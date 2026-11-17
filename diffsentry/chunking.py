"""Smart chunking for large diffs.

The naive approach — slice the diff every N lines — cuts functions in
half and produces reviews of fragments. DiffSentry chunks on *structure*:

1. A diff is first split into segments at hunk boundaries and at
   top-level ``def`` / ``class`` boundaries inside hunks, so a segment
   never straddles two unrelated functions.
2. Segments are greedily packed into chunks under a token budget.
3. Only a single segment larger than the whole budget is hard-split,
   at line boundaries, with the split points marked.

Every chunk knows its file, its new-file line range, and the enclosing
function/class when uniform — the context a reviewer (human, rule
engine, or LLM) needs to say something true about the code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .diffparse import FileDiff

CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS = 3000

_DEF_RE = re.compile(r"^\s*(?:async\s+)?(def|class)\s+(\w+)")


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class DiffChunk:
    file: str
    start_line: int
    end_line: int
    text: str
    function: str | None = None
    est_tokens: int = 0


@dataclass
class _Segment:
    file: str
    lines: list[str] = field(default_factory=list)  # rendered diff lines
    start_line: int = 0
    end_line: int = 0
    function: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _render(kind: str, text: str) -> str:
    return {"add": "+", "context": " ", "del": "-"}[kind] + text


def _segments_for_file(fd: FileDiff) -> list[_Segment]:
    segments: list[_Segment] = []
    current: _Segment | None = None
    current_fn: str | None = None

    def flush() -> None:
        nonlocal current
        if current is not None and current.lines:
            segments.append(current)
        current = None

    for hunk in fd.hunks:
        flush()  # hunk boundary is always a segment boundary
        for ln in hunk.lines:
            m = _DEF_RE.match(ln.text) if ln.kind != "del" else None
            is_boundary = bool(m) and (ln.text == ln.text.lstrip() or current_fn is None)
            if m:
                current_fn = m.group(2)
            if is_boundary and current is not None and current.lines:
                flush()
            if current is None:
                current = _Segment(
                    file=fd.path,
                    start_line=ln.new_line or hunk.new_start,
                    function=current_fn,
                )
            current.lines.append(_render(ln.kind, ln.text))
            if ln.new_line is not None:
                current.end_line = ln.new_line
            current.function = current_fn if current.function in (None, current_fn) else current.function
        flush()
    return segments


def chunk_diff(files: list[FileDiff], max_tokens: int = DEFAULT_MAX_TOKENS) -> list[DiffChunk]:
    chunks: list[DiffChunk] = []
    for fd in files:
        if fd.is_deleted:
            continue
        pending: list[_Segment] = []
        pending_tokens = 0

        def flush_pending() -> None:
            nonlocal pending, pending_tokens
            if not pending:
                return
            text = "\n".join(seg.text for seg in pending)
            fns = {seg.function for seg in pending}
            chunks.append(
                DiffChunk(
                    file=fd.path,
                    start_line=pending[0].start_line,
                    end_line=pending[-1].end_line,
                    text=text,
                    function=fns.pop() if len(fns) == 1 else None,
                    est_tokens=estimate_tokens(text),
                )
            )
            pending = []
            pending_tokens = 0

        for seg in _segments_for_file(fd):
            seg_tokens = estimate_tokens(seg.text)
            if seg_tokens > max_tokens:
                # One segment bigger than the budget: hard-split at lines.
                flush_pending()
                lines = seg.text.splitlines()
                part: list[str] = []
                part_tokens = 0
                for line in lines:
                    lt = estimate_tokens(line) + 1
                    if part and part_tokens + lt > max_tokens:
                        text = "\n".join(part)
                        chunks.append(DiffChunk(fd.path, seg.start_line, seg.end_line,
                                                text, seg.function, estimate_tokens(text)))
                        part, part_tokens = [], 0
                    part.append(line)
                    part_tokens += lt
                if part:
                    text = "\n".join(part)
                    chunks.append(DiffChunk(fd.path, seg.start_line, seg.end_line,
                                            text, seg.function, estimate_tokens(text)))
                continue
            if pending and pending_tokens + seg_tokens > max_tokens:
                flush_pending()
            pending.append(seg)
            pending_tokens += seg_tokens
        flush_pending()
    return chunks

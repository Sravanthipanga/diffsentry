"""Unified-diff parsing: files, hunks, and added lines with the line
numbers they will have in the *new* file (the numbers a reviewer — and
a GitHub comment — must reference)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    kind: str  # "add" | "context" | "del"
    text: str
    new_line: int | None  # line number in the new file (None for deletions)


@dataclass
class Hunk:
    old_start: int
    new_start: int
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def added(self) -> list[DiffLine]:
        return [ln for ln in self.lines if ln.kind == "add"]


@dataclass
class FileDiff:
    path: str  # new-file path ("b/..." stripped)
    old_path: str | None = None
    is_new: bool = False
    is_deleted: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_lines(self) -> list[DiffLine]:
        return [ln for h in self.hunks for ln in h.added]

    def added_text(self) -> str:
        """The added lines as a plain block (for whole-file style checks)."""
        return "\n".join(ln.text for ln in self.added_lines)


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    new_line_no = 0

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            parts = raw.split(" ")
            old = parts[2][2:] if len(parts) > 2 and parts[2].startswith("a/") else None
            new = parts[3][2:] if len(parts) > 3 and parts[3].startswith("b/") else None
            current = FileDiff(path=new or old or "unknown", old_path=old)
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if raw.startswith("new file mode"):
            current.is_new = True
            continue
        if raw.startswith("deleted file mode"):
            current.is_deleted = True
            continue
        if raw.startswith("+++ "):
            if raw[4:] != "/dev/null":
                current.path = raw[4:].removeprefix("b/")
            continue
        if raw.startswith("--- "):
            continue
        m = _HUNK_RE.match(raw)
        if m:
            hunk = Hunk(old_start=int(m.group(1)), new_start=int(m.group(3)))
            current.hunks.append(hunk)
            new_line_no = hunk.new_start
            continue
        if hunk is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            hunk.lines.append(DiffLine("add", raw[1:], new_line_no))
            new_line_no += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            hunk.lines.append(DiffLine("del", raw[1:], None))
        elif raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            text_line = raw[1:] if raw.startswith(" ") else raw
            hunk.lines.append(DiffLine("context", text_line, new_line_no))
            new_line_no += 1
    return [f for f in files if f.hunks or f.is_new]

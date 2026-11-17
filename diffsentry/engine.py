"""Review orchestration: diff -> chunks -> engine -> structured result.

The static engine reads whole files/hunks (it is not token-bound), but
it runs through the same chunk accounting so the result reports what
was covered. LLM engines are genuinely chunk-driven: one schema-bound
call per chunk.
"""

from __future__ import annotations

import time

from .chunking import chunk_diff
from .diffparse import FileDiff
from .rules import StaticAnalyzer
from .schema import CodeReviewResult


def review_diff(files: list[FileDiff], engine: str = "static",
                max_tokens: int = 3000) -> CodeReviewResult:
    started = time.perf_counter()
    chunks = chunk_diff(files, max_tokens=max_tokens)
    reviewed_files = len({f.path for f in files if not f.is_deleted})

    if engine == "static":
        issues = StaticAnalyzer().review(files)
        engine_name = "static"
    else:
        from .llm import get_llm_analyzer

        analyzer = get_llm_analyzer(engine)
        issues = analyzer.review_chunks(chunks)
        engine_name = analyzer.name
        # The static engine's diff-level checks (missing tests, leaked
        # keys) are cheap and deterministic — always include them; the
        # LLM adds judgement on top.
        static_issues = StaticAnalyzer().review(files)
        seen = {(i.file, i.line_number, i.rule) for i in issues}
        issues.extend(i for i in static_issues
                      if (i.file, i.line_number, i.rule) not in seen)

    return CodeReviewResult(
        issues=issues,
        files_reviewed=reviewed_files,
        chunks_reviewed=len(chunks),
        engine=engine_name,
        duration_seconds=round(time.perf_counter() - started, 3),
    )

"""Structured output schema — the contract every review must satisfy.

Whether a finding comes from the deterministic rule engine or from an
LLM, it is a ``ReviewIssue`` validated by Pydantic. There is no
free-form review text anywhere in the system: no regex scraping of
model prose, no "the model said something like...". If it doesn't
validate against this schema, it doesn't ship.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"high": 3, "medium": 2, "low": 1}[self.value]


class Category(str, Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    ERROR_HANDLING = "error-handling"
    CORRECTNESS = "correctness"
    TEST_COVERAGE = "test-coverage"
    MAINTAINABILITY = "maintainability"


class ReviewIssue(BaseModel):
    """One finding, anchored to an exact location in the new file."""

    file: str
    line_number: int = Field(ge=1)
    severity: Severity
    category: Category
    rule: str = Field(description="Stable rule id, e.g. 'sql-string-concat'")
    explanation: str
    suggested_fix: str
    code: str = ""  # the offending line, for display


class CodeReviewResult(BaseModel):
    """The full structured review of one diff."""

    issues: list[ReviewIssue] = Field(default_factory=list)
    files_reviewed: int = 0
    chunks_reviewed: int = 0
    engine: str = "static"
    duration_seconds: float = 0.0

    @computed_field
    @property
    def counts(self) -> dict[str, int]:
        out = {"high": 0, "medium": 0, "low": 0}
        for issue in self.issues:
            out[issue.severity.value] += 1
        return out

    @property
    def total(self) -> int:
        return len(self.issues)

    def worst(self) -> Severity | None:
        if not self.issues:
            return None
        return max((i.severity for i in self.issues), key=lambda s: s.rank)

    def sorted_issues(self) -> list[ReviewIssue]:
        return sorted(
            self.issues,
            key=lambda i: (-i.severity.rank, i.file, i.line_number),
        )

"""Rendering: terminal (Rich), JSON, and Markdown (for PR comments)."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .schema import CodeReviewResult, Severity

_SEV_STYLE = {Severity.HIGH: "bold red", Severity.MEDIUM: "yellow",
              Severity.LOW: "green"}
_SEV_MARK = {Severity.HIGH: "■", Severity.MEDIUM: "●", Severity.LOW: "✓"}
_SEV_EMOJI = {Severity.HIGH: "🟥", Severity.MEDIUM: "🟧", Severity.LOW: "🟩"}


def render_terminal(result: CodeReviewResult, console: Console | None = None) -> None:
    console = console or Console()
    if not result.issues:
        console.print(Panel(
            f"[bold green]No issues found[/] in {result.files_reviewed} "
            f"file(s), {result.chunks_reviewed} chunk(s) "
            f"({result.duration_seconds:.1f}s, engine: {result.engine})",
            title="DiffSentry", border_style="green"))
        return
    for issue in result.sorted_issues():
        style = _SEV_STYLE[issue.severity]
        head = Text()
        head.append(f"{_SEV_MARK[issue.severity]} {issue.severity.value.upper()}",
                    style=style)
        head.append(f"  —  {issue.file}:{issue.line_number}",
                    style="bold white")
        head.append(f"   [{issue.category.value} · {issue.rule}]",
                    style="dim")
        body = Text()
        if issue.code:
            body.append(f"  {issue.code}\n", style="dim italic")
        body.append(f"  {issue.explanation}\n")
        body.append(f"  → {issue.suggested_fix}", style="cyan")
        console.print(head)
        console.print(body)
        console.print()
    c = result.counts
    console.print(
        f"[bold]{result.total} issue(s)[/] · [red]{c['high']} high[/] · "
        f"[yellow]{c['medium']} medium[/] · [green]{c['low']} low[/] · "
        f"{result.duration_seconds:.1f}s · engine: {result.engine}")


def render_json(result: CodeReviewResult) -> str:
    return result.model_dump_json(indent=2)


def render_markdown(result: CodeReviewResult) -> str:
    lines = ["## 🛡️ DiffSentry review", ""]
    if not result.issues:
        lines.append(f"No issues found in {result.files_reviewed} file(s). ✅")
        return "\n".join(lines)
    c = result.counts
    lines.append(f"**{result.total} issue(s)** — {c['high']} high · "
                 f"{c['medium']} medium · {c['low']} low "
                 f"(engine: {result.engine}, {result.duration_seconds:.1f}s)")
    lines.append("")
    for issue in result.sorted_issues():
        lines.append(
            f"{_SEV_EMOJI[issue.severity]} **{issue.severity.value.upper()}** "
            f"— `{issue.file}:{issue.line_number}` "
            f"({issue.category.value} · `{issue.rule}`)")
        if issue.code:
            lines.append(f"> `{issue.code}`")
        lines.append(f"> {issue.explanation}")
        lines.append(f"> **Fix:** {issue.suggested_fix}")
        lines.append("")
    return "\n".join(lines)

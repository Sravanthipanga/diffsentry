"""DiffSentry CLI.

    diffsentry review --pr 142 --repo owner/name
    diffsentry review --diff changes.patch
    diffsentry review --files src/auth.py src/api.py
    diffsentry review --diff pr.patch --format markdown --post --repo o/n --pr 142

Exit code is 1 when any issue meets the --fail-on severity (default:
high), so the same command works as a local tool and as a CI gate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from .diffparse import parse_diff
from .engine import review_diff
from .render import render_json, render_markdown, render_terminal
from .schema import Severity

app = typer.Typer(help="DiffSentry — AI-powered code review for diffs and PRs.")
console = Console()


def _files_to_diff(paths: list[Path]) -> str:
    """Build a synthetic 'everything added' diff from plain files."""
    out: list[str] = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        out.append(f"diff --git a/{path} b/{path}")
        out.append("new file mode 100644")
        out.append(f"--- /dev/null")
        out.append(f"+++ b/{path}")
        out.append(f"@@ -0,0 +1,{len(lines)} @@")
        out.extend(f"+{ln}" for ln in lines)
    return "\n".join(out) + "\n"


def _git_diff(staged: bool) -> str:
    cmd = ["git", "diff", "--staged"] if staged else ["git", "diff"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise typer.BadParameter(f"git diff failed: {proc.stderr.strip()}")
    return proc.stdout


@app.command()
def review(
    pr: int = typer.Option(None, "--pr", help="Pull request number (needs --repo and GITHUB_TOKEN)"),
    repo: str = typer.Option(None, "--repo", help="owner/name for --pr and --post"),
    diff_file: Path = typer.Option(None, "--diff", help="Path to a unified diff file"),
    files: list[Path] = typer.Option(None, "--files", help="Plain files to review as additions"),
    staged: bool = typer.Option(False, "--staged", help="Review the staged git diff"),
    engine: str = typer.Option("static", "--engine", help="static | openai | anthropic"),
    max_tokens: int = typer.Option(3000, "--max-tokens", help="Per-chunk token budget"),
    fmt: str = typer.Option("terminal", "--format", help="terminal | json | markdown"),
    fail_on: str = typer.Option("high", "--fail-on", help="high | medium | low | never"),
    post: bool = typer.Option(False, "--post", help="Post the review as a PR comment"),
    output: Path = typer.Option(None, "--output", help="Write the rendered review to a file"),
) -> None:
    if pr is not None:
        if not repo:
            raise typer.BadParameter("--pr requires --repo owner/name")
        from .github import fetch_pr_diff

        diff_text = fetch_pr_diff(repo, pr)
    elif diff_file is not None:
        diff_text = diff_file.read_text(encoding="utf-8")
    elif files:
        diff_text = _files_to_diff(files)
    elif staged:
        diff_text = _git_diff(staged=True)
    else:
        diff_text = _git_diff(staged=False)
        if not diff_text.strip():
            console.print("[yellow]No unstaged changes; trying --staged...[/]")
            diff_text = _git_diff(staged=True)

    parsed = parse_diff(diff_text)
    if not parsed:
        console.print("[yellow]Nothing to review — the diff is empty.[/]")
        raise typer.Exit(0)

    try:
        result = review_diff(parsed, engine=engine, max_tokens=max_tokens)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc

    if fmt == "json":
        rendered = render_json(result)
        typer.echo(rendered)  # plain echo: Rich would wrap lines and break JSON
    elif fmt == "markdown":
        rendered = render_markdown(result)
        typer.echo(rendered)
    else:
        rendered = render_markdown(result)
        render_terminal(result, console)

    if output is not None:
        output.write_text(rendered, encoding="utf-8")
        console.print(f"[dim]Wrote {output}[/]")

    if post:
        if not repo or pr is None:
            raise typer.BadParameter("--post requires --repo and --pr")
        from .github import post_pr_comment

        url = post_pr_comment(repo, pr, render_markdown(result))
        console.print(f"[green]Posted:[/] {url}")

    if fail_on != "never":
        threshold = Severity(fail_on)
        if any(i.severity.rank >= threshold.rank for i in result.issues):
            raise typer.Exit(1)


@app.command()
def rules() -> None:
    """List the deterministic rules the static engine enforces."""
    from . import rules as _rules  # noqa: F401  (import documents the module)

    table = [
        ("sql-string-concat", "high", "security"),
        ("hardcoded-secret", "high", "security"),
        ("eval-exec", "high", "security"),
        ("unsafe-deserialization", "high", "security"),
        ("shell-injection", "high", "security"),
        ("weak-hash", "medium", "security"),
        ("missing-error-handling", "medium", "error-handling"),
        ("bare-except", "medium", "error-handling"),
        ("swallowed-exception", "low", "error-handling"),
        ("db-query-in-loop", "medium", "performance"),
        ("regex-in-loop", "low", "performance"),
        ("concat-in-loop", "low", "performance"),
        ("mutable-default-arg", "medium", "correctness"),
        ("assert-in-production", "low", "correctness"),
        ("missing-tests", "medium", "test-coverage"),
    ]
    for rule, sev, cat in table:
        console.print(f"[bold]{rule:<26}[/] {sev:<7} {cat}")


if __name__ == "__main__":
    app()

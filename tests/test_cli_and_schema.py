import json
from pathlib import Path

from typer.testing import CliRunner

from diffsentry.cli import app
from diffsentry.schema import CodeReviewResult, ReviewIssue, Severity

SAMPLES = Path(__file__).resolve().parents[1] / "eval" / "samples"
runner = CliRunner()


def test_schema_counts_and_sorting():
    result = CodeReviewResult(issues=[
        ReviewIssue(file="b.py", line_number=5, severity=Severity.LOW,
                    category="performance", rule="r1", explanation="e",
                    suggested_fix="f"),
        ReviewIssue(file="a.py", line_number=2, severity=Severity.HIGH,
                    category="security", rule="r2", explanation="e",
                    suggested_fix="f"),
    ])
    assert result.counts == {"high": 1, "medium": 0, "low": 1}
    assert result.sorted_issues()[0].file == "a.py"
    assert result.worst() == Severity.HIGH
    # The whole result round-trips through JSON (structured output contract).
    assert CodeReviewResult.model_validate_json(
        result.model_dump_json()).total == 2


def test_cli_reviews_files_and_fails_on_high():
    proc = runner.invoke(app, ["review", "--files", str(SAMPLES / "bad_auth.py"),
                               "--format", "json"])
    assert proc.exit_code == 1  # HIGH findings with default --fail-on high
    data = json.loads(proc.stdout)
    rules = {i["rule"] for i in data["issues"]}
    assert "sql-string-concat" in rules


def test_cli_clean_file_exits_zero(tmp_path):
    test_file = tmp_path / "test_dummy.py"
    test_file.write_text("def test_dummy():\n    assert True\n")
    proc = runner.invoke(app, ["review", "--files",
                               str(SAMPLES / "clean_service.py"),
                               "--files", str(test_file),
                               "--format", "json"])
    assert proc.exit_code == 0
    assert json.loads(proc.stdout)["issues"] == []


def test_cli_markdown_format():
    proc = runner.invoke(app, ["review", "--files", str(SAMPLES / "bad_api.py"),
                               "--format", "markdown", "--fail-on", "never"])
    assert proc.exit_code == 0
    assert "DiffSentry review" in proc.stdout
    assert "missing-error-handling" in proc.stdout

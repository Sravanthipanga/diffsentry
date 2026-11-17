from pathlib import Path

from diffsentry.cli import _files_to_diff
from diffsentry.diffparse import parse_diff
from diffsentry.rules import StaticAnalyzer

SAMPLES = Path(__file__).resolve().parents[1] / "eval" / "samples"

TEST_DIFF = (
    "diff --git a/tests/test_x.py b/tests/test_x.py\n"
    "new file mode 100644\n--- /dev/null\n+++ b/tests/test_x.py\n"
    "@@ -0,0 +1,1 @@\n+def test_x(): pass\n"
)


def _rules_for(sample: str, with_tests: bool = True) -> set[str]:
    files = parse_diff(_files_to_diff([SAMPLES / sample]))
    if with_tests:
        files += parse_diff(TEST_DIFF)
    return {i.rule for i in StaticAnalyzer().review(files)
            if i.file.endswith(sample)}


def test_sql_concat_and_fstring_flagged():
    rules = _rules_for("bad_auth.py")
    assert "sql-string-concat" in rules
    assert "hardcoded-secret" in rules
    assert "eval-exec" in rules


def test_error_handling_rules():
    rules = _rules_for("bad_api.py")
    assert {"missing-error-handling", "bare-except", "swallowed-exception"} <= rules


def test_performance_rules():
    rules = _rules_for("bad_perf.py")
    assert {"db-query-in-loop", "regex-in-loop", "concat-in-loop"} <= rules


def test_correctness_and_security_rules():
    rules = _rules_for("bad_core.py")
    assert {"mutable-default-arg", "unsafe-deserialization", "shell-injection",
            "weak-hash", "assert-in-production"} <= rules


def test_clean_sample_has_no_findings():
    assert _rules_for("clean_service.py") == set()


def test_missing_tests_rule_fires_without_test_changes():
    rules = _rules_for("bad_new_feature.py", with_tests=False)
    assert rules == {"missing-tests"}


def test_line_numbers_point_at_added_lines():
    diff = _files_to_diff([SAMPLES / "bad_auth.py"])
    issues = StaticAnalyzer().review(parse_diff(diff))
    secret = next(i for i in issues if i.rule == "hardcoded-secret")
    assert secret.line_number == 3  # DB_PASSWORD line in the sample
    assert secret.severity.value == "high"

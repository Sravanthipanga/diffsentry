"""Golden-set evaluation for DiffSentry's static engine.

Each sample is reviewed as an added file (with a test-file change in
the same diff unless the case says otherwise). Findings are matched to
expectations by (file, rule):

  precision = matched predictions / all predictions
  recall    = matched expectations / all expectations

Gate (eval/cases.json thresholds): precision >= 0.80, recall >= 0.85.
Writes eval/report.json; exit 1 on gate failure.

Usage:  python eval/run_eval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from diffsentry.cli import _files_to_diff  # noqa: E402
from diffsentry.diffparse import parse_diff  # noqa: E402
from diffsentry.engine import review_diff  # noqa: E402

TEST_FILE = Path("tests/test_placeholder.py")
TEST_CONTENT = "def test_placeholder():\n    assert True\n"


def _review(case: dict) -> set[tuple[str, str]]:
    sample = BASE / "eval" / "samples" / case["file"]
    paths = [sample]
    tmp_test = None
    if case.get("with_tests"):
        tmp_test = BASE / "eval" / "samples" / "_eval_test_placeholder.py"
        tmp_test.write_text(TEST_CONTENT)
        paths.append(tmp_test)
    try:
        diff_text = _files_to_diff(paths)
    finally:
        if tmp_test is not None:
            tmp_test.unlink(missing_ok=True)
    # _files_to_diff embeds full paths; normalize to basenames.
    result = review_diff(parse_diff(diff_text))
    return {(Path(i.file).name, i.rule) for i in result.issues
            if Path(i.file).name == case["file"]}


def main() -> int:
    spec = json.loads((BASE / "eval" / "cases.json").read_text())
    thresholds = spec["thresholds"]
    expected_total: set[tuple[str, str]] = set()
    predicted_total: set[tuple[str, str]] = set()
    per_case = []

    for case in spec["cases"]:
        expected = {(case["file"], e["rule"]) for e in case["expected"]}
        predicted = _review(case)
        expected_total |= expected
        predicted_total |= predicted
        per_case.append({
            "file": case["file"],
            "expected": sorted(r for _, r in expected),
            "predicted": sorted(r for _, r in predicted),
            "missed": sorted(r for _, r in expected - predicted),
            "false_positives": sorted(r for _, r in predicted - expected),
        })

    matched = expected_total & predicted_total
    precision = len(matched) / len(predicted_total) if predicted_total else 1.0
    recall = len(matched) / len(expected_total) if expected_total else 1.0

    print(f"{'file':<22} {'expected':>8} {'found':>6}  missed / false-positives")
    print("-" * 78)
    for row in per_case:
        print(f"{row['file']:<22} {len(row['expected']):>8} "
              f"{len(row['predicted']):>6}  {row['missed']} / {row['false_positives']}")
    print(f"\nprecision {precision:.4f} (>= {thresholds['precision']})   "
          f"recall {recall:.4f} (>= {thresholds['recall']})")

    report = {"precision": round(precision, 4), "recall": round(recall, 4),
              "thresholds": thresholds, "cases": per_case}
    (BASE / "eval" / "report.json").write_text(json.dumps(report, indent=1))

    failed = []
    if precision < thresholds["precision"]:
        failed.append("precision")
    if recall < thresholds["recall"]:
        failed.append("recall")
    if failed:
        print(f"EVAL GATE FAILED: {', '.join(failed)}")
        return 1
    print("EVAL GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

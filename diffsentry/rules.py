"""The deterministic rule engine.

Two layers, both anchored to exact new-file line numbers:

- **AST rules** for Python: each hunk's context+added lines are
  reconstructed into a parseable block (whole added files parse
  directly); findings map back through the block's line table.
- **Line rules** for everything else (and as a safety net): secret
  shapes and dangerous-call patterns that are unambiguous on one line.

Every rule emits the shared ``ReviewIssue`` schema — the same contract
the LLM engine must satisfy — so engines are interchangeable and the
eval harness scores them identically.
"""

from __future__ import annotations

import ast
import re
import textwrap

from .diffparse import FileDiff
from .schema import Category, ReviewIssue, Severity

SECRET_NAME_RE = re.compile(r"(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)", re.I)
PLACEHOLDER_RE = re.compile(r"(changeme|example|placeholder|xxx+|\.\.\.|<.*>|\$\{|os\.environ|getenv)", re.I)
AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
GENERIC_SECRET_ASSIGN_RE = re.compile(
    r"""(password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['"][^'"]{8,}['"]""", re.I
)

HTTP_CALLS = {"requests.get", "requests.post", "requests.put", "requests.patch",
              "requests.delete", "requests.request", "httpx.get", "httpx.post",
              "httpx.put", "httpx.delete", "urllib.request.urlopen"}


def _issue(fd: FileDiff, line: int, severity: Severity, category: Category,
           rule: str, explanation: str, fix: str, code: str = "") -> ReviewIssue:
    return ReviewIssue(file=fd.path, line_number=max(1, line), severity=severity,
                       category=category, rule=rule, explanation=explanation,
                       suggested_fix=fix, code=code.strip()[:160])


def _dotted_name(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


class _AstVisitor(ast.NodeVisitor):
    """One pass over a reconstructed block, tracking try/loop ancestry."""

    def __init__(self, fd: FileDiff, line_map: list[int], source_lines: list[str]):
        self.fd = fd
        self.line_map = line_map  # block line index (0-based) -> new-file line
        self.source_lines = source_lines
        self.issues: list[ReviewIssue] = []
        self._try_depth = 0
        self._loop_depth = 0

    def _line(self, node: ast.AST) -> int:
        idx = (node.lineno or 1) - 1
        return self.line_map[idx] if 0 <= idx < len(self.line_map) else 1

    def _code(self, node: ast.AST) -> str:
        idx = (node.lineno or 1) - 1
        return self.source_lines[idx] if 0 <= idx < len(self.source_lines) else ""

    def _add(self, node, severity, category, rule, explanation, fix):
        self.issues.append(_issue(self.fd, self._line(node), severity, category,
                                  rule, explanation, fix, self._code(node)))

    # ------------------------------------------------------------ context
    def visit_Try(self, node: ast.Try):
        self._try_depth += 1
        for child in node.body:
            self.visit(child)
        self._try_depth -= 1
        for handler in node.handlers:
            self.visit(handler)
        for child in node.orelse + node.finalbody:
            self.visit(child)

    visit_TryStar = visit_Try

    def _visit_loop(self, node):
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    visit_For = _visit_loop
    visit_While = _visit_loop
    visit_AsyncFor = _visit_loop

    # -------------------------------------------------------------- rules
    def visit_Call(self, node: ast.Call):
        name = _dotted_name(node.func)
        short = name.rsplit(".", 1)[-1]

        if short in ("execute", "executemany", "raw") and node.args:
            arg = node.args[0]
            if isinstance(arg, (ast.BinOp, ast.JoinedStr)) or (
                isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "format"
            ):
                self._add(node, Severity.HIGH, Category.SECURITY, "sql-string-concat",
                          "SQL query built by string concatenation/formatting — "
                          "user input can break out of the query (SQL injection).",
                          "Use parameterized queries: cursor.execute(sql, params) "
                          "with %s placeholders.")
            if self._loop_depth:
                self._add(node, Severity.MEDIUM, Category.PERFORMANCE, "db-query-in-loop",
                          "Database query executed inside a loop — the classic "
                          "N+1 pattern; latency grows linearly with row count.",
                          "Batch the query (IN clause / join) or prefetch outside "
                          "the loop.")
        if name in ("eval", "exec"):
            self._add(node, Severity.HIGH, Category.SECURITY, "eval-exec",
                      f"{name}() executes arbitrary code strings; any tainted "
                      "input becomes remote code execution.",
                      "Replace with a safe parser (ast.literal_eval) or an "
                      "explicit dispatch table.")
        if name in ("pickle.load", "pickle.loads", "marshal.loads"):
            self._add(node, Severity.HIGH, Category.SECURITY, "unsafe-deserialization",
                      f"{name} can execute arbitrary code while deserializing "
                      "untrusted data.",
                      "Use a safe format (JSON) or sign and verify payloads "
                      "before unpickling.")
        if name == "yaml.load" and not any(
            _dotted_name(kw.value).endswith("SafeLoader") for kw in node.keywords
            if kw.arg == "Loader"
        ) and len(node.args) < 2:
            self._add(node, Severity.HIGH, Category.SECURITY, "unsafe-deserialization",
                      "yaml.load without SafeLoader can construct arbitrary "
                      "Python objects from untrusted YAML.",
                      "Use yaml.safe_load(...) or Loader=yaml.SafeLoader.")
        if name in ("hashlib.md5", "hashlib.sha1"):
            self._add(node, Severity.MEDIUM, Category.SECURITY, "weak-hash",
                      f"{name} is collision-broken / too fast for password or "
                      "integrity use.",
                      "Use hashlib.sha256+ for integrity, bcrypt/argon2 for "
                      "passwords.")
        if name == "os.system" or (
            name.startswith("subprocess.") and any(
                kw.arg == "shell" and isinstance(kw.value, ast.Constant)
                and kw.value.value is True for kw in node.keywords)
        ):
            self._add(node, Severity.HIGH, Category.SECURITY, "shell-injection",
                      "Shell execution with shell=True / os.system allows "
                      "command injection from any interpolated input.",
                      "Pass an argv list to subprocess.run([...]) without "
                      "shell=True.")
        if name in HTTP_CALLS and self._try_depth == 0:
            self._add(node, Severity.MEDIUM, Category.ERROR_HANDLING,
                      "missing-error-handling",
                      f"{name} call has no surrounding try/except — network "
                      "failures and non-2xx responses will crash or silently "
                      "misbehave.",
                      "Wrap in try/except around the request library's "
                      "exception type, and check response status / set a "
                      "timeout.")
        if name in ("re.compile", "re.search", "re.match", "re.findall") and self._loop_depth:
            self._add(node, Severity.LOW, Category.PERFORMANCE, "regex-in-loop",
                      f"{name} runs on every loop iteration; the pattern is "
                      "recompiled/re-matched repeatedly.",
                      "Compile the pattern once at module level "
                      "(PATTERN = re.compile(...)) and reuse it.")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is None:
            self._add(node, Severity.MEDIUM, Category.ERROR_HANDLING, "bare-except",
                      "Bare 'except:' catches everything — including "
                      "KeyboardInterrupt, SystemExit, and real bugs — and "
                      "hides them.",
                      "Catch the specific exception types you expect "
                      "(except ValueError, requests.Timeout, ...).")
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self._add(node, Severity.LOW, Category.ERROR_HANDLING,
                      "swallowed-exception",
                      "Exception is caught and silently swallowed with "
                      "'pass' — failures become invisible.",
                      "Log the exception (logger.exception(...)) or "
                      "re-raise / handle it explicitly.")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(default, ast.Call)
                and _dotted_name(default.func) in ("list", "dict", "set")
            ):
                self._add(node, Severity.MEDIUM, Category.CORRECTNESS,
                          "mutable-default-arg",
                          f"Mutable default argument in '{node.name}' is "
                          "created once and shared across all calls — state "
                          "leaks between invocations.",
                          "Default to None and create the object inside the "
                          "function.")
                break
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            value = node.value.value
            for target in node.targets:
                name = _dotted_name(target)
                if SECRET_NAME_RE.search(name) and len(value) >= 6 \
                        and not PLACEHOLDER_RE.search(value):
                    self._add(node, Severity.HIGH, Category.SECURITY,
                              "hardcoded-secret",
                              f"Hardcoded credential assigned to '{name}' — "
                              "secrets in source leak with the repo and can "
                              "never be rotated safely.",
                              "Read it from the environment "
                              "(os.environ[...]) or a secrets manager.")
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        if "test" not in self.fd.path:
            self._add(node, Severity.LOW, Category.CORRECTNESS, "assert-in-production",
                      "assert statements are stripped when Python runs with "
                      "-O, so this check silently disappears in optimized "
                      "deployments.",
                      "Raise an explicit exception (ValueError/TypeError) "
                      "for runtime validation.")
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        if self._loop_depth and isinstance(node.op, ast.Add):
            self._add(node, Severity.LOW, Category.PERFORMANCE,
                      "concat-in-loop",
                      "Repeated += accumulation inside a loop can be "
                      "quadratic for strings and hides the real cost.",
                      "Collect parts in a list and ''.join(...) once, or "
                      "use a builder / comprehension.")
        self.generic_visit(node)


def _ast_issues_for_block(fd: FileDiff, block_lines: list[str],
                          line_map: list[int]) -> list[ReviewIssue]:
    source = textwrap.dedent("\n".join(block_lines))
    # dedent may change columns but not line order/count, so the map holds.
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = _AstVisitor(fd, line_map, block_lines)
    visitor.visit(tree)
    return visitor.issues


def _python_ast_issues(fd: FileDiff) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    for hunk in fd.hunks:
        block = [ln.text for ln in hunk.lines if ln.kind in ("add", "context")]
        line_map = [ln.new_line or 1 for ln in hunk.lines if ln.kind in ("add", "context")]
        if block:
            issues.extend(_ast_issues_for_block(fd, block, line_map))
    return issues


def _line_issues(fd: FileDiff) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    for ln in fd.added_lines:
        text = ln.text
        if AWS_KEY_RE.search(text):
            issues.append(_issue(fd, ln.new_line or 1, Severity.HIGH,
                                 Category.SECURITY, "hardcoded-secret",
                                 "AWS access key id committed to source.",
                                 "Revoke the key and move it to the "
                                 "environment / a secrets manager.", text))
        elif PRIVATE_KEY_RE.search(text):
            issues.append(_issue(fd, ln.new_line or 1, Severity.HIGH,
                                 Category.SECURITY, "hardcoded-secret",
                                 "Private key material committed to source.",
                                 "Remove the key, rotate it, and load keys "
                                 "from a secrets manager.", text))
        elif GENERIC_SECRET_ASSIGN_RE.search(text) and not PLACEHOLDER_RE.search(text):
            issues.append(_issue(fd, ln.new_line or 1, Severity.HIGH,
                                 Category.SECURITY, "hardcoded-secret",
                                 "Hardcoded credential assigned in source.",
                                 "Read it from the environment "
                                 "(os.environ[...]) or a secrets manager.", text))
    return issues


TEST_PATH_RE = re.compile(r"(^|/)(tests?|spec|__tests__)(/|_)|(_test|test_|\.test\.|\.spec\.)", re.I)
SOURCE_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rb")


def _test_coverage_issues(files: list[FileDiff]) -> list[ReviewIssue]:
    """New production code with no test change anywhere in the diff."""
    has_test_change = any(TEST_PATH_RE.search(f.path) for f in files)
    if has_test_change:
        return []
    issues: list[ReviewIssue] = []
    for fd in files:
        if TEST_PATH_RE.search(fd.path) or not fd.path.endswith(SOURCE_EXTS):
            continue
        new_defs = [ln for ln in fd.added_lines
                    if re.match(r"\s*(async\s+)?(def|class|function|func)\s+\w+", ln.text)]
        if new_defs:
            first = new_defs[0]
            issues.append(_issue(
                fd, first.new_line or 1, Severity.MEDIUM, Category.TEST_COVERAGE,
                "missing-tests",
                f"This change adds {len(new_defs)} new function/class "
                "definition(s) but the diff contains no test changes — the "
                "new code lands unverified.",
                "Add tests covering the new behaviour in the same PR.",
                first.text))
    return issues


class StaticAnalyzer:
    """Deterministic engine: same diff in, same review out. No keys, no
    network — this is what runs in CI and in the eval harness."""

    name = "static"

    def review(self, files: list[FileDiff]) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        for fd in files:
            if fd.is_deleted:
                continue
            issues.extend(_line_issues(fd))
            if fd.path.endswith(".py"):
                issues.extend(_python_ast_issues(fd))
        issues.extend(_test_coverage_issues(files))
        seen: set[tuple] = set()
        unique: list[ReviewIssue] = []
        for issue in issues:
            key = (issue.file, issue.line_number, issue.rule)
            if key not in seen:
                seen.add(key)
                unique.append(issue)
        return unique

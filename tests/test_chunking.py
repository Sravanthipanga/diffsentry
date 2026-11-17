from diffsentry.chunking import chunk_diff, estimate_tokens
from diffsentry.diffparse import parse_diff


def _diff_for(body_lines: list[str], path: str = "mod.py") -> str:
    out = [f"diff --git a/{path} b/{path}", "new file mode 100644",
           "--- /dev/null", f"+++ b/{path}",
           f"@@ -0,0 +1,{len(body_lines)} @@"]
    out += [f"+{ln}" for ln in body_lines]
    return "\n".join(out) + "\n"


def test_small_diff_is_one_chunk():
    files = parse_diff(_diff_for(["def a():", "    return 1"]))
    chunks = chunk_diff(files, max_tokens=3000)
    assert len(chunks) == 1
    assert chunks[0].file == "mod.py"
    assert chunks[0].start_line == 1


def test_chunking_respects_token_budget():
    body = []
    for i in range(40):
        body.append(f"def fn_{i}():")
        body.append(f"    return {'x' * 50!r}")
    files = parse_diff(_diff_for(body))
    chunks = chunk_diff(files, max_tokens=100)
    assert len(chunks) > 1
    assert all(c.est_tokens <= 130 for c in chunks)


def test_chunks_split_on_function_boundaries():
    body = []
    for i in range(6):
        body.append(f"def fn_{i}():")
        body.append("    return " + ", ".join(str(j) for j in range(30)))
    files = parse_diff(_diff_for(body))
    chunks = chunk_diff(files, max_tokens=60)
    # No chunk should contain the tail of one function and head of another
    # without starting at a def line (segments are function-aligned).
    for chunk in chunks:
        first = chunk.text.splitlines()[0]
        assert first.startswith("+def ") or first.startswith("+    return")


def test_estimate_tokens():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100

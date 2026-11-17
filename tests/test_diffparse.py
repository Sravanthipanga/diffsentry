from diffsentry.diffparse import parse_diff

DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@ def main():
 context
-old line
+new line
+another
 tail
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+first
+second
"""


def test_parse_files_and_hunks():
    files = parse_diff(DIFF)
    assert [f.path for f in files] == ["src/app.py", "new.py"]
    assert files[1].is_new is True


def test_added_lines_carry_new_file_numbers():
    files = parse_diff(DIFF)
    added = files[0].added_lines
    assert [(ln.text, ln.new_line) for ln in added] == [
        ("new line", 11), ("another", 12)]
    assert files[1].added_lines[0].new_line == 1

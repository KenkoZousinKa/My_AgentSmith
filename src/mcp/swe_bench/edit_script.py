"""edit_file がコンテナの中で実行する Python スクリプト.

使い方: python3 -c EDIT_SCRIPT <filepath> <old_strのbase64> <new_strのbase64>
    3つの引数はすべて shlex.quote する（new_str が空のとき base64 も空になり、quote しないと引数が消える）
exit code: 0 成功 / 1 失敗（どちらも理由は stdout に1行）
"""

EDIT_SCRIPT = r'''
import base64
import sys

path = sys.argv[1]
old = base64.b64decode(sys.argv[2]).decode("utf-8")
new = base64.b64decode(sys.argv[3]).decode("utf-8")


def fail(message):
    print("Error: " + message)
    sys.exit(1)


if old == "":
    fail("old_str must not be empty.")
try:
    with open(path, encoding="utf-8", newline="") as f:
        content = f.read()
except FileNotFoundError:
    fail("file not found: " + path)
except IsADirectoryError:
    fail("is a directory: " + path)
except UnicodeDecodeError:  # bin
    fail("file is not valid UTF-8: " + path)
except OSError as e:
    fail("cannot read " + path + ": " + str(e))

count = content.count(old)
if count == 0:
    fail("old_str was not found in " + path
         + ". It must match the file exactly, including whitespace and indentation.")
if count > 1:
    fail("old_str was found " + str(count) + " times in " + path
         + ". Include more surrounding lines so that it matches exactly once.")

line = content.count("\n", 0, content.index(old)) + 1
updated = content.replace(old, new, 1)
if path.endswith(".py"):
    try:
        compile(updated.replace("\r\n", "\n"), path, "exec")
    except SyntaxError as e:
        fail("syntax error at line " + str(e.lineno) + ": " + str(e.msg) + " (file was not modified)")
try:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(updated)
except OSError as e:
    fail("cannot write " + path + ": " + str(e))
print("Edited " + path + " (replaced 1 occurrence starting at line " + str(line) + ").")
'''

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
# ↑ base64 は英数字と +/= だけなので、シェルを通しても壊れない。ここで元の文字列に戻す


def fail(message):
    print("Error: " + message)
    sys.exit(1)


if old == "":
    fail("old_str must not be empty.")
try:
    with open(path, encoding="utf-8", newline="") as f:
        content = f.read()
        # ↑ newline="" で、\r\n を \n に変えずに読む（書き戻しても改行コードが変わらない）
except FileNotFoundError:
    fail("file not found: " + path)
except IsADirectoryError:
    fail("is a directory: " + path)
except UnicodeDecodeError:  # バイナリをそのまま読もうとした
    fail("file is not valid UTF-8: " + path)
except OSError as e:
    fail("cannot read " + path + ": " + str(e))
    # ↑ 権限がないなど、ほかの読み込みエラー（OSError は FileNotFoundError などの親クラスなので、最後に置く）

count = content.count(old)
if count == 0:
    fail("old_str was not found in " + path
         + ". It must match the file exactly, including whitespace and indentation.")
if count > 1:
    fail("old_str was found " + str(count) + " times in " + path
         + ". Include more surrounding lines so that it matches exactly once.")

line = content.count("\n", 0, content.index(old)) + 1
# ↑ 置きかえ位置より前にある改行の数 + 1 = 置きかえが始まる行番号
# indexが置き換え開始位置までの文字数、そこまで何回改行があったか
try:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content.replace(old, new, 1))
except OSError as e:
    fail("cannot write " + path + ": " + str(e))
print("Edited " + path + " (replaced 1 occurrence starting at line " + str(line) + ").")
'''

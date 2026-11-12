"""7問目（sympy-21930）で、本物の run_tests() を元のコード → 正解のパッチの一部 → 全部の順に回す（LLM なし）."""
import json
import pathlib
import sys
import time

repo, work = sys.argv[1], pathlib.Path(sys.argv[2])
sys.path.insert(0, repo)
import mcp_tools_swebench as tools  # noqa: E402

task = json.loads((work / "sympy__sympy-21930.json").read_text())
gold = (work / "sympy__sympy-21930.gold.diff").read_text()
header, *hunks = gold.split("\n@@")
hunks = ["@@" + hunk for hunk in hunks]
tools.setup({tools.META_KEY: {"docker_image": task["docker_image"], "eval_script": task["eval_script"], "testbed_path": "/testbed"}})
try:
    def check(label: str) -> None:
        started = time.monotonic()
        output = tools.run_tests()
        (work / f"run_tests.{label}.txt").write_text(output)
        print(label, f"{time.monotonic() - started:.0f}s", "|", output.splitlines()[-1], flush=True)
    check("original")
    for number, hunk in enumerate(hunks, start=1):
        patch = header + "\n" + hunk.rstrip("\n") + "\n"
        applied = tools.executor.run("git apply -", "/testbed", tools.COMMAND_TIMEOUT, input=patch)
        print("apply hunk", number, applied.exit_code, applied.stderr[:200] if hasattr(applied, "stderr") else "", flush=True)
        check(f"hunk{number}")
    status = tools.executor.run("git status --short", "/testbed", tools.COMMAND_TIMEOUT).stdout.strip()
    print("git status:", status)
finally:
    tools.executor.close()
    tools.executor = tools.LocalExecutor()

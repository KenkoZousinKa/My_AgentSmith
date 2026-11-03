"""task.json（AIに渡したイシュー）と solution.json（各Stepの思考・コード・Observation）を表示するスクリプト.

使い方:
    uv run python -m test.mcp.show_trace
    uv run python -m test.mcp.show_trace ../cache/swebench_task.json ../cache/swebench_solution.json
"""

import json
import sys
from pathlib import Path


def main() -> None:
    task_path = Path(sys.argv[1] if len(sys.argv) > 1 else "../cache/swebench_task.json")
    sol_path = Path(sys.argv[2] if len(sys.argv) > 2 else "../cache/swebench_solution.json")

    if task_path.exists():
        t = json.loads(task_path.read_text(encoding="utf-8"))
        print("=" * 60)
        print(f"[TASK] {t.get('instance_id') or t.get('task_id')}  (repo: {t.get('repo', '')})")
        print("=" * 60)
        print("[Issue / Problem Statement]")
        print(t.get("problem_statement") or t.get("task_definition") or "")
        if t.get("hints_text"):
            print("\n[Hints]")
            print(t["hints_text"])
        print()

    if sol_path.exists():
        s = json.loads(sol_path.read_text(encoding="utf-8"))
        print("=" * 60)
        print(f"[SOLUTION] task_id={s.get('task_id')}  success={s.get('success')}  error={s.get('error')}")
        print("=" * 60)
        for step in s.get("steps", []):
            print(f"\n==================== Step {step['step']} ====================")
            print("[LLM Thought / Raw Output]")
            print(step.get("llm_output", ""))
            print("\n[Sandbox Input (Executed Code)]")
            print(step.get("sandbox_input", ""))
            print("\n[Observation (Returned to LLM)]")
            print(step.get("sandbox_output", ""))
        print("\n==================== Final Solution (Patch/Code) ====================")
        print(s.get("solution", ""))


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# MBPP の test split 全タスク（デフォルト全問、--limit N で件数指定可）を実行・採点するスクリプト
# 使い方:
#   ./test/exam/exam_mbpp_all.sh [--limit N] [--student-path ./My_AgentSmith] [--moulinette-path ../moulinette] [--env-file ./.env]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STUDENT_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"
MOULINETTE_PATH="$(cd "$STUDENT_PATH/../moulinette" 2>/dev/null && pwd || echo "")"
ENV_FILE="$STUDENT_PATH/.env"
MODEL_ARGS=""
LIMIT=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --student-path) STUDENT_PATH="$(cd "$2" && pwd)"; shift 2 ;;
        --moulinette-path) MOULINETTE_PATH="$(cd "$2" && pwd)"; shift 2 ;;
        --env-file) ENV_FILE="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
        --model-name) MODEL_ARGS="$MODEL_ARGS --model-name $2"; shift 2 ;;
        --provider-url) MODEL_ARGS="$MODEL_ARGS --provider-url $2"; shift 2 ;;
        --limit) LIMIT="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

[ -d "$STUDENT_PATH" ] || { echo "Error: student-path not found: $STUDENT_PATH" >&2; exit 1; }
[ -d "$MOULINETTE_PATH" ] || { echo "Error: moulinette-path not found: $MOULINETTE_PATH" >&2; exit 1; }
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
LOG_ROOT="$STUDENT_PATH/evaluations/mbpp_all/$TIMESTAMP"
mkdir -p "$LOG_ROOT"

TASK_IDS=$(uv run --project "$MOULINETTE_PATH" python -c "
from moulinette.mbpp import InteractMBPP
pool = InteractMBPP().list_tasks(split='test')
limit = int('$LIMIT')
for tid in (pool[:limit] if limit > 0 else pool):
    print(tid)
")

TOTAL=$(echo "$TASK_IDS" | wc -w)
TIME_LIMIT=120
PASSED=0
FAILED=0
FAILED_IDS=()
ERROR_LOG="$LOG_ROOT/failed_errors.log"
: > "$ERROR_LOG"

append_failure_report() {
    local tid="$1"
    local task_dir="$2"
    python3 - "$tid" "$task_dir" "$MOULINETTE_PATH" >> "$ERROR_LOG" <<'PYEOF'
import ast, json, os, re, sys
tid, td, moulinette_path = int(sys.argv[1]), sys.argv[2], sys.argv[3]
sanitized_path = os.path.join(moulinette_path, "moulinette/mbpp/data/sanitized_tasks.json")
all_tasks = {t["task_id"]: t for t in json.load(open(sanitized_path))} if os.path.exists(sanitized_path) else {}
raw_task = all_tasks.get(tid, {})
test_imports = raw_task.get("test_imports", [])
test_list = raw_task.get("test_list", [])

def extract_solution_str(sandbox_in):
    try:
        tree = ast.parse(sandbox_in)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "solution" and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    except Exception:
        pass
    return None

task_path = os.path.join(td, "task.json")
sol_path = os.path.join(td, "solution.json")
stdout_path = os.path.join(td, "stdout.log")
stderr_path = os.path.join(td, "stderr.log")
task_data = json.load(open(task_path)) if os.path.exists(task_path) else {}
sol_data = json.load(open(sol_path)) if os.path.exists(sol_path) else {}
public_tests = task_data.get("test_list", [])
stdout = open(stdout_path).read().strip() if os.path.exists(stdout_path) else ""
stderr = open(stderr_path).read().strip() if os.path.exists(stderr_path) else ""

succ = sol_data.get("success")
err_reason = sol_data.get("error")
sol_code_raw = sol_data.get("solution") or ""
code_lines = (sol_code_raw + "\n").splitlines() if sol_code_raw else [""]
imp_lines = ("\n".join(test_imports) + "\n").splitlines() if test_imports else []
first_test_line = len(code_lines) + len(imp_lines) + 1
m = re.search(r'File "<string>", line (\d+), in <module>', stdout)
failed_line = int(m.group(1)) if m else None
failed_test_idx = (failed_line - first_test_line) if (succ and failed_line is not None and first_test_line <= failed_line < first_test_line + len(test_list)) else None

if not succ:
    fail_reason = f"FAILED PUBLIC TESTS / BUDGET EXHAUSTED (error={err_reason}, final_answer never called)"
elif failed_test_idx == 0:
    fail_reason = "FAILED ON HIDDEN TEST (passed all public tests, failed test_list[0])"
elif failed_test_idx is not None:
    fail_reason = f"FAILED ON PUBLIC TEST (test_list[{failed_test_idx}])"
else:
    fail_reason = "FAILED (Runtime or metrics error)"

print("=" * 70)
print(f"Task ID: {tid}  -->  {fail_reason}")
print(f"Definition: {task_data.get('task_definition', '').strip()}")
print(f"Signature:  {task_data.get('function_definition', '').strip()}")
if test_imports:
    print("Test Imports:")
    for idx, imp in enumerate(test_imports):
        tag = "[HIDDEN]" if idx == 0 else "[PUBLIC]"
        print(f"  {tag} {imp}")
print("Test List:")
for idx, t_stmt in enumerate(test_list):
    tag = "[HIDDEN]" if idx == 0 else "[PUBLIC]"
    if succ:
        line_no = first_test_line + idx
        marker = "  <-- FAILED HERE" if failed_test_idx == idx else ""
        print(f"  {tag} (validate line {line_no:2d}) {t_stmt}{marker}")
    else:
        print(f"  {tag} {t_stmt}")
print(f"Claimed Success: {succ} | Error: {err_reason} | Iterations: {sol_data.get('iterations')} | Tokens: {sol_data.get('total_input_tokens')} in / {sol_data.get('total_output_tokens')} out")

if succ:
    print("--- Executed Script in validate (with exact line numbers) ---")
    cur = 1
    for cl in code_lines:
        tag = "<-- (blank line because solution ended with \\n)" if (cur == len(code_lines) and cl == "") else ""
        print(f"  {cur:2d}: {cl} {tag}".rstrip())
        cur += 1
    for il in imp_lines:
        print(f"  {cur:2d}: {il}  # [IMPORT]")
        cur += 1
    for idx, tl in enumerate(test_list):
        tag = "[HIDDEN]" if idx == 0 else "[PUBLIC]"
        marker = "  <-- FAILED HERE" if cur == failed_line else ""
        print(f"  {cur:2d}: {tl}  # {tag}{marker}")
        cur += 1
else:
    print("--- Solution ---")
    steps = sol_data.get("steps") or []
    if steps:
        last = steps[-1]
        st_num = last.get("step")
        st_mod = last.get("model_name")
        st_in = last.get("sandbox_input", "").strip()
        st_out = last.get("sandbox_output", "").strip()
        print(f"(empty — final_answer was never called because public tests failed in all {len(steps)} steps)")
        cand = extract_solution_str(st_in)
        if cand is not None:
            test_run_script = f"{cand}\n" + "\n".join(public_tests)
            m_tr = re.search(r'test_run\.py", line (\d+)', st_out)
            tr_fail_line = int(m_tr.group(1)) if m_tr else None
            print(f"--- Step {st_num} ({st_mod}) Executed test_run.py (with exact line numbers) ---")
            for idx, tr_line in enumerate(test_run_script.splitlines(), 1):
                marker = "  <-- FAILED HERE" if idx == tr_fail_line else ("  <-- (blank line from trailing \\n in solution)" if tr_line == "" else "")
                print(f"  {idx:2d}: {tr_line}{marker}")
        else:
            print(f"--- Last Attempt in Step {st_num} ({st_mod}) ---")
            for idx, sl in enumerate(st_in.splitlines(), 1):
                print(f"  {idx:2d}: {sl}")
        print("--- Last Step Sandbox Output ---")
        print(st_out)
    else:
        print("(empty)")

print("--- Validation / Error Output ---")
print(stdout)
if stderr:
    print("--- Stderr ---")
    print(stderr)
print("")
PYEOF
}

echo "=========================================="
echo " EXAM MBPP ALL ($TOTAL tasks from test split)"
echo " Logs: $LOG_ROOT"
echo " Error summary: $ERROR_LOG"
echo "=========================================="

i=0
for tid in $TASK_IDS; do
    i=$((i + 1))
    TASK_DIR="$LOG_ROOT/$tid"
    mkdir -p "$TASK_DIR"
    TASK_FILE="$TASK_DIR/task.json"
    SOL_FILE="$TASK_DIR/solution.json"

    echo ""
    echo ">>> [$i/$TOTAL] Task ID: $tid"

    # 1. dump task
    uv run --project "$MOULINETTE_PATH" moulinette_eval dump mbpp --task-id "$tid" --output "$TASK_FILE" >/dev/null

    # 2. run agent
    AGENT_CMD="uv run python -m agent_mbpp --task-file $TASK_FILE --output $SOL_FILE $MODEL_ARGS"
    (
        cd "$STUDENT_PATH" && \
        uv run --project "$MOULINETTE_PATH" moulinette_eval run-agent "$TIME_LIMIT" "$AGENT_CMD"
    ) >"$TASK_DIR/stdout.log" 2>"$TASK_DIR/stderr.log"
    RUN_RC=$?

    # 3. validate
    if [ $RUN_RC -eq 0 ] && [ -f "$SOL_FILE" ]; then
        if uv run --project "$MOULINETTE_PATH" moulinette_eval validate mbpp "$TASK_FILE" "$SOL_FILE" >>"$TASK_DIR/stdout.log" 2>>"$TASK_DIR/stderr.log"; then
            echo "    Result: PASSED ($((PASSED + 1))/$i)"
            PASSED=$((PASSED + 1))
        else
            echo "    Result: FAILED (validation failed — see $TASK_DIR/stdout.log)"
            FAILED=$((FAILED + 1))
            FAILED_IDS+=("$tid")
            append_failure_report "$tid" "$TASK_DIR"
        fi
    else
        echo "    Result: FAILED (agent exit code $RUN_RC — see $TASK_DIR/stderr.log)"
        FAILED=$((FAILED + 1))
        FAILED_IDS+=("$tid")
        append_failure_report "$tid" "$TASK_DIR"
    fi
done

echo ""
echo "=========================================="
echo " MBPP ALL Summary: $PASSED / $TOTAL passed ($FAILED failed)"
if [ ${#FAILED_IDS[@]} -gt 0 ]; then
    echo " Failed Task IDs: ${FAILED_IDS[*]}"
    echo " Consolidated Error Log: $ERROR_LOG"
fi
echo "=========================================="
[ "$FAILED" -eq 0 ]

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
    python3 - "$tid" "$task_dir" >> "$ERROR_LOG" <<'PYEOF'
import json, os, sys
tid, td = sys.argv[1], sys.argv[2]
task_path = os.path.join(td, "task.json")
sol_path = os.path.join(td, "solution.json")
stdout_path = os.path.join(td, "stdout.log")
stderr_path = os.path.join(td, "stderr.log")
task_data = json.load(open(task_path)) if os.path.exists(task_path) else {}
sol_data = json.load(open(sol_path)) if os.path.exists(sol_path) else {}
stdout = open(stdout_path).read().strip() if os.path.exists(stdout_path) else ""
stderr = open(stderr_path).read().strip() if os.path.exists(stderr_path) else ""
print("=" * 70)
print(f"Task ID: {tid}")
print(f"Definition: {task_data.get('task_definition', '').strip()}")
print(f"Signature:  {task_data.get('function_definition', '').strip()}")
print(f"Claimed Success: {sol_data.get('success')} | Iterations: {sol_data.get('iterations')} | Tokens: {sol_data.get('total_input_tokens')} in / {sol_data.get('total_output_tokens')} out")
print("--- Solution ---")
print((sol_data.get("solution") or "(empty)").strip())
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

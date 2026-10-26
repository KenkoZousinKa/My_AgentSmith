#!/usr/bin/env bash
# 課題 PDF Chapter VI Table VI.1 / VI.5 に基づく exam_swebench.sh の模擬スクリプト
# 使い方:
#   ./test/exam/exam_swebench.sh [--student-path ./My_AgentSmith] [--moulinette-path ../moulinette] [--env-file ./.env]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STUDENT_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"
MOULINETTE_PATH="$(cd "$STUDENT_PATH/../moulinette" 2>/dev/null && pwd || echo "")"
ENV_FILE="$STUDENT_PATH/.env"
MODEL_ARGS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --student-path) STUDENT_PATH="$(cd "$2" && pwd)"; shift 2 ;;
        --moulinette-path) MOULINETTE_PATH="$(cd "$2" && pwd)"; shift 2 ;;
        --env-file) ENV_FILE="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
        --model-name) MODEL_ARGS="$MODEL_ARGS --model-name $2"; shift 2 ;;
        --provider-url) MODEL_ARGS="$MODEL_ARGS --provider-url $2"; shift 2 ;;
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
LOG_ROOT="$STUDENT_PATH/evaluations/swebench/$TIMESTAMP"
mkdir -p "$LOG_ROOT"

TOTAL=3
REQUIRED=2
TIME_LIMIT=900
PASSED=0

echo "=========================================="
echo " EXAM SWE-BENCH (3 random tasks, Pass: 2/3)"
echo " Logs: $LOG_ROOT"
echo "=========================================="

# moulinette_eval select で EXAM_POOL からランダムに3問選ぶ
TASK_IDS=$(uv run --project "$MOULINETTE_PATH" moulinette_eval select --count "$TOTAL" 2>/dev/null | python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
for tid in data['instance_ids']:
    print(tid)
")

i=0
for tid in $TASK_IDS; do
    i=$((i + 1))
    TASK_DIR="$LOG_ROOT/$tid"
    mkdir -p "$TASK_DIR"
    TASK_FILE="$TASK_DIR/task.json"
    SOL_FILE="$TASK_DIR/solution.json"

    echo ""
    echo ">>> [$i/$TOTAL] Instance ID: $tid"

    CONTAINERS_BEFORE=$(docker ps -q | wc -l)

    # 1. dump task
    uv run --project "$MOULINETTE_PATH" moulinette_eval dump swebench --task-id "$tid" --output "$TASK_FILE" >/dev/null 2>&1

    # 2. run agent
    AGENT_CMD="uv run python -m agent_swebench --task-file $TASK_FILE --output $SOL_FILE $MODEL_ARGS"
    (
        cd "$STUDENT_PATH" && \
        uv run --project "$MOULINETTE_PATH" moulinette_eval run-agent "$TIME_LIMIT" "$AGENT_CMD"
    ) >"$TASK_DIR/stdout.log" 2>"$TASK_DIR/stderr.log"
    RUN_RC=$?

    # 4. container cleanup 確認（エージェントが起動したコンテナが残っていないか）
    LEAKED=$(docker ps --filter "label=agentsmith=1" -q)
    CONTAINERS_AFTER=$(docker ps -q | wc -l)
    CLEANUP_OK=1
    if [ -n "$LEAKED" ] || [ "$CONTAINERS_AFTER" -gt "$CONTAINERS_BEFORE" ]; then
        echo "    [FAIL] Container cleanup check failed! Leaked container(s) detected."
        CLEANUP_OK=0
        [ -n "$LEAKED" ] && docker rm -f $LEAKED >/dev/null 2>&1 || true
    else
        echo "    [OK] Container cleanup verified."
    fi

    # 3. validate
    if [ $RUN_RC -eq 0 ] && [ -f "$SOL_FILE" ] && [ $CLEANUP_OK -eq 1 ]; then
        if uv run --project "$MOULINETTE_PATH" moulinette_eval validate swebench "$TASK_FILE" "$SOL_FILE" >>"$TASK_DIR/stdout.log" 2>>"$TASK_DIR/stderr.log"; then
            echo "    Result: PASSED"
            PASSED=$((PASSED + 1))
        else
            echo "    Result: FAILED (validation failed — see $TASK_DIR/stdout.log)"
        fi
    else
        echo "    Result: FAILED (run_rc=$RUN_RC, cleanup_ok=$CLEANUP_OK — see $TASK_DIR/stderr.log)"
    fi
done

echo ""
echo "=========================================="
echo " SWE-bench Summary: $PASSED / $TOTAL passed (required: $REQUIRED)"
echo "=========================================="
[ "$PASSED" -ge "$REQUIRED" ]

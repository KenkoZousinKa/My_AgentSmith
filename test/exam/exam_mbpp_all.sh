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

echo "=========================================="
echo " EXAM MBPP ALL ($TOTAL tasks from test split)"
echo " Logs: $LOG_ROOT"
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
        fi
    else
        echo "    Result: FAILED (agent exit code $RUN_RC — see $TASK_DIR/stderr.log)"
        FAILED=$((FAILED + 1))
        FAILED_IDS+=("$tid")
    fi
done

echo ""
echo "=========================================="
echo " MBPP ALL Summary: $PASSED / $TOTAL passed ($FAILED failed)"
if [ ${#FAILED_IDS[@]} -gt 0 ]; then
    echo " Failed Task IDs: ${FAILED_IDS[*]}"
fi
echo "=========================================="
[ "$FAILED" -eq 0 ]

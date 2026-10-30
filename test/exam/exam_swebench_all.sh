#!/usr/bin/env bash
# SWE-bench の EXAM_POOL 全6タスクを順番にすべて実行・採点するスクリプト
# 使い方:
#   ./test/exam/exam_swebench_all.sh [--student-path ./My_AgentSmith] [--moulinette-path ../moulinette] [--env-file ./.env]
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
LOG_ROOT="$STUDENT_PATH/evaluations/swebench_all/$TIMESTAMP"
mkdir -p "$LOG_ROOT"

# EXAM_POOL の全タスクを取得
TASK_IDS=$(uv run --project "$MOULINETTE_PATH" python -c "
from moulinette.swebench import EXAM_POOL
for tid in EXAM_POOL:
    print(tid)
")

TOTAL=$(echo "$TASK_IDS" | wc -w)
TIME_LIMIT=900
PASSED=0
FAILED=0
FAILED_IDS=()

echo "=========================================="
echo " EXAM SWE-BENCH ALL ($TOTAL tasks in EXAM_POOL)"
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

    # 4. container cleanup 確認
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
            echo "    Result: PASSED ($((PASSED + 1))/$i)"
            PASSED=$((PASSED + 1))
        else
            echo "    Result: FAILED (validation failed — see $TASK_DIR/stdout.log)"
            FAILED=$((FAILED + 1))
            FAILED_IDS+=("$tid")
        fi
    else
        echo "    Result: FAILED (run_rc=$RUN_RC, cleanup_ok=$CLEANUP_OK — see $TASK_DIR/stderr.log)"
        FAILED=$((FAILED + 1))
        FAILED_IDS+=("$tid")
    fi
done

echo ""
echo "=========================================="
echo " SWE-bench ALL Summary: $PASSED / $TOTAL passed ($FAILED failed)"
if [ ${#FAILED_IDS[@]} -gt 0 ]; then
    echo " Failed Instance IDs: ${FAILED_IDS[*]}"
fi
echo "=========================================="
[ "$FAILED" -eq 0 ]

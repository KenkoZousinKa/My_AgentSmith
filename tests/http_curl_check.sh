#!/usr/bin/env bash
# 自作 MCP サーバー（Streamable HTTP）を curl と nc で確かめる。
#
# 使い方:
#   uv run python mcp_tools_mbpp.py --transport http      # 別の端末でサーバーを起動しておく
#   ./tests/http_curl_check.sh [ポート] [--slow]             # --slow でタイムアウトの確認も行う（数秒かかる）
#   ./tests/http_curl_check.sh              # ポート 8000 で確認
#   ./tests/http_curl_check.sh 9000         # ポートを指定
#   ./tests/http_curl_check.sh --slow       # タイムアウトの確認も行う（数秒かかる）
set -u

PORT=8000
SLOW=0
for arg in "$@"; do
    case "$arg" in
        --slow) SLOW=1 ;;
        *) PORT="$arg" ;;
    esac
done
U="http://127.0.0.1:$PORT/mcp"
VERSION="2025-06-18"
PASS=0
FAIL=0

# 結果を判定して表示する。$1=期待する値 $2=実際の値 $3=何を確かめるか [$4=本文 $5=本文に含まれるべき文字列]
# 値の列を先に置いて幅をそろえる（日本語は幅の計算がずれるので、説明は最後に置く）
check() {
    local expected=$1 actual=$2 what=$3 body=${4:-} needle=${5:-}
    if [ "$actual" = "$expected" ] && { [ -z "$needle" ] || [[ "$body" == *"$needle"* ]]; }; then
        printf '  \033[32mPASS\033[0m  %-6s  %s\n' "$actual" "$what"
        PASS=$((PASS + 1))
    else
        printf '  \033[31mFAIL\033[0m  %-6s  %s（期待: %s%s）\n' "$actual" "$what" "$expected" "${needle:+、本文に $needle}"
        [ -n "$body" ] && printf '                本文: %s\n' "${body:0:200}"
        FAIL=$((FAIL + 1))
    fi
}

# curl を実行し、「本文」と「ステータス」を変数 BODY と CODE に入れる
req() {
    local out
    out=$(curl -s --max-time 15 -w $'\n%{http_code}' "$@")
    CODE=${out##*$'\n'}
    BODY=${out%$'\n'*}
}

# セッション ID とバージョンを付けて POST する
mcp() {
    req "$U" -H 'Content-Type: application/json' \
        -H "Mcp-Session-Id: $SID" -H "MCP-Protocol-Version: $VERSION" "$@"
}

# nc で生のバイト列を送り、返事の1行目からステータスを取り出す
raw() {
    CODE=$(printf "$1" | nc -q "${2:-2}" 127.0.0.1 "$PORT" | head -n 1 | awk '{print $2}')
    CODE=${CODE:-none}
}

ping_alive() {
    mcp -d '{"jsonrpc":"2.0","id":99,"method":"ping"}'
    check 200 "$CODE" "$1" "$BODY" '"result"'
}

if ! curl -s -o /dev/null --max-time 2 "$U"; then
    echo "サーバーにつながりません: $U（先に起動してください）"
    exit 1
fi

echo "        結果    確かめること"

echo "== 0. 初期化"
SID=$(curl -si "$U" -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}' \
    | grep -i '^mcp-session-id' | cut -d' ' -f2 | tr -d '\r')
check 32 "${#SID}" "initialize の返事に 32 文字のセッション ID が付く"
mcp -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
check 202 "$CODE" "initialized の通知を、本文なしで受け付ける"

echo "== 1. 普通のやり取り"
mcp -d '{"jsonrpc":"2.0","id":2,"method":"ping"}'
check 200 "$CODE" "ping に空の result が返る" "$BODY" '"result":{}'
mcp -d '{broken'
check 400 "$CODE" "壊れた JSON に解析エラー（-32700）が返る" "$BODY" '-32700'
check 400 "$CODE" "解析エラーの id が null になる" "$BODY" '"id":null'
CODE=$( ( printf 'POST /mcp HTTP/1.1\r\nHost: x\r\nMcp-Session-Id: %s\r\n' "$SID"; sleep 1
          printf 'Content-Length: 40\r\n\r\n{"jsonrpc":"2.0",'; sleep 1
          printf '"id":3,"method":"ping"}' ) | nc -q 3 127.0.0.1 "$PORT" | head -n 1 | awk '{print $2}')
check 200 "${CODE:-none}" "3 回に分けて届いても、読み足して処理する"

echo "== 2. HTTP の形（_read_request）"
raw 'POST /mcp HTTP/1.1\r\nContent-Length: abc\r\n\r\n'
check 400 "$CODE" "Content-Length が数字でなければ断る"
raw 'POST /mcp HTTP/1.1\r\nContent-Length: -5\r\n\r\n'
check 400 "$CODE" "Content-Length が負なら断る"
raw 'POST /mcp HTTP/1.1\r\nBrokenHeader\r\n\r\n'
check 400 "$CODE" "コロンの無いヘッダー行を断る"
raw 'POST /mcp HTTP/1.0\r\nContent-Length: 0\r\n\r\n'
check 505 "$CODE" "HTTP/1.1 以外を断る"
req "$U" -H 'Content-Length: 2000000' -d '{}'
check 413 "$CODE" "本文の上限（1MB）を超える長さを、読む前に断る"
req "$U" -H "X-Junk: $(head -c 9000 /dev/zero | tr '\0' 'a')" -d '{}'
check 431 "$CODE" "ヘッダーの上限（8KB）を超えたら断る"
printf 'POST /mcp HTTP/1.1\r\nHo' | nc -q 0 127.0.0.1 "$PORT" > /dev/null
ping_alive "ヘッダーの途中で切断されても、サーバーは落ちない"

echo "== 3. Streamable HTTP の決まり（_route）"
req "http://127.0.0.1:$PORT/other" -d '{}'
check 404 "$CODE" "/mcp 以外のパスを断る"
mcp -H 'Origin: http://evil.example.com' -d '{"jsonrpc":"2.0","id":11,"method":"ping"}'
check 403 "$CODE" "外部サイトの Origin を断る"
mcp -H 'Origin: http://localhost:3000' -d '{"jsonrpc":"2.0","id":12,"method":"ping"}'
check 200 "$CODE" "localhost の Origin は受け付ける"
req "$U"
check 405 "$CODE" "POST 以外（GET）を断る"
ALLOW=$(curl -si "$U" | grep -i '^allow:' | cut -d' ' -f2 | tr -d '\r')
check POST "$ALLOW" "405 の返事に Allow ヘッダーが付く"
req "$U" -X POST
check 411 "$CODE" "Content-Length の無い POST を断る"
mcp -H 'Transfer-Encoding: chunked' -d '{"jsonrpc":"2.0","id":13,"method":"ping"}'
check 411 "$CODE" "チャンク転送の POST を断る"
req "$U" -d '{"jsonrpc":"2.0","id":14,"method":"ping"}'
check 400 "$CODE" "セッション ID の無いリクエストを断る"
req "$U" -H 'Mcp-Session-Id: unknown' -d '{"jsonrpc":"2.0","id":15,"method":"ping"}'
check 404 "$CODE" "発行していないセッション ID を断る"
req "$U" -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 1999-01-01' -d '{"jsonrpc":"2.0","id":16,"method":"ping"}'
check 400 "$CODE" "未対応のプロトコルバージョンを断る"
req "$U" -H "Mcp-Session-Id: $SID" -d '{"jsonrpc":"2.0","id":17,"method":"ping"}'
check 200 "$CODE" "バージョンのヘッダーが無ければ受け付ける"
ping_alive "ここまでの確認の後も、サーバーは落ちていない"

echo "== 4. tool を HTTP で呼ぶ"
mcp -d '{"jsonrpc":"2.0","id":20,"method":"tools/list"}'
check 200 "$CODE" "tools/list に run_tests が含まれる" "$BODY" '"run_tests"'
mcp -d '{"jsonrpc":"2.0","id":21,"method":"tools/call","params":{"name":"run_tests","arguments":{"code":"def add(a, b):\n    return a + b","test_list":["assert add(1, 2) == 3"]}}}'
check 200 "$CODE" "正しいコードで run_tests が success: true" "$BODY" '\"success\": true'
mcp -d '{"jsonrpc":"2.0","id":22,"method":"tools/call","params":{"name":"run_tests","arguments":{"code":"def add(a, b):\n    return a - b","test_list":["assert add(1, 2) == 3"]}}}'
check 200 "$CODE" "間違ったコードで run_tests が success: false" "$BODY" '\"success\": false'
mcp -d '{"jsonrpc":"2.0","id":23,"method":"tools/call","params":{"name":"nope","arguments":{}}}'
check 200 "$CODE" "存在しない tool は 200 のまま JSON-RPC エラー（-32602）" "$BODY" '-32602'

if [ "$SLOW" = 1 ]; then
    echo "== 5. 何も送らない相手（--slow）"
    (sleep 30 | nc 127.0.0.1 "$PORT" > /dev/null) &
    SILENT=$!
    sleep 0.5
    START=$(date +%s)
    mcp -d '{"jsonrpc":"2.0","id":30,"method":"ping"}'
    ELAPSED=$(( $(date +%s) - START ))
    check 200 "$CODE" "黙っている相手をタイムアウトで切り、次に応じる（${ELAPSED} 秒待った）"
    kill "$SILENT" 2>/dev/null
fi

echo
echo "合計: PASS $PASS / FAIL $FAIL"
[ "$FAIL" = 0 ]

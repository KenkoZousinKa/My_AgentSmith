*This project has been created as part of the 42 curriculum by ayhirose, nsato, joseo.*

<table>
	<thead>
    	<tr>
      		<th style="text-align:center"><a href="README.md">英語</a></th>
      		<th style="text-align:center">日本語</th>
    	</tr>
  	</thead>
</table>

<h1>
	AgentSmith
</h1>
<H2>
	MBPP と SWE-bench を解く、自作の LLM コーディングエージェント
</H2>


## 📖*目次*
1. [💡概要](#1-概要)
2. [📁ファイル構成](#2-ファイル構成)
3. [✅手順](#3-手順)
4. [⛏追加要件](#4-追加要件)
5. [📃入出力例](#5-入出力例)
6. [🎁ボーナス](#6-ボーナス)
7. [🌈リソース](#7-リソース)
	1. [参考URL](#7-1-参考URL)
	2. [AIの使用について](#7-2-AIの使用について)


## 💡1. 概要

AgentSmith は、プログラミングの課題を自分で考え、コードを書き、実行して確かめ、直すことをくり返す LLM エージェントです。
次の2つのベンチマークに対応しています。

- **MBPP**：短い問題文から Python の関数を書く
- **SWE-bench**：実際の OSS リポジトリの issue を、パッチ（`git diff`）で直す

システムは、3つの部品でできています。

| 部品 | 役割 | 担当 |
|---|---|---|
| Agent | LLM の呼び出し、思考と行動のループ、答えの取り出し | nsato（要確認） |
| Sandbox | LLM が書いたコードを、隔離した環境で実行する | joseo（要確認） |
| MCP | ツールを提供するサーバーと、それを呼ぶクライアント | ayhirose |

<!-- TODO: 全体の構成図（Agent → Sandbox → MCPClient → MCP サーバー → Docker）を入れる -->


## 📁2. ファイル構成

```
.
├── agent_mbpp.py          # MBPP のエントリーポイント
├── agent_swebench.py      # SWE-bench のエントリーポイント
├── mcp_tools_mbpp.py      # MBPP 用の MCP サーバー
├── mcp_tools_swebench.py  # SWE-bench 用の MCP サーバー
├── providers/             # LLM プロバイダーとモデルの設定
├── src/
│   ├── agent/             # エージェント（LLM、プロンプト、抽出、オーケストレーター）
│   ├── sandbox/           # サンドボックス
│   ├── mcp/               # 自作の MCP（models / server / client）
│   │   └── swe_bench/     # SWE-bench 用の Executor（ローカル / Docker）
│   ├── config/            # 設定の読み込み
│   └── models/            # 入出力のモデル
└── test/                  # テスト（MCP は test/mcp/）
```


## ✅3. 手順

### 3-1. 必要なもの
- Python 3.10
- [uv](https://docs.astral.sh/uv/)（`make uv-install` でもインストールできます）
- Docker（SWE-bench の実行と、moulinette での評価に必要）
- LLM の API キー（OpenRouter または Groq）
- 課題で配布される moulinette（`moulinette.zip`）

### 3-2. フォルダの配置
課題で配布される moulinette（評価ツール）を、このリポジトリと同じ階層に置きます。
タスクと解答の JSON は、同じ階層の `cache/` に書き出されます。

```
<作業フォルダ>/
├── moulinette/      # 配布された moulinette.zip を展開したもの
├── AgentSmith/   # このリポジトリ
└── cache/           # task.json と solution.json（moulinette が作る）
```

### 3-3. セットアップ
```bash
# エージェント
cd AgentSmith
make install          # 仮想環境の作成と依存関係のインストール
cp .env.example .env  # OPENROUTER_API_KEY / GROQ_API_KEY を記入する

# moulinette
cd ../moulinette
uv sync
```

### 3-4. moulinette で評価する
moulinette の `quickstart.sh` を使うと、次の3つを1回のコマンドで実行できます。

1. タスクの取得（dump）
2. 制限時間つきでのエージェントの実行（run-agent）
3. 解答の評価（validate）

```bash
cd moulinette

# MBPP（制限時間 120秒）
./quickstart.sh mbpp --student-path ../AgentSmith \
  --model-name "model/name" --provider-url "https://provider.api/v1"

# SWE-bench（制限時間 900秒）
./quickstart.sh swebench --student-path ../AgentSmith \
  --model-name "model/name" --provider-url "https://provider.api/v1"
```
- `--task-id` で問題を指定できます（例：`--task-id 42`、`--task-id sympy__sympy-23534`）。
- `--seed` で、ランダムに選ばれる問題を固定できます。
- `--cache-dir` で、JSON の書き出し先を変えられます（既定は `../cache`）。
- オプションの一覧は `./quickstart.sh --help` で確認できます。

### 3-5. Moulinette マニュアル実行
`quickstart.sh` を1段階ずつ実行する。

```bash
cd moulinette

# 1. タスクを取得する
uv run moulinette_eval dump mbpp --output ../cache/mbpp_task.json
uv run moulinette_eval dump swebench --task-id sympy__sympy-23534 --output ../cache/swebench_task.json

# 2. 制限時間つきでエージェントを実行する
uv run moulinette_eval run-agent 120 \
  "cd ../AgentSmith && uv run python -m agent_mbpp --task-file ../cache/mbpp_task.json --output ../cache/mbpp_solution.json"

# 3. 解答を評価する
uv run moulinette_eval validate mbpp ../cache/mbpp_task.json ../cache/mbpp_solution.json
uv run moulinette_eval validate mbpp ../cache/mbpp_task.json ../cache/mbpp_solution.json --skip-metrics
uv run moulinette_eval validate_metrics mbpp ../cache/mbpp_solution.json

# 4. 解答の中身を見る
uv run moulinette_eval display ../cache/mbpp_solution.json --full
```
- `moulinette_eval` を引数なしで実行すると、コマンドの一覧が表示されます。

<!-- TODO：2. の run-agent のコマンドは、quickstart.sh の実際の実行場所に合わせて確認する -->

### 3-6. moulinette を使わずに実行する
すでに task.json がある場合は、エージェントを直接実行できます。

```bash
cd AgentSmith

# MBPP
uv run python3 -m agent_mbpp \
  --task-file ../cache/mbpp_task.json \
  --output ../cache/mbpp_solution.json \
  --model-name "model/name" --provider-url "http://provider.api/v1"

# SWE-bench
uv run python3 -m agent_swebench \
  --task-file ../cache/swebench_task.json \
  --output ../cache/swebench_solution.json \
  --model-name "model/name" --provider-url "http://provider.api/v1"
```
`--model-name` と `--provider-url` を省略すると、`providers/providers.json` の既定値を使います。

<!-- TODO: Makefile の run を直したら、make run の使い方に合わせる -->

### 3-7. 評価の基準
moulinette は、解答が正しいかに加えて、次の制限を守っているかも確認します。

| 指標 | MBPP | SWE-bench |
|---|---|---|
| ループの最大回数 | 10 | 30 |
| 入力トークンの上限 | 6,000 | 300,000 |
| 出力トークンの上限 | 1,500 | 10,000 |
| 制限時間 | 120秒 | 900秒 |
| 合格の基準 | ランダムな5問のうち4問 | ランダムな3問のうち2問 |

### 3-8. Makefile のターゲット
| ターゲット | 内容 |
|---|---|
| `install` | 仮想環境の作成と依存関係のインストール |
| `run` / `debug` | 実行 / pdb でのデバッグ実行 |
| `lint` / `lint-strict` | flake8・mypy による静的解析 / より厳しい解析 |
| `test` / `lint-test` | pytest の実行 / テストの静的解析 |
| `clean` / `fclean` / `re` | キャッシュの削除 / 仮想環境も削除 / 作り直し |


## ⛏4. 追加要件

### 4-1. Agent
<!-- TODO（Agent 担当）：ループの設計、プロンプト、答えの取り出し形式、リトライ、制限、ログ -->

### 4-2. Sandbox
<!-- TODO（Sandbox 担当）：隔離の方法、制限（メモリ・時間・ネットワーク）、REPL、MCP ツールの公開方法 -->

To isolate the sandbox is done in a newly made namespace. This namespace has only allowed imports and builtins that is set in the config.

To ensure resource limits and time limits it is done in two processes.
	The parent process manages the tool calls and memory while the child does the actual running of code.

	Time limits and memory limits are paused during tool calls and to ensure that the timing errors only happen during sandbox process.

	Network access is removed by blocking all socket functions. This is to ensure that the network is never accessed during the sandbox code, even if the AI requests it.
	The name-space sets the socket calls to all raise errors.

Final_answer:
	A baseException so that it is not eaten up by the LLM loop exception.
	It is a callable function for the LLM to call when it thinks its code does what is asked correctly.

Manual:
	A single use function to call to send information to the AI about the MCP tools and final answer usage.

```bash
# test repl of sandbox
uv run python -m src.sandbox.sandbox_main (config)

# test with MCP server/stdio
uv run python -m src.sandbox.sandbox_main (config) --mcp-stdio or --mcp-server (server/stdio)

# 1 test of code
uv run python -m src.sandbox.sandbox_main (config) -c "code"
```

### 4-3. MCP

MCP の仕様（JSON-RPC 2.0）に沿って、サーバーとクライアントの両方を標準ライブラリと pydantic で実装しました。
公式の `mcp` SDK は、相互に接続できるかを確かめるテストの相手として使っています。

- **models**：JSON-RPC と MCP のメッセージを pydantic のモデルで表す
- **server**：`@server.tool()`、`@server.resource(uri)`、`@server.prompt()` のデコレーターで登録する。`tools`、`resources`、`prompts` の各メソッドに対応
- **client**：`MCPClient(transport)` で接続し、`list_tools` / `call_tool` / `list_resources` / `read_resource` / `list_prompts` / `get_prompt` を呼ぶ

#### 2種類の通信方式（transport）
| | サーバー | クライアント |
|---|---|---|
| stdio | 標準入出力を1行ずつ読み書きする | サーバーを子プロセスとして起動する |
| Streamable HTTP | `socket` 上でのHTTP通信。1件ずつJSON で返答します。`Mcp-Session-Id`を割り当てる。  | `http.client` を使用してJSON と SSE を読み込む。既定の URL ではサーバーを自動で起動する。 |

#### MBPP 用サーバー（`mcp_tools_mbpp.py`）
- ツール `run_tests(code, test_list)`：コードとテストを実行し、結果を返す
- resource `mbpp://guide/run_tests`、prompt `solve_task`
- `--transport stdio|http`、`--port`（既定は 8000）

#### SWE-bench 用サーバー（`mcp_tools_swebench.py`）
- 課題で必須の9個のツールを提供：`read_file`、`edit_file`、`list_files`、`search_code`、`search_function_or_class_definition_in_code`、`find_references`、`run_tests`、`get_patch`、`run_command`
- **Docker管理**：initialize のときにコンテナを起動し、ツールは `docker exec` でコンテナの中で実行する
- **設定は initialize の `_meta["agentsmith/swebench"]` で受け取る**（Docker イメージ、eval_script）。
- `_meta` がない場合は、環境変数 `TESTBED_PATH` を使い、Docker なしでローカルのディレクトリに対して動く（moulinette のツール単体テスト用）
- **コンテナ廃棄**：SIGTERM を受けたとき、または標準入力が閉じたときにコンテナを止めて削除する。


## 📃5. 入出力例
<!-- TODO：MBPP と SWE-bench の task.json と solution.json の実例を1つずつ（`moulinette_eval display <solution.json> --full` の出力を使うと楽） -->


## 🎁6. ボーナス
<!-- TODO：実装した場合のみ -->


## 🌈7. リソース

### 7-1. 参考URL
- [Model Context Protocol 仕様](https://modelcontextprotocol.io/specification)
- [JSON-RPC 2.0 仕様](https://www.jsonrpc.org/specification)
- [MBPP](https://github.com/google-research/google-research/tree/master/mbpp)
- [SWE-bench](https://www.swebench.com/)
- [Docker ドキュメント](https://docs.docker.com/)
<!-- TODO：各担当が参考にしたものを追加 -->

### 7-2. AIの使用について
<!-- 各自が「どの作業で、どの部分に」使ったかを書く -->
- **ayhirose（MCP）**：MCP と HTTP・SSE の仕様の解説、設計の壁打ち、テストスクリプト（`test/mcp/`）の作成、コードのレビューに Claude を使用。SWE-bench のツールの一部は、生成させたコードを元に修正して取り込んだ。
- **nsato**：<!-- TODO -->
- **joseo**：<!-- TODO -->

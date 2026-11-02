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
Agentは、LLMに「考え（Thought）→ コード（Code）→ 実行結果（Observation）」をくり返させるループです（`src/agent/`）。  
MBPP と SWE-bench は同じループで動きます。2つの違いは、プロンプト・提出物の扱い・制限の値だけで、これをタスクごとの設定（`TaskProfile`）が持ちます。  

#### 全体の流れ
```mermaid
```
- Orchestrator はインターフェース（`LLMGenerator`・`CodeExtractor`・`SandboxBase`・`TaskProfile`）にだけ依存します。そのため、プロバイダ・取り出しの形式・サンドボックス・ベンチマークを、ループに手を入れずに差し替えられます。

#### 1回の反復
1. **上限の確認**：反復の回数、入力・出力トークンの合計、経過時間（＋余白：MBPP 10秒・SWE 60秒）のどれかを超えていれば終わる。
2. **送る履歴を決める**：Chat Completions は状態を持たないので、毎回、履歴を送り直します。送るのは次の3つだけです。
   - system プロンプト
   - タスク文
   - 直近 N 往復（1往復＝LLM の応答＋Observation。MBPP は N=2、SWE は 6）

   1件ずつ上限の文字数を超えた分は、**真ん中を省いて**縮めます（末尾の助言を残すため）。
   送る前に入力トークンを見積もり（文字数 ÷ 3.0。実測に合わせて小さいほうへ直す）、合計の上限に収まるまで N を減らします。system とタスク文だけでも収まらなければ、送らずに終わります。
3. **生成**：停止文字列は `<end_code>` です。1回の出力の上限は、`min(1回の上限, 出力の残り)` にします（1回の上限は MBPP 600・SWE 1,200）。
4. **コードの取り出し**：```` ```python ```` のブロックのほか、XML・JSON（Hermes）・ReAct 形式のツール呼び出しも Python に直します。崩れた出力も、直して実行します。何を直したかは、`[MALFORMED_CODE]` で LLM に伝えます。直す対象は次のとおりです。
   - 閉じていないブロック、フェンスの無いコード
   - 余分なエスケープや、余分な閉じ括弧
   - `{"code": ...}` の形
   - 複数のブロック
5. **実行と Observation**：サンドボックスで実行し、結果を次の形にまとめます。
   - 状態のラベル（`[OK]`・`[EXCEPTION]`・`[TIMEOUT]`・`[TRUNCATED]`・`[NO_CODE]`）
   - stdout、最後の式の値、エラー、直し方の助言
   - 前と同じコードなら `[REPEATED]`、残りが少なければ `[BUDGET]` を付けます。
6. **提出の検査**：`final_answer(...)` が呼ばれたら、受け取る前に確かめます。通らなければ、理由を付けて差し戻します。
   - MBPP：次の3つを確かめます。
     - 関数のソースとして正しいか
     - 見えているテストに通るか（`run_tests` で実際に通す）
     - 見えているテストの答えを直書きしていないか
   - SWE-bench：git の diff になっているか（`final_answer(get_patch())`）
7. **停滞したら別のプロバイダへ**：同じモデルで進まないときは、直前に答えたプロバイダを後ろに回します（モデルが違うと、間違い方も違うため）。
   - MBPP：提出が受理されない反復が2回続いたとき
   - SWE：同じコードが2回続いたとき

提出しないまま止まったときも、手元の最善を提出します。MBPP は、エラーなく動いた最後の関数です。SWE は、そのときのコンテナの `get_patch()` です。

#### LLM の呼び出しと再試行（`ResilientLLMClient`）
- `providers/providers.json`（MBPP）・`providers_swebench.json`（SWE）の `priority` の順に、「プロバイダ → キー → モデル」の組を並べます。毎回、先頭から試します。
  - キーは `XXX_API_KEY`、`XXX_API_KEY_2`… の順に使います。
  - 推論を切るなどのモデルごとの設定は、`model_params` に書きます。
- 失敗の種類ごとの扱い：

| 失敗 | 扱い |
|---|---|
| 429（レート制限・枠切れ） | 待たずに次の組へ |
| 5xx・通信エラー | 1秒・2秒…（最大8秒）待って、同じ組で2回まで送り直す |
| 401/403・400・空の応答・読めない応答 | 次の組へ。その組は、そのタスクの間は最後に回す |

- 全部だめで、途中に 429 があったときは、待ち時間が残り時間に収まれば1回だけ待ってもう1周します。それでもだめなら `LLM_UNAVAILABLE` で終わります（落ちません）。
- HTTP のタイムアウトと待ち時間は、残り時間より短くします。採点側の SIGTERM より先に、自分で止めるためです。

#### 本番のプロバイダの並び（計測で決めたもの。詳しくは `BENCHMARK_REPORT.md`）
- MBPP: 試験の範囲の257問を全部回して、237/257（92.2%）でした。
  - 1番手は、枠が大きく速い codestral です。
  - 2番手は、難しい問題で正答率が一番高かった qwen3.8 です。
- SWE-bench: 試験の候補の6問 × 3周を1モデルだけで回して、gpt-oss:120b（low）が 18/18 でした（いちばん難しい sympy-14711 も 9/9）。
- 推論を強くする設定は、SWE の出力の上限（10,000）に当たりやすく、正答率も上がらなかったので、使っていません。
- `.env` には、ここに出てくる社のキー（`MISTRAL_API_KEY`・`GROQ_API_KEY`・`OLLAMA_API_KEY`・`GEMINI_API_KEY`・`KILO_API_KEY`・`NVIDIA_API_KEY`・`CLOUDFLARE_API_KEY`・`COHERE_API_KEY`）を入れます。キーの無い社は飛ばされます。

#### 制限とトークンの数え方
| 上限（`config.json`） | MBPP | SWE-bench |
|---|---|---|
| 反復 | 10 | 30 |
| 入力トークン（タスク全体の合計） | 6,000 | 300,000 |
| 出力トークン（合計。推論のトークンも含む） | 1,500 | 10,000 |
| 1回の出力の上限 | 600 | 1,200 |
| 制限時間 | 120秒 | 900秒 |

- トークンは、プロバイダが返す `usage` で数えます。隠れた推論のトークン（`total − prompt` が `completion` より大きい分）と、空の応答で使われた分も足します。
- 本文が空で、推論の文だけが返ったときは、推論の文を本文の代わりに使います。

#### 終わり方と記録
- どんな終わり方でも `solution.json` を書きます。
  - 想定外の例外のとき：`error="AGENT_CRASH: …"`
  - SIGTERM・Ctrl+C のとき：`error="INTERRUPTED: …"`
  - 制限で止まったとき：`MAX_ITERATIONS`・`MAX_INPUT_TOKENS`・`MAX_OUTPUT_TOKENS`・`TIME_LIMIT`
  - LLM が全滅したとき：`LLM_UNAVAILABLE`
- `solution.json` の `steps` には、反復ごとに次のものが残ります。
  - LLM の出力
  - 実行したコードと Observation
  - 入出力トークン、応答時間、モデル名、リトライの回数
- プロバイダの切り替えと失敗は、ロガー `agent.llm` で標準エラーに出ます。

### 4-2. Sandbox
<!-- TODO（Sandbox 担当）：隔離の方法、制限（メモリ・時間・ネットワーク）、REPL、MCP ツールの公開方法 -->

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
- Agent：
  - Yao et al., [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)（ICLR 2023）
  - Wang et al., [Executable Code Actions Elicit Better LLM Agents（CodeAct）](https://arxiv.org/abs/2402.01030)（ICML 2024）：ツールを JSON ではなくコードで呼ぶ考え方
  - Jimenez et al., [SWE-bench: Can Language Models Resolve Real-World GitHub Issues?](https://arxiv.org/abs/2310.06770)（ICLR 2024）
  - 各プロバイダの OpenAI 互換 Chat Completions API のドキュメント（Mistral・Groq・Ollama Cloud・Cohere・Google AI Studio・NVIDIA NIM・Kilo Code・Cloudflare Workers AI）
<!-- TODO：各担当が参考にしたものを追加 -->

### 7-2. AIの使用について
<!-- 各自が「どの作業で、どの部分に」使ったかを書く -->
- **ayhirose（MCP）**：MCP と HTTP・SSE の仕様の解説、設計の壁打ち、テストスクリプト（`test/mcp/`）の作成。SWE-bench のツールの一部は、生成させたコードを元に修正して取り込んだ。
- **nsato（Agent）**：Claude Codeを疑問点の相談相手・分析役として使った。  
  - **設計**：エージェントループ、プロバイダの切り替え、制限の扱いの壁打ち。どの案を採るかは自分（チーム）で決めた。
  - **実装**：コードの提案を1行ずつの解説付きで受けた。それを読んで理解し自分で打ち込みテストした。
  - **テストと計測**：単体テストの設計と計測用のスクリプトに使った。失敗した回の `solution.json` を読んで原因を探すのにも使った。
  - **ドキュメント**：この README の Agent の節と `BENCHMARK_REPORT.md` の下書きに使った。数字はすべて実際の計測から取っている。
- **joseo**：<!-- TODO -->

# Agent_SmithにおけるSWE-Benchのモデルベンチマークレポート

## 📖*目次*
0. [はじめに](#0-はじめに)
1. [セットアップ](#1-セットアップ)
2. [結果表](#2-結果表)
3. [プロバイダーの信頼性](#3-プロバイダー-の信頼性)
4. [中間指標](#4-中間指標)
5. [アブレーション研究](#5-アブレーション研究)
6. [結論](#6-結論)

## 0. **はじめに**
- **比べたもの**:
- 課題の要件では、SWE-benchを3問以上・5モデル以上・2社以上にまたがって比較することが求められています。  
- はじめに比較する問題は、課題PDFで最初に試す単純な問題として挙げている`sympy__sympy-14711`、`sympy__sympy-13480`、`pydata__xarray-4629`の3問を選択しました。  
- モデル、プロバイダは6社・11モデル・16設定で比較しました。同じモデルの推論 ON／OFF は、別の設定として数えています。  
- 1つの設定につき1モデルだけで回しました(他のモデル、プロバイダへのバックオフ、フォールバックなし)。  
- 時間やトークンの制限は実際の制限と同じです。  

- **3問とも PASS したのは7設定**です。そのうち以下の4つは自分から`final_answer`で提出して通しました。
    - Mistral codestral  
    - NVIDIA glm-5.3-flash  
    - Ollama gpt-oss:120b(推論 low)  
    - Cohere command-a。  
- 残りの3つは反復の上限(30回)で止まった時に、それまで生成した解凍から回収したパッチで1問通っています。  

- **推論を強くしても、点は上がりませんでした**（§5.1）。
  - gpt-oss:120b は、推論 medium で出力の上限（10,000）を使い切りました。  
  - nemotron-3-ultra は、推論 medium で反復が16回から27回に増えました。  

- **本番の並び**
    **Ollama gpt-oss:120b（推論 low）を1番手**にします。
  - 試験の候補の6問 × 3周を、1モデルだけで回して **18/18** でした。
  - いちばん差の出た 14711 は 9/9 でした。
  - 2番手は NVIDIA glm-5.3-flash（17/18。落ちた1回は NVIDIA の通信エラー）です。
  - 今の1番手の cohere command-a と、案にしていた codestral は、14711 と scikit-learn で落ちる回がありました。

- **使わないもの**:
  - Cohere の command-a-plus と command-a-reasoning（推論 ON）。毎回 HTTP 422 でした。
  - Gemini 3.5-flash。1日の枠が小さすぎました。
  - Groq。1分あたり 8,000 トークンの枠が、SWE の1回の入力より小さいためです。

## 1. **セットアップ**
比較対象としたモデル／プロバイダー、使用したタスク、およびそれらのタスクが選ばれた理由について。

### 1.1 一回の測り方

各設定、タスクについて下記の3ステップで回しました。

1. `moulinette_eval dump swebench --task-id <id>` で `task.json` を書き出す
2. `moulinette_eval run-agent 900 "uv run python -m agent_swebench --task-file … --output … --providers_file_path <その設定だけの providers ファイル>"`
3. `moulinette_eval validate swebench task.json solution.json`（パッチを当ててテストを回し、上限も確かめる）

- 1回に1モデルだけ・フォールバックはなし。どの結果もそのモデル1つのものです。  
- 本番の設定(フォールバックあり)は、別で #7 で測りました。  
- 制限は本番と同じ30反復、入力 300,000、出力 10,000、900秒。全てタスク全体の合計。  
- 全部の設定でプロンプト・ツール・ループは同じです。変えたのは、モデル名とリクエストの設定(`model_params`)だけです。  

### 1.2 比べたモデルとプロバイダ(6社・11モデル・16設定)

**選び方**:

- OpenRouter, Groq, Mistral, NVIDIA, Google AI Studio, Cohere, Ollama, Kilo, Cloudflare, LLM7, A ZI の11社の無料モデルから選定をはじめ、203モデルありました。  
- この時点で使用できるモデル全てで計測してしまうと無料枠が尽きてしまうため、使えるモデルを絞りました。  
- まず無料モデルの中で、一覧で出てきていたけど実際に使えるものは93件でした。  
- さらにそこから計測するモデルを以下の基準で45件まで絞りました。
  - 応答に20秒以上かかるモデル(Z AI / gemini gemma-4-26b(26秒)、nemotron-bolt(57秒)など)  
  - 古い、または小さいモデル(ministral 3b/8b、allam-2-7b, tiny-ayaなど)  
- その45モデルではじめにMBPPのタスクを簡単なもの10問 × 2周回し、正答率が7 / 10以上の32モデルに絞りました。  
- さらに正答率の低い10問 × 2周の合計1モデル40問を回し、結果として難しい問題では2~7.2 / 10問と一応の差が出ました。同じ問題を複数回回答しての比較ではないため、目安としてこの値を使用しています。  

|順|プロバイダ|モデル|難しい10問|易しい10問|無応答/入力上限(難しい10問・20回中)|平均秒(難しい10問)|
|---|---|---|---|---|---|---|
|1|groq|qwen3.8-27b|**7.2**|10.0|2/3|12.5|
|2|kilo|nemotron-3-ultra-550b|**7.0**|9.0|0/3|20.4|
|3|gemini|3.1-flash-lite|6.7|8.8|5/2|7.6 |
|4|gemini|3.5-flash-lite|6.5|10.0|3/5|8.9|
|4|ollama|gpt-oss:120b|6.5|9.0|0/2|4.0|
|4|cloudflare|gpt-oss-120b|6.5|8.5|0/4|16.2|
|7|ollama|nemotron-3-ultra|6.3|9.0|1/3|28.1|
|8|nvidia| minimax-m3.1-flash|6.2|10.0| 4/2|**73.2**|
|9|cohere|command-a-plus|5.5|7.4|0/4|9.4|
|9|kilo|laguna-s-2.1|5.5|8.0|0/8|22.2|
|9|kilo|dots-3-note-preview|5.5|8.5|0/5|13.4|
|9|mistral|ministral-14b|5.5|9.0|0/10|10.8|
|9|ollama|gemma4:31b|5.5|10.0|0/3|3.8|
|9|ollama|nemotron-3-super|5.5|8.0|0/2|8.5|
|15|groq|gpt-oss-120b|5.3|7.9|5/3|3.2|
|16|cohere|command-a-03-2025|5.0|9.5|2/6|35.4|
|16|nvidia|nemotron-3-ultra-550b|5.0|8.5|0/4|19.1|
|16|nvidia|nemotron-3.5-lightning|5.0|7.5|0/8|7.6|
|-|mistral|**codestral**|**4.0**|7.0|0/8|4.5|

- Geminiの3.5-flash(8.0)と3-flash-preview(6.4)は、20回中9〜10回が枠切れ。11-01に日を改めて難しい10問を先に回しても半分が返らないため1日の枠が小さすぎて主力にも全問計測にも使用できなかった。
- 11-01 の Cloudflare(一日の枠が小さいプロバイダ)の結果:
  - gpt-oss-120b は 6.5、llama-3.3-70b は 3.0。
  - llama-4-scout は set10 で 2.5／5.7 だったので難しい問題には進まず。
  - mistral-small・qwen2.5-coder・gpt-oss-20b は、40回すべて無応答(Cloudflare では使えない)。
- 外したもの:
  - xing4.0・beam・3.7-flash(無応答ばかり)
  - minimax(73秒でMBPP120秒の制限に近い)
  - 4.0未満のモデル(north-mini-code・nano-omni・laguna-xs・gpt-oss-20b・mistral-code・nemotron-3-nano)
  

- この時点でMBPPの計測を上記のモデルで、難しい問題が5.0以上のものから、各プロバイダ1~2モデルに絞り本番のMBPPに近づけるため、1モデルごとではなくプロバイダ、モデルをproviders.jsonに並べ評価対象の全257問を1周回しました。  
- 結果としては 224 / 257で、計測を始める前に出来上がったコードで試しに全問1周回したときのスコア(233 / 257)を下回りました。  
- これは、上記の計測時に難しい10問で7.2のスコアだったgroqのqwen3.8-27bが全体の半分を解いたタイミングで枠が切れ、2番手に置いたkiloのnemotron-ultraがもう半分を解いていたためでした。  
- テスト時は上記計測で4.0のmistral codestralを使用していたので、単純に選別した10問の差ではモデルの差は測れないという結論に至りました。  
- 計測の中で、落としている問題のほとんどは入力トークンの上限でしたが、システムプロンプトや毎回送る履歴などを切り詰めて1往復分の余裕をもたせても、結果として入力上限に引っかかる頻度は減っても今度は出力上限に引っかかったり結果としてスコアの改善には繋がらず有意な差は得られないと感じたため今回は見送りました。  
- ランダム10問では差が図りづらく、全問計測が一番スコアを図りやすいとはいえそれも1周ではばらつきがあり、無料枠を使用しているので何度も測れるわけではなく、また一回の計測に時間もかかり(全問約40分、1000リクエスト前後)ので1つづつ変更をしその度に計測し直すのは現実的ではない、さらに落としている問題の中にはLLMに与えられているテストと問題分では答えを推測するのが難しい問題があり絶対にPASSできる実装にするのは無理だと判断し、MBPPの並びはトークンにも余裕があり以前の計測で上位だったmistral codestralを採用し、2番手にgroqのqwenを置くことで、もしcodestralが回答できなくても正答率の(恐らく)高いモデルにフォールバックできるように変えました。  

- SWEでは入出力の上限が大きい分推論の多いモデルを使用してもリミットにかかることが減り精度が上がると思い、推論 ON／OFF を同じモデルで並べました。  
- 推論ONの設定は、先にエージェントと同じ形のリクエスト(`stop=["<end_code>"]`・`max_tokens=1200`)で1回ずつ確かめ、どちらも本文にコードが返ってくるもののみを採用しました。
- 最終的にSWE-Benchの計測をしたのが下記の16設定です。

| プロバイダ（無料枠） | モデル | リクエストの設定 |
|---|---|---|
| Mistral | `codestral-latest` | なし |
| Cohere | `command-a-03-2025` | なし |
| Cohere | `command-a-plus-05-2026` | なし |
| Cohere | `command-a-reasoning-08-2025` | `reasoning_effort: none`／既定（ON） |
| NVIDIA NIM | `nvidia/nemotron-3-ultra-550b-a55b` | `enable_thinking: false`／`true` |
| NVIDIA NIM | `z-ai/glm-5.3-flash` | なし（推論する） |
| Ollama Cloud | `gpt-oss:120b` | `reasoning_effort: low`／`medium` |
| Ollama Cloud | `nemotron-3-ultra` | `reasoning_effort: none`／`medium` |
| Kilo Code（OpenRouter 互換） | `nvidia/nemotron-3-ultra-550b-a55b:free` | `reasoning.enabled: false`／`true` |
| Google AI Studio | `gemini-3.1-flash-lite` | `reasoning_effort: medium` |
| Google AI Studio | `gemini-3.5-flash` | なし（推論する） |

|外したもの|理由|
|---|---|
|NVIDIA `minimax-m3.1-flash`| 1回の応答に 81秒。900秒の中で約10回しか呼べない |
|NVIDIA `deepseek-v4.1-flash`| 1回の応答に 100秒 |
|Mistral `mistral-large-4`| `content` が文字列ではなくリストで返る。エージェントは空の応答として扱う |
|Mistral `magistral-medium`| 確かめたときに 429 |
|Ollama `gpt-oss:120b` 推論 high| `finish_reason=tool_calls` で本文が空（自分の形式のツール呼び出しを返す） |
|Kilo `laguna-s-2.1:free`| 計測の日に Kilo の一覧から消えていた（404）。無料モデルは予告なく消える |
|Groq(全モデル)| 1分あたり 8,000 トークンがアカウント単位。SWE の1回は 11,000〜130,000 トークンの入力なので、900秒に収まらない |
|Cloudflare| 1日の枠(10,000 neurons)が、MBPP の計測でも約40分で尽きた |

### 1.3 タスク

`sympy__sympy-14711`・`sympy__sympy-13480`・`pydata__xarray-4629` を使いました。理由は次のとおりです。

- 課題PDFで最初に試す単純な問題として挙げている`sympy__sympy-14711`、`sympy__sympy-13480`、`pydata__xarray-4629`の3問のため。  
- 3問とも moulinette の試験の候補(`EXAM_POOL` の6問)に入っていたため。  
- 14711 は、モデルの差がいちばん出た問題で、30反復まで使ったモデルが多くありました。

## 2. **結果表**
- 各モデル × タスクの組み合わせについて
    - 合格／不合格
    - 使用した反復回数
    - 入力トークンの総数
    - 出力トークンの総数
    - 実時間
    
| 設定 | タスク | 結果 | 反復 | 入力トークン | 出力トークン | 時間(秒) | 止まった理由 |
|---|---|---|---|---|---|---|---|
| Mistral / codestral-latest | xarray-4629 | PASS | 4 | 11,288 | 244 | 15 | final_answer |
| Mistral / codestral-latest | sympy-13480 | PASS | 3 | 5,331 | 222 | 19 | final_answer |
| Mistral / codestral-latest | sympy-14711 | PASS | 4 | 7,747 | 454 | 18 | final_answer |
| NVIDIA / glm-5.3-flash（推論あり） | xarray-4629 | PASS | 6 | 18,759 | 592 | 232 | final_answer |
| NVIDIA / glm-5.3-flash（推論あり） | sympy-13480 | PASS | 5 | 11,710 | 536 | 168 | final_answer |
| NVIDIA / glm-5.3-flash（推論あり） | sympy-14711 | PASS | 5 | 14,950 | 1,021 | 75 | final_answer |
| Ollama / gpt-oss:120b（推論 low） | xarray-4629 | PASS | 14 | 50,148 | 1,106 | 26 | final_answer |
| Ollama / gpt-oss:120b（推論 low） | sympy-13480 | PASS | 6 | 11,567 | 352 | 23 | final_answer |
| Ollama / gpt-oss:120b（推論 low） | sympy-14711 | PASS | 20 | 65,169 | 3,178 | 39 | final_answer |
| Ollama / gpt-oss:120b（推論 medium） | xarray-4629 | FAIL | 17 | 65,782 | 10,000 | 55 | MAX_OUTPUT_TOKENS |
| Ollama / gpt-oss:120b（推論 medium） | sympy-13480 | PASS | 9 | 27,311 | 3,371 | 41 | final_answer |
| Ollama / gpt-oss:120b（推論 medium） | sympy-14711 | PASS | 13 | 47,192 | 5,982 | 68 | final_answer |
| Cohere / command-a-03-2025 | xarray-4629 | PASS | 6 | 25,934 | 529 | 88 | final_answer |
| Cohere / command-a-03-2025 | sympy-13480 | PASS | 5 | 13,817 | 443 | 56 | final_answer |
| Cohere / command-a-03-2025 | sympy-14711 | PASS | 9 | 27,276 | 1,000 | 168 | final_answer |
| Cohere / command-a-plus-05-2026 | xarray-4629 | FAIL | 0 | 0 | 0 | 4 | LLM_UNAVAILABLE |
| Cohere / command-a-plus-05-2026 | sympy-13480 | FAIL | 0 | 0 | 0 | 7 | LLM_UNAVAILABLE |
| Cohere / command-a-plus-05-2026 | sympy-14711 | FAIL | 0 | 0 | 0 | 10 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning（推論 none） | xarray-4629 | PASS | 2 | 5,611 | 300 | 9 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning（推論 none） | sympy-13480 | PASS | 4 | 8,877 | 188 | 27 | final_answer |
| Cohere / command-a-reasoning（推論 none） | sympy-14711 | FAIL | 1 | 1,930 | 64 | 15 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning（推論 ON） | xarray-4629 | FAIL | 1 | 2,654 | 534 | 15 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning（推論 ON） | sympy-13480 | FAIL | 0 | 0 | 0 | 6 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning（推論 ON） | sympy-14711 | FAIL | 1 | 1,930 | 1,199 | 15 | LLM_UNAVAILABLE |
| Kilo / nemotron-3-ultra:free（推論 OFF） | xarray-4629 | PASS | 9 | 58,964 | 9,423 | 425 | final_answer |
| Kilo / nemotron-3-ultra:free（推論 OFF） | sympy-13480 | PASS | 7 | 19,104 | 572 | 36 | final_answer |
| Kilo / nemotron-3-ultra:free（推論 OFF） | sympy-14711 | PASS* | 30 | 122,730 | 3,245 | 235 | MAX_ITERATIONS |
| Kilo / nemotron-3-ultra:free（推論 ON） | xarray-4629 | PASS | 10 | 46,892 | 1,403 | 82 | final_answer |
| Kilo / nemotron-3-ultra:free（推論 ON） | sympy-13480 | PASS | 8 | 21,252 | 764 | 92 | final_answer |
| Kilo / nemotron-3-ultra:free（推論 ON） | sympy-14711 | FAIL | 27 | 105,197 | 4,097 | 180 | LLM_UNAVAILABLE |
| NVIDIA / nemotron-3-ultra（推論 OFF） | xarray-4629 | PASS | 15 | 65,633 | 1,216 | 99 | final_answer |
| NVIDIA / nemotron-3-ultra（推論 OFF） | sympy-13480 | PASS | 7 | 19,376 | 617 | 42 | final_answer |
| NVIDIA / nemotron-3-ultra（推論 OFF） | sympy-14711 | FAIL | 30 | 131,210 | 2,562 | 132 | MAX_ITERATIONS |
| NVIDIA / nemotron-3-ultra（推論 ON） | xarray-4629 | PASS | 9 | 34,193 | 1,160 | 82 | final_answer |
| NVIDIA / nemotron-3-ultra（推論 ON） | sympy-13480 | PASS | 6 | 13,774 | 475 | 57 | final_answer |
| NVIDIA / nemotron-3-ultra（推論 ON） | sympy-14711 | PASS* | 30 | 108,468 | 3,991 | 192 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra（推論 none） | xarray-4629 | PASS | 11 | 54,305 | 1,468 | 85 | final_answer |
| Ollama / nemotron-3-ultra（推論 none） | sympy-13480 | PASS | 6 | 14,411 | 488 | 39 | final_answer |
| Ollama / nemotron-3-ultra（推論 none） | sympy-14711 | PASS* | 30 | 110,291 | 2,517 | 175 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra（推論 medium） | xarray-4629 | PASS | 21 | 124,476 | 2,639 | 220 | final_answer |
| Ollama / nemotron-3-ultra（推論 medium） | sympy-13480 | PASS* | 30 | 106,696 | 3,702 | 278 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra（推論 medium） | sympy-14711 | FAIL | 30 | 125,707 | 4,726 | 282 | MAX_ITERATIONS |
| Google / gemini-3.1-flash-lite（推論 medium） | xarray-4629 | PASS | 3 | 10,093 | 878 | 36 | final_answer |
| Google / gemini-3.1-flash-lite（推論 medium） | sympy-13480 | PASS | 3 | 9,096 | 670 | 48 | final_answer |
| Google / gemini-3.1-flash-lite（推論 medium） | sympy-14711 | FAIL | 6 | 27,368 | 2,715 | 115 | final_answer |
| Google / gemini-3.5-flash | xarray-4629 | FAIL | 0 | 2,647 | 0 | 42 | LLM_UNAVAILABLE |
| Google / gemini-3.5-flash | sympy-13480 | FAIL | 0 | 0 | 0 | 10 | LLM_UNAVAILABLE |
| Google / gemini-3.5-flash | sympy-14711 | FAIL | 6 | 22,734 | 496 | 30 | LLM_UNAVAILABLE |

PASS\*について:  
  反復の上限で止まり、エージェントが最後に回収したパッチ(`get_patch()`)が採点で通った回。
  `LLM_UNAVAILABLE` で PASS の回(Cohere reasoning none の xarray)も同じで、途中で応答が止まったときの回収パッチが通っています。

**3問の合計**:

| 設定 | 結果 | うち自分で提出 | 平均反復 | 平均入力 | 平均出力 | 平均秒 |
|---|---|---|---|---|---|---|
| Mistral / codestral-latest | **3/3** | 3 | 4 | 8,122 | 307 | **17** |
| NVIDIA / glm-5.3-flash | **3/3** | 3 | 5 | 15,140 | 716 | 158 |
| Ollama / gpt-oss:120b（low） | **3/3** | 3 | 13 | 42,295 | 1,545 | 29 |
| Cohere / command-a-03-2025 | **3/3** | 3 | 7 | 22,342 | 657 | 104 |
| Kilo / nemotron-3-ultra（OFF） | 3/3 | 2 | 15 | 66,933 | 4,413 | 232 |
| NVIDIA / nemotron-3-ultra（ON） | 3/3 | 2 | 15 | 52,145 | 1,875 | 110 |
| Ollama / nemotron-3-ultra（none） | 3/3 | 2 | 16 | 59,669 | 1,491 | 100 |
| NVIDIA / nemotron-3-ultra（OFF） | 2/3 | 2 | 17 | 72,073 | 1,465 | 91 |
| Kilo / nemotron-3-ultra（ON） | 2/3 | 2 | 15 | 57,780 | 2,088 | 118 |
| Ollama / gpt-oss:120b（medium） | 2/3 | 2 | 13 | 46,762 | 6,451 | 55 |
| Ollama / nemotron-3-ultra（medium） | 2/3 | 1 | 27 | 118,960 | 3,689 | 260 |
| Google / gemini-3.1-flash-lite（medium） | 2/3 | 2 | 4 | 15,519 | 1,421 | 66 |
| Cohere / command-a-reasoning（none） | 2/3 | 1 | 2 | 5,473 | 184 | 17 |
| Cohere / command-a-reasoning（ON） | 0/3 | 0 | - | - | - | - |
| Cohere / command-a-plus | 0/3 | 0 | - | - | - | - |
| Google / gemini-3.5-flash | 0/3 | 0 | - | - | - | - |

## 3. **プロバイダーの信頼性**
- 各モデル／プロバイダーについて
    - リクエストあたりの平均応答時間
    - 必要な再試行回数（レート制限、タイムアウト、エラー）
    - ベンチマーク実行中の全体的な可用性 
  
| 設定 | 結果 | 1リクエストの平均応答時間(秒) | リクエスト数 | リトライ | 失敗したリクエスト | 成功率 | 提供側の失敗で終わらなかった回 |
|---|---|---|---|---|---|---|---|
| Mistral / codestral-latest | 3/3 | **1.4** | 11 | 0 | 0 | 100% | 3/3 |
| NVIDIA / glm-5.3-flash | 3/3 | 27.3 | 16 | 0 | 0 | 100% | 3/3 |
| Ollama / gpt-oss:120b（low） | 3/3 | **1.2** | 40 | 0 | 0 | 100% | 3/3 |
| Ollama / gpt-oss:120b（medium） | 2/3 | 2.3 | 39 | 0 | 0 | 100% | 3/3 |
| Cohere / command-a-03-2025 | 3/3 | 8.7 | 21 | 1 | 1 | 95% | 3/3 |
| Cohere / command-a-plus-05-2026 | 0/3 | - | 3 | 0 | 3 | 0% | 0/3 |
| Cohere / command-a-reasoning（none） | 2/3 | 2.7 | 9 | 0 | 2 | 78% | 1/3 |
| Cohere / command-a-reasoning（ON） | 0/3 | 10.5 | 5 | 0 | 3 | 40% | 0/3 |
| Kilo / nemotron-3-ultra（OFF） | 3/3 | 12.2 | 47 | 1 | 1 | 98% | 3/3 |
| Kilo / nemotron-3-ultra（ON） | 2/3 | 6.4 | 46 | 0 | 1 | 98% | 2/3 |
| NVIDIA / nemotron-3-ultra（OFF） | 2/3 | 4.2 | 52 | 0 | 0 | 100% | 3/3 |
| NVIDIA / nemotron-3-ultra（ON） | 3/3 | 5.6 | 46 | 1 | 1 | 98% | 3/3 |
| Ollama / nemotron-3-ultra（none） | 3/3 | 4.8 | 47 | 0 | 0 | 100% | 3/3 |
| Ollama / nemotron-3-ultra（medium） | 2/3 | 7.3 | 82 | 1 | 1 | 99% | 3/3 |
| Google / gemini-3.1-flash-lite（medium） | 2/3 | 13.5 | 12 | 0 | 0 | 100% | 3/3 |
| Google / gemini-3.5-flash | 0/3 | 3.0 | 12 | 0 | 6 | 50% | 0/3 |

- **Mistral・Ollama は、失敗したリクエストが0件**。応答も 1.2〜4.8秒と速い。
- **Cohere は、モデルによって大きく違います**。
  - command-a は 95%（1件の失敗は、リトライで回復）でした。
  - plus と reasoning は、422 でほとんど使えませんでした。
  - 10-30 の試しでも、command-a が途中から 422 になる回がありました。
  - 試用キーは月 1,000回までと少なめです。
  - 1回の応答が 8.7秒と遅めです。選定では 93.9秒かかった応答もありました。
- **NVIDIA は、落ちないが遅いことがあります**。
  - glm-5.3-flash は1回 27秒、nemotron-3-ultra は 4〜6秒でした。確かめのとき、推論 ON で1回だけ 503 が出ました。
- **Kilo** は、OpenRouter と同じ形のゲートウェイです。
  - `:free` のモデルは、予告なく一覧から消えます（laguna-s が計測の日に消えた）。
- **Google** は、gemini-3.5-flash の1日の枠が小さすぎます。3問を回し切れませんでした。


## 4. **中間指標**（以下のうち少なくとも2つ）
- エージェントが、最終パッチに含まれるファイルを初めて読み込んだ／編集したステップ（探索効率）
- テストの失敗数がベースラインと比較して初めて減少したステップ（部分的な進捗）
- 「tests first pass」とfinal_answerの間の反復回数（提出の規律— 0回が理想的）
これらの指標は、**solution.json** ファイルを確認することで手動で測定可能です
自動化は必須ではありません。重要なのは分析そのものであり、ツールではありません。

| 設定 | タスク | 最終パッチのファイルを初めて読んだステップ | 初めて編集したステップ | テストが全部通ってから final_answer までの反復 |
|---|---|---|---|---|
| Mistral / codestral-latest | xarray-4629 | 2 | 3 | 1 |
| Mistral / codestral-latest | sympy-13480 | 2 | 3 | 0 |
| Mistral / codestral-latest | sympy-14711 | 2 | 4 | 0 |
| NVIDIA / glm-5.3-flash | xarray-4629 | 2 | 3 | 1 |
| NVIDIA / glm-5.3-flash | sympy-13480 | 2 | 3 | 1 |
| NVIDIA / glm-5.3-flash | sympy-14711 | 1 | 3 | 1 |
| Ollama / gpt-oss:120b（low） | xarray-4629 | 12 | 13 | - |
| Ollama / gpt-oss:120b（low） | sympy-13480 | - | 3 | 1 |
| Ollama / gpt-oss:120b（low） | sympy-14711 | 3 | 11 | 3 |
| Ollama / gpt-oss:120b（medium） | sympy-13480 | 4 | 5 | 1 |
| Ollama / gpt-oss:120b（medium） | sympy-14711 | 3 | 5 | 1 |
| Cohere / command-a-03-2025 | xarray-4629 | 2 | 3 | 1 |
| Cohere / command-a-03-2025 | sympy-13480 | 2 | 3 | 1 |
| Cohere / command-a-03-2025 | sympy-14711 | 2 | 7 | 2 |
| Kilo / nemotron-3-ultra（OFF） | xarray-4629 | 1 | 2 | 6 |
| Kilo / nemotron-3-ultra（OFF） | sympy-13480 | 1 | 2 | 3 |
| Kilo / nemotron-3-ultra（OFF） | sympy-14711 | 2 | 27 | - |
| Kilo / nemotron-3-ultra（ON） | xarray-4629 | 3 | 5 | 3 |
| Kilo / nemotron-3-ultra（ON） | sympy-13480 | 2 | 3 | 2 |
| NVIDIA / nemotron-3-ultra（OFF） | xarray-4629 | 4 | 11 | 2 |
| NVIDIA / nemotron-3-ultra（OFF） | sympy-13480 | 1 | 2 | 3 |
| NVIDIA / nemotron-3-ultra（ON） | xarray-4629 | 2 | 4 | 3 |
| NVIDIA / nemotron-3-ultra（ON） | sympy-13480 | 2 | 3 | 1 |
| NVIDIA / nemotron-3-ultra（ON） | sympy-14711 | 2 | 22 | - |
| Ollama / nemotron-3-ultra（none） | xarray-4629 | 2 | 4 | 5 |
| Ollama / nemotron-3-ultra（none） | sympy-13480 | 1 | 2 | 2 |
| Ollama / nemotron-3-ultra（none） | sympy-14711 | 2 | 15 | - |
| Ollama / nemotron-3-ultra（medium） | xarray-4629 | 3 | 5 | 14 |
| Ollama / nemotron-3-ultra（medium） | sympy-13480 | 2 | 4 | - |
| Google / gemini-3.1-flash-lite（medium） | xarray-4629 | 1 | 1 | - |
| Google / gemini-3.1-flash-lite（medium） | sympy-13480 | 1 | 1 | - |
| Google / gemini-3.1-flash-lite（medium） | sympy-14711 | 1 | 5 | - |

- パッチを作らなかった回（422 で止まった回など）は省きました。
- `-` の意味:
  - 「読んだ」が `-`: `read_file` を使わずに、`run_command`（`sed -n`・`cat`）や `search_code` で中身を見た回です。
  - 最後の列が `-`: `run_tests()` が全部通ったのを見ないまま終わった回です。テストを回さずに提出した回と、反復の上限で止まった回があります。

**探索の効率**:

- 3問とも PASS した上位4設定は、正しいファイルを1〜2ステップ目で読み、3〜4ステップ目（14711 の Cohere は7）で編集しています。課題文が直す関数を名指ししているので、強いモデルはまっすぐそこへ行きます。
- 差が出たのは 14711 です。nemotron-3-ultra は、どの社でも2ステップ目には正しいファイルを読んでいます。それでも、最初の編集は15・22・27ステップ目でした。読んではいるのに、直す方針を決めきれず、確かめをくり返しています。
- gpt-oss:120b（low）の xarray は、最終パッチのファイル（`merge.py`）を12ステップ目に初めて読んでいます。それまでは `search_code` と `run_command` で、まわりを探していました。

**提出の規律**:

- codestral は、14711・13480 で **0**（テストを回して、通ったらそのまま同じステップで `final_answer(get_patch())`）でした。xarray は 1 です。
- Cohere command-a と glm-5.3-flash は、ほぼ 1 です（結果を読んでから提出）。
- nemotron-3-ultra は、通ってからも 2〜6回、medium では14回も確かめを続けました。
- SWE では、残りが4反復になると「探すのをやめて提出せよ」とエージェントが伝えます（`[BUDGET]`・`iteration_warn_at=4`）。それでも、反復の上限に当たった回がありました。
- gemini-3.1-flash-lite は、3問とも `run_tests()` が全部通るのを見ないまま提出しました（列が `-`）。14711 は、それで隠れたテストに落ちています。


## 5. アブレーション研究
- 同じモデルを用いて同じタスクに対して、エージェントへの変更（プロンプト、ツール、パラメータ）前後の比較を少なくとも1回行うこと

### 5.1 推論の強さ（パラメータ）: 同じモデル・同じ3問 

変えたのは、リクエストの推論の設定（`model_params`）だけです。

| モデル | 弱い／OFF | 強い／ON | 差 |
|---|---|---|---|
| Ollama gpt-oss:120b（low → medium） | 3/3・平均13反復・出力 1,545・29秒 | **2/3**・13反復・出力 **6,451**・55秒 | medium は出力が4倍になり、xarray で上限 10,000 に当たって FAIL |
| Ollama nemotron-3-ultra（none → medium） | 3/3・16反復・入力 59,669・100秒 | **2/3**・**27反復**・入力 **118,960**・260秒 | 反復と入力が約2倍。2問が反復の上限 |
| NVIDIA nemotron-3-ultra（OFF → ON） | 2/3・17反復・入力 72,073 | 3/3・15反復・入力 52,145 | ON がやや良い。ただし 14711 の PASS は回収パッチ |
| Kilo nemotron-3-ultra（OFF → ON） | 3/3・15反復・出力 4,413 | 2/3・15反復・出力 2,088 | OFF がやや良い。ON の 14711 は応答が止まって FAIL |
| Cohere command-a-reasoning（none → ON） | 2/3 | 0/3 | ON は 422 で使えない |

**分かったこと**:

- **推論を強くしても、合格は増えませんでした**。5組の比べのうち、強いほうが良かったのは NVIDIA の1組だけです。それも回収パッチの PASS でした。
- **出力の上限（10,000）が、推論には狭い**:
  - SWE は1問に10〜30回呼びます。1回あたりに使える出力は、330〜1,000 トークンです。
  - gpt-oss medium は1回平均約500トークンを使い、xarray では17反復で上限に当たりました。
  - 課題 PDF VI.1.2 の「推論で上限が厳しくなるなら、推論しないモデルも検討せよ」のとおりです。
- **推論すると、反復が増えることもあります**（ollama ultra: 16 → 27）。考えた分、試す回数も増えています。
- 推論するモデルで良かったのは glm-5.3-flash（3/3・平均5反復）です。1回で考えて少ない反復で決める型ですが、1回 27秒と遅いです。
- **注意**: どれも1回ずつ（n=1）です。同じ設定でも、反復の数はかなり揺れます（#7 の codestral の 14711 は 4・21・6反復）。

- 他にも単純な比較であれば
  - 1番手をcohereとcodestralで全6問計測
    - 同じモデルでは無いため除外。
  - 14711だけを9回ずつ、上位の5候補で計測
    - 14711以外はどのモデルでも正答率が高かったが、これだけ30反復回ってバッチ回収などブレがあったためメインの問題として計測(NVIDIA glm, Ollama gpt 推論low / midiumが9 / 9)。同じモデルではないため除外。
  - プロンプト、提出の検査の改善、Observationの改善、プロンプトの短縮、送り直す履歴を2往復から1往復にしトークン節約、プロバイダの並び
    - MBPPでの計測時に行ったため除外。


## 6. 結論
- 最終的なパイプラインにどのモデルを選択したか、およびその理由。
- どのモデルを無視できるか、およびその理由。データに基づいて記述すること。

- 裏付けとなる solution.json ファイルは、リポジトリ内に必ず含まれている必要があります。

**決め方**: 速さより正答率を優先しました。手順は次の3段です。

1. 簡単な3問で、16設定から候補を絞る(#2)
2. 差の出た 14711 を9回ずつ回す（#5）
3. 9/9 だった3モデルで、6問 × 3周を回す（#7）

**SWE-bench の本番の並び**(`providers/providers_swebench.json`)

1. **Ollama `gpt-oss:120b`（推論 low）** → 同じ Ollama の `nemotron-3-ultra`（推論 none）
   - 6問 × 3周を1モデルだけで **18/18**、14711 は **9/9** でした。
   - 18回とも自分で提出し、上限にも当たっていません。
   - 1問平均 32秒・1回 1.2秒と、速さも上位です。
   - `nemotron-3-ultra` は、gpt-oss が応答しなかったときの同じ社の予備です。
2. **NVIDIA `glm-5.3-flash`** → `nemotron-3-ultra`（推論 ON）
   - 17/18（落ちた1回は通信エラー）、14711 は 9/9 でした。
   - 1回 27秒と遅いので2番手です。
   - 1番手と別の社にしたのは、同じコードのくり返しで切り替わったときに、違う間違い方をするモデルに渡すためです。
3. **Mistral `codestral-latest`**
   - 速くて枠も大きいですが、14711 は 3/9、scikit-learn は 1/4 でした。自信をもって間違ったパッチを出すことがあるので、3番手です。
4. Google `gemini-3.1-flash-lite`（推論 medium）: 3問で 2/3、14711 は 6/9。
5. Kilo `nemotron-3-ultra:free`（推論 OFF）: `:free` は消えることがあるので後ろに置きます。
6. Cohere `command-a-03-2025`
   - 3問では 3/3 でした。しかし、試用キーの月 1,000回の上限があり、計測中にその上限に達しました。
   - 1回の応答も遅いので、最後の保険にします。

- 確認: この並びのファイルで、6問 × 2周を回して **12/12** でした（#7）。
- 最終的にOllama `gpt-oss:120b`を使用した並びが合計 30 / 30、14711は 9 / 9 でした。

**比べた並びのまとめ**（6問）:

| 並び（1番手） | 結果 |
|---|---|
| cohere command-a（今の本番。実質は nemotron-ultra） | 15/18（14711 は 0/3） |
| codestral | 19/24（14711 は 5/9、scikit-learn は 1/4） |
| **gpt-oss:120b（low）単体** | **18/18** |

**使わないもの**:

| モデル | 理由 |
|---|---|
| Cohere command-a-plus・command-a-reasoning（推論 ON） | 毎回 422 |
| Google gemini-3.5-flash | 1日の枠が小さく、3問を回し切れない |
| 推論を強くした設定（gpt-oss medium・nemotron medium） | 合格が増えず、出力・反復が増える。gpt-oss は出力の上限に当たった |
| Groq | 1分あたり 8,000 トークンでは、SWE の1回を 900秒に収められない |
| minimax・deepseek（NVIDIA） | 1回の応答が 80〜100秒 |

**データから言えること**:

- SWE の上限（出力 10,000）の中では、**推論を強くしても合格は増えませんでした**。同じ gpt-oss:120b でも、low の 18/18 に対して medium は 16/18 です。
- **1回だけの計測では、モデルの強さを見誤ります**。
  - codestral は、選定の1回では 14711 を通しましたが、9回では 3/9 でした。
  - 3問の選定（n=1）は候補を絞るのに使い、最後は回数を重ねて決めました。
- 簡単な問題（13480・django など）は、上位のどのモデルでも解けます。並びの差は 14711・scikit-learn のような、迷いやすい問題で出ます。
- 「提出が早いこと」は、良いことばかりではありません。codestral は少ない反復で提出しますが、間違ったパッチを出すと、そこで回が終わります。フォールバックは、それを救えません。


## 7. 本番の設定での確認（全6問）

- moulinette の試験の候補（`EXAM_POOL`）の6問を、本番の並び（フォールバックあり）で回しました。

| 並び | 回数 | 結果 |
|---|---|---|
| codestral が1番手（mistral → ollama → nvidia → cohere → kilo → gemini） | 4周（r1〜r4） | 6・5・4・4 → **19/24（79%）** |
| cohere が1番手（今の `providers_swebench.json`。cohere は1周目の途中から枠切れで、実質 nemotron-3-ultra が1番手） | 3周（r1〜r3） | 5・5・5 → **15/18（83%）** |
| 上位3モデル（14711 で 9/9）を1モデルだけで × 6問 × 3周 | 下の表 | gpt-oss low **18/18**・glm 17/18・gpt-oss medium 16/18 |
| **最終の並び（gpt-oss が1番手。#6）** | 2周（11-02 07:12〜07:26） | **12/12**（平均 9.5反復・入力約30,500・出力約1,260・35秒）。答えたのは gpt-oss:120b だけで、xarray の1回だけ途中から glm-5.3-flash に切り替わって通った |

**上位3モデル × 6問 × 3周（1モデルだけ・フォールバックなし・11-02）**:

| タスク | gpt-oss:120b（low） | glm-5.3-flash | gpt-oss:120b（medium） |
|---|---|---|---|
| django-11066 | 3/3（5〜7反復・15〜25秒） | 3/3（4〜5・17〜46秒） | 3/3（5〜18・16〜36秒） |
| xarray-4629 | 3/3（7〜8・20〜22秒） | 3/3（4〜6・52〜66秒） | 3/3（4〜7・17〜31秒） |
| scikit-learn-13439 | 3/3（7〜9・22〜24秒） | 3/3（5〜10・44〜93秒） | 2/3（1回は反復の上限で FAIL、1回は上限の回収パッチで PASS） |
| sympy-13480 | 3/3（3〜6・31〜40秒） | 3/3（4〜5・43〜270秒） | 3/3（4〜9・11〜55秒） |
| sympy-14711 | 3/3（7〜10・19〜42秒） | 2/3（1回は NVIDIA の通信エラー〔TransportError〕で応答が止まる） | 2/3（出力の上限 10,000 に2回当たり、1回は回収パッチで PASS） |
| sympy-18189 | 3/3（3〜11・59〜61秒） | 3/3（4〜5・59〜111秒） | 3/3（5〜28・51〜195秒） |
| **合計** | **18/18** | **17/18** | **16/18** |
| 平均（1問） | 7反復・入力約21,000・出力約740・32秒 | 6反復・入力約21,000・出力約1,240・105秒 | 14反復・入力約49,000・出力約4,030・51秒 |

- **gpt-oss:120b（low）は、18回とも自分で `final_answer` を出して通しました**。反復の上限・出力の上限に一度も当たっていません。
- 同じ gpt-oss:120b でも、推論 medium にすると、反復は約2倍、出力は約5倍に増えます。出力の上限（10,000）や反復の上限（30）に当たって、2回落ちました（§5.1 と同じ傾向）。
- glm-5.3-flash は、モデルとしては全部解けています。落ちた1回は、NVIDIA の API の通信エラーで応答が止まったものです。1問あたり平均105秒と遅めです。

**問題ごと（PASS の回数）**:

| タスク | codestral が1番手（4周） | cohere が1番手＝実質 nemotron-ultra（3周） |
|---|---|---|
| django-11066 | 4/4 | 3/3 |
| xarray-4629 | 3/4（r4 が出力の上限） | 3/3 |
| scikit-learn-13439 | 1/4 | 3/3 |
| sympy-13480 | 4/4 | 3/3 |
| sympy-14711 | 3/4（14711 だけの追加5回を含めると 5/9） | 0/3 |
| sympy-18189 | 4/4 | 3/3 |

- **codestral が1番手の並びの弱点**:
  - scikit-learn（1/4）: 3〜4反復で間違ったパッチを提出する回が2回、`edit_file` の失敗をくり返して出力の上限に当たる回が1回ありました。
  - 14711（5/9）: 間違ったパッチを提出する回と、出力の上限に当たる回がありました。
  - codestral は提出が早い（速くて安い）一方で、自信をもって間違えることがあります。間違ったパッチを提出すると、そこで回が終わるので、フォールバックが働く前に負けます。
- **nemotron-ultra が1番手のとき**は、14711 以外は全部通りました（15/15）。ただし 14711 は3回とも、30反復の上限で止まりました。

**codestral が1番手の r1・r2**:

| タスク | r1 | r2 |
|---|---|---|
| sympy-14711 | PASS（21反復・57秒。codestral 7回 → 同じコードの繰り返しで切り替え → gpt-oss 14回） | PASS（6・37秒） |
| sympy-13480 | PASS（4・23秒） | PASS（4・29秒） |
| xarray-4629 | PASS（4・15秒） | PASS（4・15秒） |
| django-11066 | PASS（4・17秒） | PASS（4・19秒） |
| scikit-learn-13439 | PASS（5・28秒） | **FAIL**（出力の上限） |
| sympy-18189 | PASS（4・57秒） | PASS（3・54秒） |

- r2 の scikit-learn の FAIL:
  - codestral が `edit_file` の置き換え元の文字列を合わせられず、メソッドを丸ごと書き写す応答（1回 1,200トークンの上限まで）を6回出しました。
  - 毎回少しずつ違うので、「同じコードが2回続くと切り替え」がすぐには働きませんでした。
  - gpt-oss に切り替わったときには、出力の残りがほとんどありませんでした。
  - エージェント側の改善の候補です（今回は入れていません）。

## 8. MBPP について

- 試験の範囲（test split の257問）を全部回した結果です。
  - 10-30（メンバー、今の本番の並び）: 233/257（90.7%）
  - 11-01（並び B）: 224/257（87.2%）
  - 11-02（A と C を1問ずつ交互）: A 234（91.1%）・C **237**（92.2%）→ **本番は C**
- 試験は5問中4問のため、1問の成功率が 0.92 なら、合格の見込みは約95%です。

## 9. データの置き場所

`benchmark/swebench/` に、201回分を置きました（約 39MB）。

- 1回ごとに、次の6つがあります。
  - `solution.json`
  - `task.json`
  - `validate.log`（採点の全文）
  - `validate_summary.txt`（`validate.log` から判定の行だけを抜き出したもの）
  - `agent_stdout.log`・`agent_stderr.log`（エージェントの標準出力・標準エラー）
- 設定ごとに、その回に使った `providers.json` があります。

| フォルダ | 中身 | この文書の節 |
|---|---|---|
| `selection_easy3/<設定>/r1/<タスク>/` | 簡単な3問 × 16設定 | §2〜§5.1 |
| `task14711_repeats/<設定>/r<回>/sympy__sympy-14711/` | 14711 だけの追加の回（r2〜r9。本番の並びの案は r5〜r9） | §5.2b |
| `top3_6tasks/<設定>/r<回>/<タスク>/` | 上位3モデル × 6問 × 3周 | §7 |
| `production_codestral_first/swe_final/r<回>/<タスク>/` | codestral が1番手の並び × 6問 × 4周 | §5.2・§7 |
| `production_cohere_first/swe_cohere/r<回>/<タスク>/` | cohere が1番手の並び × 6問 × 3周 | §5.2・§7 |
| `production_final/swe_final2/r<回>/<タスク>/` | 最終の並び × 6問 × 2周 | §6・§7 |

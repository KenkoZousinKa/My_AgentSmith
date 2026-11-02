# SWE-bench Model Benchmark Report for Agent_Smith

[日本語版 (Japanese)](BENCHMARK_REPORT_ja.md)

## 📖*Contents*
0. [Introduction](#0-introduction)
1. [Setup](#1-setup)
2. [Results table](#2-results-table)
3. [Provider reliability](#3-provider-reliability)
4. [Intermediary metrics](#4-intermediary-metrics-at-least-2-of-the-following)
5. [Ablation study](#5-ablation-study)
6. [Conclusion](#6-conclusion)
7. [Check with the production settings (all 6 tasks)](#7-check-with-the-production-settings-all-6-tasks)
8. [About MBPP](#8-about-mbpp)
9. [Where the data is](#9-where-the-data-is)

## 0. **Introduction**
- **What we compared**:
- The subject requires comparing at least 5 models across at least 2 providers on at least 3 SWE-bench tasks.
- As the tasks to compare first, we chose the three that the subject PDF lists as simple tasks to try first: `sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629`.
- We compared 16 settings of 11 models from 6 providers. The same model with reasoning ON and OFF counts as two different settings.
- Each setting was run with a single model only (no backoff or fallback to other models or providers).
- The time and token limits are the same as the real ones.

- **7 settings passed all 3 tasks**. Four of them passed by submitting with `final_answer` themselves:
    - Mistral codestral
    - NVIDIA glm-5.3-flash
    - Ollama gpt-oss:120b (reasoning low)
    - Cohere command-a
- The other three each passed one task (14711) with the patch recovered from their work so far (`get_patch()`) when they stopped at the iteration limit (30).

- **Stronger reasoning did not raise the score** (#5).
  - gpt-oss:120b used up the output limit (10,000) with reasoning medium.
  - nemotron-3-ultra went from 16 to 27 iterations with reasoning medium.

- **Production order**
    **Ollama gpt-oss:120b (reasoning low) goes first.**
  - It got **18/18** on the 6 candidate exam tasks × 3 rounds, running as the only model.
  - On 14711, the task that separated the models most, it got 9/9.
  - Second is NVIDIA glm-5.3-flash (17/18; the one failure was a network error at NVIDIA).
  - cohere command-a, which was first in the previous production order, and codestral, which we had planned to use, both failed some runs on 14711 and scikit-learn.

- **Not used**:
  - Cohere command-a-plus and command-a-reasoning (reasoning ON): HTTP 422 every time.
  - Gemini 3.5-flash: the daily quota was too small.
  - Groq: its quota of 8,000 tokens per minute is smaller than the input of a single SWE call.

## 1. **Setup**
Which models/providers were compared, which tasks were used, and why those tasks were selected.

### 1.1 How one run is measured

For each setting and task, we ran these 3 steps.

1. Write `task.json` with `moulinette_eval dump swebench --task-id <id>`
2. `moulinette_eval run-agent 900 "uv run python -m agent_swebench --task-file … --output … --providers_file_path <a providers file with only that setting>"`
3. `moulinette_eval validate swebench task.json solution.json` (applies the patch, runs the tests, and also checks the limits)

- One model per run, no fallback. Every result comes from that one model.
- The production settings (with fallback) were measured separately, in #7.
- The limits are the same as in production: 30 iterations, 300,000 input, 10,000 output, 900 seconds, all totals for the whole task.
- The prompt, tools and loop are the same for every setting. Only the model name and the request settings (`model_params`) were changed.

### 1.2 Models and providers compared (6 providers, 11 models, 16 settings)

**How we chose them**:

- We started from the free models of 11 providers (OpenRouter, Groq, Mistral, NVIDIA, Google AI Studio, Cohere, Ollama, Kilo, Cloudflare, LLM7, Z AI), 203 models in total.
- Measuring every available model would use up the free quotas, so we narrowed down the models we could use.
- First, of the free models in the lists, 93 actually worked.
- From those, we narrowed the models to measure down to 45 by removing:
  - models that took 20 seconds or more to respond (Z AI / gemini gemma-4-26b (26 seconds), nemotron-bolt (57 seconds), etc.)
  - old or small models (ministral 3b/8b, allam-2-7b, tiny-aya, etc.)
- With those 45 models, we first ran 10 easy MBPP tasks × 2 rounds, and kept the 32 models that solved 7/10 or more.
- We then ran 10 tasks with low pass rates × 2 rounds (40 tasks per model in total). On the hard tasks there was some spread, from 2 to 7.2 out of 10. These are not comparisons over many repeats of the same tasks, so we use these values only as a rough guide.

|Rank|Provider|Model|Hard 10|Easy 10|No response / input limit (hard 10, out of 20 runs)|Avg. seconds (hard 10)|
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

- Gemini 3.5-flash (8.0) and 3-flash-preview (6.4) ran out of quota in 9–10 of 20 runs. On 11-01 we tried again on a new day, running the hard 10 first, and half still did not come back. The daily quota is too small to use them as a main model or for a full run.
- Results for Cloudflare (a provider with a small daily quota) on 11-01:
  - gpt-oss-120b scored 6.5, llama-3.3-70b scored 3.0.
  - llama-4-scout scored 2.5 / 5.7 on set10, so it did not go on to the hard tasks.
  - mistral-small, qwen2.5-coder and gpt-oss-20b gave no response in all 40 runs (not usable on Cloudflare).
- Removed:
  - xing4.0, beam, 3.7-flash (almost always no response)
  - minimax (73 seconds, close to MBPP's 120-second limit)
  - models below 4.0 (north-mini-code, nano-omni, laguna-xs, gpt-oss-20b, mistral-code, nemotron-3-nano)


- At this point, to get closer to the production MBPP setup, we took the models above that scored 5.0 or more on the hard tasks, narrowed them to 1–2 models per provider, and listed the providers and models in providers.json (instead of one model at a time). We then ran all 257 tasks in the evaluation range once.
- The result was 224/257, lower than the score of a trial full run (233/257) made with the code we had before starting the measurements.
- This was because groq's qwen3.8-27b, which scored 7.2 on the hard 10 above, ran out of quota halfway through, and kilo's nemotron-ultra, placed second, solved the other half.
- In the trial run we had used mistral codestral, which scored only 4.0 in the measurement above. So we concluded that the difference on 10 hand-picked tasks cannot measure the difference between models.
- Most of the tasks lost during the measurements failed on the input token limit. We trimmed the system prompt and the history sent each time to leave room for one more turn. That reduced how often the input limit was hit, but the runs then hit the output limit instead, and the score did not improve. We did not see a meaningful difference, so we did not adopt the change this time.
- With 10 random tasks it is hard to measure differences. A full run measures the score best, but even that varies from round to round. We use free quotas, so we cannot measure many times, and one run takes time (about 40 minutes and about 1,000 requests for all tasks), so changing one thing at a time and measuring again after each change is not realistic. On top of that, some of the lost tasks are hard to infer the answer to from the tests and the problem statement given to the LLM, so we judged that an implementation that always passes is impossible. For the MBPP order, we chose mistral codestral, which has plenty of token headroom and ranked high in earlier measurements, and put groq's qwen second, so that if codestral cannot answer, the agent falls back to a model with a (probably) higher pass rate.

- For SWE, we expected that with the larger input/output limits, models that reason more would hit the limits less often and be more accurate, so we put reasoning ON and OFF of the same model side by side.
- Each reasoning-ON setting was first checked once with a request of the same shape as the agent's (`stop=["<end_code>"]`, `max_tokens=1200`), and only settings that returned code in the body in both cases were adopted.
- The final SWE-bench measurements used the following 16 settings.

| Provider (free tier) | Model | Request settings |
|---|---|---|
| Mistral | `codestral-latest` | none |
| Cohere | `command-a-03-2025` | none |
| Cohere | `command-a-plus-05-2026` | none |
| Cohere | `command-a-reasoning-08-2025` | `reasoning_effort: none` / default (ON) |
| NVIDIA NIM | `nvidia/nemotron-3-ultra-550b-a55b` | `enable_thinking: false` / `true` |
| NVIDIA NIM | `z-ai/glm-5.3-flash` | none (reasons) |
| Ollama Cloud | `gpt-oss:120b` | `reasoning_effort: low` / `medium` |
| Ollama Cloud | `nemotron-3-ultra` | `reasoning_effort: none` / `medium` |
| Kilo Code (OpenRouter-compatible) | `nvidia/nemotron-3-ultra-550b-a55b:free` | `reasoning.enabled: false` / `true` |
| Google AI Studio | `gemini-3.1-flash-lite` | `reasoning_effort: medium` |
| Google AI Studio | `gemini-3.5-flash` | none (reasons) |

|Removed|Reason|
|---|---|
|NVIDIA `minimax-m3.1-flash`| 81 seconds per response. Only about 10 calls fit in 900 seconds |
|NVIDIA `deepseek-v4.1-flash`| 100 seconds per response |
|Mistral `mistral-large-4`| `content` comes back as a list, not a string. The agent treats it as an empty response |
|Mistral `magistral-medium`| 429 when we checked it |
|Ollama `gpt-oss:120b` reasoning high| Empty body with `finish_reason=tool_calls` (returns tool calls in its own format) |
|Kilo `laguna-s-2.1:free`| Gone from Kilo's list on the day of the measurement (404). Free models disappear without notice |
|Groq (all models)| 8,000 tokens per minute, per account. One SWE run has 11,000–130,000 input tokens, so it does not fit in 900 seconds |
|Cloudflare| The daily quota (10,000 neurons) ran out in about 40 minutes even in the MBPP measurement |

### 1.3 Tasks

We used `sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629`, for these reasons:

- The subject PDF lists `sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629` as simple tasks to try first.
- All three are among the moulinette's candidate exam tasks (the 6 tasks of `EXAM_POOL`).
- 14711 is the task that separated the models most; many models used all 30 iterations on it.

## 2. **Results table**
- For each model × task combination:
    - Pass/Fail
    - Iterations used
    - Total input tokens
    - Total output tokens
    - Wall-clock time

| Setting | Task | Result | Iterations | Input tokens | Output tokens | Time (s) | Stop reason |
|---|---|---|---|---|---|---|---|
| Mistral / codestral-latest | xarray-4629 | PASS | 4 | 11,288 | 244 | 15 | final_answer |
| Mistral / codestral-latest | sympy-13480 | PASS | 3 | 5,331 | 222 | 19 | final_answer |
| Mistral / codestral-latest | sympy-14711 | PASS | 4 | 7,747 | 454 | 18 | final_answer |
| NVIDIA / glm-5.3-flash (reasoning) | xarray-4629 | PASS | 6 | 18,759 | 592 | 232 | final_answer |
| NVIDIA / glm-5.3-flash (reasoning) | sympy-13480 | PASS | 5 | 11,710 | 536 | 168 | final_answer |
| NVIDIA / glm-5.3-flash (reasoning) | sympy-14711 | PASS | 5 | 14,950 | 1,021 | 75 | final_answer |
| Ollama / gpt-oss:120b (reasoning low) | xarray-4629 | PASS | 14 | 50,148 | 1,106 | 26 | final_answer |
| Ollama / gpt-oss:120b (reasoning low) | sympy-13480 | PASS | 6 | 11,567 | 352 | 23 | final_answer |
| Ollama / gpt-oss:120b (reasoning low) | sympy-14711 | PASS | 20 | 65,169 | 3,178 | 39 | final_answer |
| Ollama / gpt-oss:120b (reasoning medium) | xarray-4629 | FAIL | 17 | 65,782 | 10,000 | 55 | MAX_OUTPUT_TOKENS |
| Ollama / gpt-oss:120b (reasoning medium) | sympy-13480 | PASS | 9 | 27,311 | 3,371 | 41 | final_answer |
| Ollama / gpt-oss:120b (reasoning medium) | sympy-14711 | PASS | 13 | 47,192 | 5,982 | 68 | final_answer |
| Cohere / command-a-03-2025 | xarray-4629 | PASS | 6 | 25,934 | 529 | 88 | final_answer |
| Cohere / command-a-03-2025 | sympy-13480 | PASS | 5 | 13,817 | 443 | 56 | final_answer |
| Cohere / command-a-03-2025 | sympy-14711 | PASS | 9 | 27,276 | 1,000 | 168 | final_answer |
| Cohere / command-a-plus-05-2026 | xarray-4629 | FAIL | 0 | 0 | 0 | 4 | LLM_UNAVAILABLE |
| Cohere / command-a-plus-05-2026 | sympy-13480 | FAIL | 0 | 0 | 0 | 7 | LLM_UNAVAILABLE |
| Cohere / command-a-plus-05-2026 | sympy-14711 | FAIL | 0 | 0 | 0 | 10 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning none) | xarray-4629 | PASS | 2 | 5,611 | 300 | 9 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning none) | sympy-13480 | PASS | 4 | 8,877 | 188 | 27 | final_answer |
| Cohere / command-a-reasoning (reasoning none) | sympy-14711 | FAIL | 1 | 1,930 | 64 | 15 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning ON) | xarray-4629 | FAIL | 1 | 2,654 | 534 | 15 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning ON) | sympy-13480 | FAIL | 0 | 0 | 0 | 6 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning ON) | sympy-14711 | FAIL | 1 | 1,930 | 1,199 | 15 | LLM_UNAVAILABLE |
| Kilo / nemotron-3-ultra:free (reasoning OFF) | xarray-4629 | PASS | 9 | 58,964 | 9,423 | 425 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning OFF) | sympy-13480 | PASS | 7 | 19,104 | 572 | 36 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning OFF) | sympy-14711 | PASS* | 30 | 122,730 | 3,245 | 235 | MAX_ITERATIONS |
| Kilo / nemotron-3-ultra:free (reasoning ON) | xarray-4629 | PASS | 10 | 46,892 | 1,403 | 82 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning ON) | sympy-13480 | PASS | 8 | 21,252 | 764 | 92 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning ON) | sympy-14711 | FAIL | 27 | 105,197 | 4,097 | 180 | LLM_UNAVAILABLE |
| NVIDIA / nemotron-3-ultra (reasoning OFF) | xarray-4629 | PASS | 15 | 65,633 | 1,216 | 99 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning OFF) | sympy-13480 | PASS | 7 | 19,376 | 617 | 42 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning OFF) | sympy-14711 | FAIL | 30 | 131,210 | 2,562 | 132 | MAX_ITERATIONS |
| NVIDIA / nemotron-3-ultra (reasoning ON) | xarray-4629 | PASS | 9 | 34,193 | 1,160 | 82 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning ON) | sympy-13480 | PASS | 6 | 13,774 | 475 | 57 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning ON) | sympy-14711 | PASS* | 30 | 108,468 | 3,991 | 192 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra (reasoning none) | xarray-4629 | PASS | 11 | 54,305 | 1,468 | 85 | final_answer |
| Ollama / nemotron-3-ultra (reasoning none) | sympy-13480 | PASS | 6 | 14,411 | 488 | 39 | final_answer |
| Ollama / nemotron-3-ultra (reasoning none) | sympy-14711 | PASS* | 30 | 110,291 | 2,517 | 175 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra (reasoning medium) | xarray-4629 | PASS | 21 | 124,476 | 2,639 | 220 | final_answer |
| Ollama / nemotron-3-ultra (reasoning medium) | sympy-13480 | PASS* | 30 | 106,696 | 3,702 | 278 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra (reasoning medium) | sympy-14711 | FAIL | 30 | 125,707 | 4,726 | 282 | MAX_ITERATIONS |
| Google / gemini-3.1-flash-lite (reasoning medium) | xarray-4629 | PASS | 3 | 10,093 | 878 | 36 | final_answer |
| Google / gemini-3.1-flash-lite (reasoning medium) | sympy-13480 | PASS | 3 | 9,096 | 670 | 48 | final_answer |
| Google / gemini-3.1-flash-lite (reasoning medium) | sympy-14711 | FAIL | 6 | 27,368 | 2,715 | 115 | final_answer |
| Google / gemini-3.5-flash | xarray-4629 | FAIL | 0 | 2,647 | 0 | 42 | LLM_UNAVAILABLE |
| Google / gemini-3.5-flash | sympy-13480 | FAIL | 0 | 0 | 0 | 10 | LLM_UNAVAILABLE |
| Google / gemini-3.5-flash | sympy-14711 | FAIL | 6 | 22,734 | 496 | 30 | LLM_UNAVAILABLE |

About PASS\*:
  The run stopped at the iteration limit, and the patch the agent recovered at the end (`get_patch()`) passed grading.
  The PASS with `LLM_UNAVAILABLE` (Cohere reasoning none, xarray) is the same: the patch recovered when the responses stopped midway passed.

**Totals over the 3 tasks**:

| Setting | Result | Submitted by itself | Avg. iterations | Avg. input | Avg. output | Avg. seconds |
|---|---|---|---|---|---|---|
| Mistral / codestral-latest | **3/3** | 3 | 4 | 8,122 | 307 | **17** |
| NVIDIA / glm-5.3-flash | **3/3** | 3 | 5 | 15,140 | 716 | 158 |
| Ollama / gpt-oss:120b (low) | **3/3** | 3 | 13 | 42,295 | 1,545 | 29 |
| Cohere / command-a-03-2025 | **3/3** | 3 | 7 | 22,342 | 657 | 104 |
| Kilo / nemotron-3-ultra (OFF) | 3/3 | 2 | 15 | 66,933 | 4,413 | 232 |
| NVIDIA / nemotron-3-ultra (ON) | 3/3 | 2 | 15 | 52,145 | 1,875 | 110 |
| Ollama / nemotron-3-ultra (none) | 3/3 | 2 | 16 | 59,669 | 1,491 | 100 |
| NVIDIA / nemotron-3-ultra (OFF) | 2/3 | 2 | 17 | 72,073 | 1,465 | 91 |
| Kilo / nemotron-3-ultra (ON) | 2/3 | 2 | 15 | 57,780 | 2,088 | 118 |
| Ollama / gpt-oss:120b (medium) | 2/3 | 2 | 13 | 46,762 | 6,451 | 55 |
| Ollama / nemotron-3-ultra (medium) | 2/3 | 1 | 27 | 118,960 | 3,689 | 260 |
| Google / gemini-3.1-flash-lite (medium) | 2/3 | 2 | 4 | 15,519 | 1,421 | 66 |
| Cohere / command-a-reasoning (none) | 2/3 | 1 | 2 | 5,473 | 184 | 17 |
| Cohere / command-a-reasoning (ON) | 0/3 | 0 | - | - | - | - |
| Cohere / command-a-plus | 0/3 | 0 | - | - | - | - |
| Google / gemini-3.5-flash | 0/3 | 0 | - | - | - | - |

## 3. **Provider reliability**
- For each model/provider:
    - Average response time per request
    - Number of retries needed (rate limits, timeouts, errors)
    - Overall availability during benchmark runs

| Setting | Result | Avg. response time per request (s) | Requests | Retries | Failed requests | Success rate | Runs not ended by a provider failure |
|---|---|---|---|---|---|---|---|
| Mistral / codestral-latest | 3/3 | **1.4** | 11 | 0 | 0 | 100% | 3/3 |
| NVIDIA / glm-5.3-flash | 3/3 | 27.3 | 16 | 0 | 0 | 100% | 3/3 |
| Ollama / gpt-oss:120b (low) | 3/3 | **1.2** | 40 | 0 | 0 | 100% | 3/3 |
| Ollama / gpt-oss:120b (medium) | 2/3 | 2.3 | 39 | 0 | 0 | 100% | 3/3 |
| Cohere / command-a-03-2025 | 3/3 | 8.7 | 21 | 1 | 1 | 95% | 3/3 |
| Cohere / command-a-plus-05-2026 | 0/3 | - | 3 | 0 | 3 | 0% | 0/3 |
| Cohere / command-a-reasoning (none) | 2/3 | 2.7 | 9 | 0 | 2 | 78% | 1/3 |
| Cohere / command-a-reasoning (ON) | 0/3 | 10.5 | 5 | 0 | 3 | 40% | 0/3 |
| Kilo / nemotron-3-ultra (OFF) | 3/3 | 12.2 | 47 | 1 | 1 | 98% | 3/3 |
| Kilo / nemotron-3-ultra (ON) | 2/3 | 6.4 | 46 | 0 | 1 | 98% | 2/3 |
| NVIDIA / nemotron-3-ultra (OFF) | 2/3 | 4.2 | 52 | 0 | 0 | 100% | 3/3 |
| NVIDIA / nemotron-3-ultra (ON) | 3/3 | 5.6 | 46 | 1 | 1 | 98% | 3/3 |
| Ollama / nemotron-3-ultra (none) | 3/3 | 4.8 | 47 | 0 | 0 | 100% | 3/3 |
| Ollama / nemotron-3-ultra (medium) | 2/3 | 7.3 | 82 | 1 | 1 | 99% | 3/3 |
| Google / gemini-3.1-flash-lite (medium) | 2/3 | 13.5 | 12 | 0 | 0 | 100% | 3/3 |
| Google / gemini-3.5-flash | 0/3 | 3.0 | 12 | 0 | 6 | 50% | 0/3 |

- **Mistral and Ollama had almost no failed requests** (only one, with Ollama nemotron-3-ultra reasoning medium, and it recovered on retry). Apart from reasoning medium, their responses were also fast, 1.2–4.8 seconds.
- **Cohere differs a lot by model**.
  - command-a had 95% (the one failure recovered on retry).
  - plus and reasoning were almost unusable because of 422.
  - In a trial on 10-30, command-a also started returning 422 partway through some runs.
  - The trial key is limited to 1,000 calls per month.
  - One response takes 8.7 seconds, which is slow. During selection, one response took 93.9 seconds.
- **NVIDIA does not fail, but can be slow**.
  - glm-5.3-flash took 27 seconds per call, nemotron-3-ultra 4–6 seconds. While checking, a single 503 came back with reasoning ON.
- **Kilo** is a gateway with the same interface as OpenRouter.
  - `:free` models disappear from the list without notice (laguna-s disappeared on the day of the measurement).
- **Google**: the daily quota of gemini-3.5-flash is too small. It could not finish the 3 tasks.


## 4. **Intermediary metrics** (at least 2 of the following)
- Step at which the agent first reads/edits the file that appears in the final patch (exploration efficiency)
- Step at which test failures first decrease vs baseline (partial progress)
- Iterations between "tests first pass" and final_answer (submission discipline — zero is ideal)
These metrics can be measured manually by inspecting the **solution.json** files.
Automation is not required. What matters is the analysis, not the tooling.

| Setting | Task | First step that reads a file in the final patch | First step that edits it | Iterations from all tests passing to final_answer |
|---|---|---|---|---|
| Mistral / codestral-latest | xarray-4629 | 2 | 3 | 1 |
| Mistral / codestral-latest | sympy-13480 | 2 | 3 | 0 |
| Mistral / codestral-latest | sympy-14711 | 2 | 4 | 0 |
| NVIDIA / glm-5.3-flash | xarray-4629 | 2 | 3 | 1 |
| NVIDIA / glm-5.3-flash | sympy-13480 | 2 | 3 | 1 |
| NVIDIA / glm-5.3-flash | sympy-14711 | 1 | 3 | 1 |
| Ollama / gpt-oss:120b (low) | xarray-4629 | 12 | 13 | - |
| Ollama / gpt-oss:120b (low) | sympy-13480 | - | 3 | 1 |
| Ollama / gpt-oss:120b (low) | sympy-14711 | 3 | 11 | 3 |
| Ollama / gpt-oss:120b (medium) | sympy-13480 | 4 | 5 | 1 |
| Ollama / gpt-oss:120b (medium) | sympy-14711 | 3 | 5 | 1 |
| Cohere / command-a-03-2025 | xarray-4629 | 2 | 3 | 1 |
| Cohere / command-a-03-2025 | sympy-13480 | 2 | 3 | 1 |
| Cohere / command-a-03-2025 | sympy-14711 | 2 | 7 | 2 |
| Kilo / nemotron-3-ultra (OFF) | xarray-4629 | 1 | 2 | 6 |
| Kilo / nemotron-3-ultra (OFF) | sympy-13480 | 1 | 2 | 3 |
| Kilo / nemotron-3-ultra (OFF) | sympy-14711 | 2 | 27 | - |
| Kilo / nemotron-3-ultra (ON) | xarray-4629 | 3 | 5 | 3 |
| Kilo / nemotron-3-ultra (ON) | sympy-13480 | 2 | 3 | 2 |
| NVIDIA / nemotron-3-ultra (OFF) | xarray-4629 | 4 | 11 | 2 |
| NVIDIA / nemotron-3-ultra (OFF) | sympy-13480 | 1 | 2 | 3 |
| NVIDIA / nemotron-3-ultra (ON) | xarray-4629 | 2 | 4 | 3 |
| NVIDIA / nemotron-3-ultra (ON) | sympy-13480 | 2 | 3 | 1 |
| NVIDIA / nemotron-3-ultra (ON) | sympy-14711 | 2 | 22 | - |
| Ollama / nemotron-3-ultra (none) | xarray-4629 | 2 | 4 | 5 |
| Ollama / nemotron-3-ultra (none) | sympy-13480 | 1 | 2 | 2 |
| Ollama / nemotron-3-ultra (none) | sympy-14711 | 2 | 15 | - |
| Ollama / nemotron-3-ultra (medium) | xarray-4629 | 3 | 5 | 14 |
| Ollama / nemotron-3-ultra (medium) | sympy-13480 | 2 | 4 | - |
| Google / gemini-3.1-flash-lite (medium) | xarray-4629 | 1 | 1 | - |
| Google / gemini-3.1-flash-lite (medium) | sympy-13480 | 1 | 1 | - |
| Google / gemini-3.1-flash-lite (medium) | sympy-14711 | 1 | 5 | - |

- Runs that produced no patch (such as runs stopped by 422) are left out.
- What `-` means:
  - `-` under "reads": the run looked at the contents with `run_command` (`sed -n`, `cat`) or `search_code` instead of `read_file`.
  - `-` in the last column: the run ended without ever seeing `run_tests()` pass completely. Some of these submitted without running the tests, and some stopped at the iteration limit.

**Exploration efficiency**:

- Of the top 4 settings that passed all 3 tasks, the 3 other than gpt-oss:120b (low) read the right file at step 1–2 and edited it at step 3–4 (7 for Cohere on 14711). The task text names the function to fix, so strong models go straight there.
- The difference showed up on 14711. nemotron-3-ultra read the right file by step 2 with every provider. Even so, its first edit came at step 15, 22 and 27. It had read the file, but could not settle on how to fix it and kept checking again and again.
- gpt-oss:120b (low) on xarray first read the file of the final patch (`merge.py`) at step 12. Until then, it was searching around it with `search_code` and `run_command`.

**Submission discipline**:

- codestral scored **0** on 14711 and 13480 (it ran the tests and, once they passed, called `final_answer(get_patch())` in the same step). On xarray it scored 1.
- Cohere command-a and glm-5.3-flash were mostly 1 (they read the result before submitting).
- nemotron-3-ultra kept checking for 1–6 more iterations after the tests passed, and 14 with reasoning medium.
- In SWE, when 4 iterations are left, the agent tells the model to "stop searching and submit" (`[BUDGET]`, `iteration_warn_at=4`). Even so, some runs hit the iteration limit.
- gemini-3.1-flash-lite submitted all 3 tasks without ever seeing `run_tests()` pass completely (the column is `-`). On 14711, it failed the hidden tests because of that.


## 5. Ablation study
- At least one before/after comparison of a change to the agent (prompt, tools, parameters), with the same model on the same tasks

### 5.1 Reasoning strength (parameter): same model, same 3 tasks

Only the reasoning setting of the request (`model_params`) was changed.

| Model | Weak / OFF | Strong / ON | Difference |
|---|---|---|---|
| Ollama gpt-oss:120b (low → medium) | 3/3, avg. 13 iterations, output 1,545, 29 s | **2/3**, 13 iterations, output **6,451**, 55 s | medium quadrupled the output, hit the 10,000 limit on xarray and FAILED |
| Ollama nemotron-3-ultra (none → medium) | 3/3, 16 iterations, input 59,669, 100 s | **2/3**, **27 iterations**, input **118,960**, 260 s | About twice the iterations and input. 2 tasks hit the iteration limit |
| NVIDIA nemotron-3-ultra (OFF → ON) | 2/3, 17 iterations, input 72,073 | 3/3, 15 iterations, input 52,145 | ON slightly better, but its PASS on 14711 was a recovered patch |
| Kilo nemotron-3-ultra (OFF → ON) | 3/3, 15 iterations, output 4,413 | 2/3, 15 iterations, output 2,088 | OFF slightly better. With ON, 14711 failed when the responses stopped |
| Cohere command-a-reasoning (none → ON) | 2/3 | 0/3 | ON unusable because of 422 |

**What we learned**:

- **Stronger reasoning did not increase passes**. Of the 5 comparisons, the stronger side was better only for NVIDIA, and even that was a PASS with a recovered patch.
- **The output limit (10,000) is tight for reasoning**:
  - SWE calls the model 10–30 times per task, so each call can use 330–1,000 output tokens.
  - gpt-oss medium used about 500 tokens per call on average, and hit the limit at 17 iterations on xarray.
  - This matches the subject PDF VI.1.2: "If your chosen model's reasoning tokens make limits tight, consider using a non-reasoning model."
- **Reasoning can also increase the iterations** (ollama ultra: 16 → 27). The more it thought, the more it also tried.
- The reasoning model that did well was glm-5.3-flash (3/3, 5 iterations on average). It thinks within one call and settles in few iterations, but it is slow at 27 seconds per call.
- **Note**: every result here is a single run (n=1). Even with the same setting, the number of iterations varies a lot (codestral on 14711: 4 iterations in #2, 21 and 6 in #7).

- Other simple comparisons we made:
  - Measuring all 6 tasks with cohere first vs. codestral first
    - Excluded, because the models are not the same.
  - Measuring only 14711, 9 times each, with the top 5 candidates
    - Every model had a high pass rate on the tasks other than 14711, but this one ran to 30 iterations and varied (e.g. recovered patches), so we measured it as the main task (NVIDIA glm and Ollama gpt with reasoning low / medium got 9/9). Excluded, because the models are not the same.
  - Prompt, submission checks, Observation improvements, shorter prompts, sending 1 turn of history instead of 2 to save tokens, provider order
    - Excluded, because they were done during the MBPP measurements.


## 6. Conclusion
- Which model(s) were selected for the final pipeline, and why.
- Which models can be ignored, and why. Write it based on the data.

- The supporting solution.json files must be included in the repository.

**How we decided**: we put the pass rate before speed. We used these 3 stages:

1. Narrow the candidates from 16 settings with 3 easy tasks (#2)
2. Run 14711, where the difference showed, 9 times each (#5)
3. Run 6 tasks × 3 rounds with the 3 models that got 9/9 (#7)

**Production order for SWE-bench** (`providers/providers_swebench.json`)

1. **Ollama `gpt-oss:120b` (reasoning low)** → `nemotron-3-ultra` (reasoning none) on the same Ollama
   - **18/18** on 6 tasks × 3 rounds as the only model, and **9/9** on 14711.
   - It submitted by itself all 18 times and never hit a limit.
   - It is also among the fastest: 32 seconds per task and 1.2 seconds per call on average.
   - `nemotron-3-ultra` is a backup on the same provider for when gpt-oss does not respond.
2. **NVIDIA `glm-5.3-flash`** → `nemotron-3-ultra` (reasoning ON)
   - 17/18 (the one failure was a network error), and 9/9 on 14711.
   - It is slow at 27 seconds per call, so it is second.
   - We chose a different provider from the first one so that, when the agent switches after repeated identical code, the task goes to a model that makes different mistakes.
3. **Mistral `codestral-latest`**
   - Fast with a large quota, but 3/9 on 14711 and 1/4 on scikit-learn. It sometimes submits a wrong patch with confidence, so it is third.
4. Google `gemini-3.1-flash-lite` (reasoning medium): 2/3 on the 3 tasks, 6/9 on 14711.
5. Kilo `nemotron-3-ultra:free` (reasoning OFF): `:free` models can disappear, so it is near the end.
6. Cohere `command-a-03-2025`
   - It got 3/3 on the 3 tasks. However, the trial key is limited to 1,000 calls per month, and we reached that limit during the measurements.
   - Each response is also slow, so it is the last safety net.

- Check: with this order's file, 6 tasks × 2 rounds gave **12/12** (#7).
- In the end, the runs using Ollama `gpt-oss:120b` (as the only model or first in the order) totaled 30/30, and 9/9 on 14711.

**Summary of the orders compared** (6 tasks):

| Order (first model) | Result |
|---|---|
| cohere command-a (the previous production order; in practice nemotron-ultra) | 15/18 (0/3 on 14711) |
| codestral | 19/24 (5/9 on 14711, 1/4 on scikit-learn) |
| **gpt-oss:120b (low) alone** | **18/18** |

**Not used**:

| Model | Reason |
|---|---|
| Cohere command-a-plus, command-a-reasoning (reasoning ON) | 422 every time |
| Google gemini-3.5-flash | The daily quota is small; it could not finish the 3 tasks |
| Stronger reasoning settings (gpt-oss medium, nemotron medium) | No more passes, more output and iterations. gpt-oss hit the output limit |
| Groq | With 8,000 tokens per minute, one SWE run does not fit in 900 seconds |
| minimax, deepseek (NVIDIA) | 80–100 seconds per response |

**What the data tells us**:

- Within SWE's limits (10,000 output tokens), **stronger reasoning did not increase passes**. With the same gpt-oss:120b, low got 18/18 and medium 16/18.
- **A single run can misjudge a model's strength**.
  - codestral passed 14711 in its one selection run, but got 3/9 over 9 runs.
  - We used the 3-task selection (n=1) only to narrow the candidates, and made the final decision with repeated runs.
- Easy tasks (13480, django, etc.) are solved by every top model. Differences between orders show up on tasks where models easily get lost, such as 14711 and scikit-learn.
- Submitting early is not always good. codestral submits after few iterations, but when it submits a wrong patch, the run ends there. Fallback cannot save it.


## 7. Check with the production settings (all 6 tasks)

- We ran the 6 candidate exam tasks of the moulinette (`EXAM_POOL`) with production orders (with fallback).

| Order | Rounds | Result |
|---|---|---|
| codestral first (mistral → ollama → nvidia → cohere → kilo → gemini) | 4 rounds (r1–r4) | 6, 5, 4, 4 → **19/24 (79%)** |
| cohere first (the previous `providers_swebench.json`; cohere ran out of quota partway through round 1, so nemotron-3-ultra was first in practice) | 3 rounds (r1–r3) | 5, 5, 5 → **15/18 (83%)** |
| The top 3 models (9/9 on 14711), each as the only model × 6 tasks × 3 rounds | table below | gpt-oss low **18/18**, glm 17/18, gpt-oss medium 16/18 |
| **Final order (gpt-oss first; #6)** | 2 rounds (11-02 07:12–07:26) | **12/12** (avg. 9.5 iterations, about 30,500 input, about 1,260 output, 35 s). Only gpt-oss:120b answered, except one xarray run that switched to glm-5.3-flash partway and passed |

**Top 3 models × 6 tasks × 3 rounds (single model, no fallback, 11-02)**:

| Task | gpt-oss:120b (low) | glm-5.3-flash | gpt-oss:120b (medium) |
|---|---|---|---|
| django-11066 | 3/3 (5–7 iterations, 15–25 s) | 3/3 (4–5, 17–46 s) | 3/3 (5–18, 16–36 s) |
| xarray-4629 | 3/3 (7–8, 20–22 s) | 3/3 (4–6, 52–66 s) | 3/3 (4–7, 17–31 s) |
| scikit-learn-13439 | 3/3 (7–9, 22–24 s) | 3/3 (5–10, 44–93 s) | 2/3 (one FAIL at the iteration limit, one PASS with the patch recovered at the limit) |
| sympy-13480 | 3/3 (3–6, 31–40 s) | 3/3 (4–5, 43–270 s) | 3/3 (4–9, 11–55 s) |
| sympy-14711 | 3/3 (7–10, 19–42 s) | 2/3 (in one run the responses stopped because of a network error at NVIDIA [TransportError]) | 2/3 (hit the 10,000 output limit twice; one of them passed with the recovered patch) |
| sympy-18189 | 3/3 (3–11, 59–61 s) | 3/3 (4–5, 59–111 s) | 3/3 (5–28, 51–195 s) |
| **Total** | **18/18** | **17/18** | **16/18** |
| Average (per task) | 7 iterations, about 21,000 input, about 740 output, 32 s | 6 iterations, about 21,000 input, about 1,240 output, 105 s | 14 iterations, about 49,000 input, about 4,030 output, 51 s |

- **gpt-oss:120b (low) passed all 18 runs by calling `final_answer` itself**. It never hit the iteration limit or the output limit.
- With the same gpt-oss:120b, reasoning medium roughly doubles the iterations and multiplies the output by about 5. It hit the output limit (10,000) or the iteration limit (30) and failed twice (the same trend as #5).
- glm-5.3-flash solved every task as a model. The one failure was a run whose responses stopped because of a network error in NVIDIA's API. It is slow, at 105 seconds per task on average.

**Per task (number of PASSes)**:

| Task | codestral first (4 rounds) | cohere first = nemotron-ultra in practice (3 rounds) |
|---|---|---|
| django-11066 | 4/4 | 3/3 |
| xarray-4629 | 3/4 (r4 hit the output limit) | 3/3 |
| scikit-learn-13439 | 1/4 | 3/3 |
| sympy-13480 | 4/4 | 3/3 |
| sympy-14711 | 3/4 (5/9 including 5 extra runs of 14711 only) | 0/3 |
| sympy-18189 | 4/4 | 3/3 |

- **Weak points of the codestral-first order**:
  - scikit-learn (1/4): in 2 runs it submitted a wrong patch after 3–4 iterations, and in 1 run it kept failing `edit_file` and hit the output limit.
  - 14711 (5/9): some runs submitted a wrong patch, and some hit the output limit.
  - codestral submits early (fast and cheap), but it sometimes makes mistakes with confidence. Once it submits a wrong patch, the run ends there, so it loses before the fallback can work.
- **With nemotron-ultra first**, every task except 14711 passed (15/15). However, on 14711 all 3 runs stopped at the 30-iteration limit.

**r1 and r2 of the codestral-first order**:

| Task | r1 | r2 |
|---|---|---|
| sympy-14711 | PASS (21 iterations, 57 s; codestral 7 times → switched on repeated identical code → gpt-oss 14 times) | PASS (6, 37 s) |
| sympy-13480 | PASS (4, 23 s) | PASS (4, 29 s) |
| xarray-4629 | PASS (4, 15 s) | PASS (4, 15 s) |
| django-11066 | PASS (4, 17 s) | PASS (4, 19 s) |
| scikit-learn-13439 | PASS (5, 28 s) | **FAIL** (output limit) |
| sympy-18189 | PASS (4, 57 s) | PASS (3, 54 s) |

- The scikit-learn FAIL in r2:
  - codestral could not match the string to replace in `edit_file`, and 6 times answered by copying out the whole method (up to the 1,200-token limit per call).
  - Each copy was slightly different, so "switch after the same code twice in a row" did not kick in right away.
  - By the time it switched to gpt-oss, almost no output budget was left.
  - This is a candidate improvement on the agent side (not included this time).

## 8. About MBPP

- Results of running every task in the exam's range (the 257 tasks of the test split):
  - 10-30 (a team member, the previous production order): 233/257 (90.7%)
  - 11-01 (order B): 224/257 (87.2%)
  - 11-02 (A and C alternating task by task): A 234 (91.1%), C **237** (92.2%) → **production uses C**
- The exam requires 4 of 5 tasks, so with a per-task success rate of 0.92, the chance of passing is about 95%.

## 9. Where the data is

We put 201 runs in `benchmark/swebench/` (about 39MB).

- Each run has these 6 files:
  - `solution.json`
  - `task.json`
  - `validate.log` (the full grading output)
  - `validate_summary.txt` (only the verdict lines from `validate.log`)
  - `agent_stdout.log`, `agent_stderr.log` (the agent's standard output and standard error)
- Each setting also has the `providers.json` used for its runs.

| Folder | Contents | Section of this document |
|---|---|---|
| `selection_easy3/<setting>/r1/<task>/` | 3 easy tasks × 16 settings | #2–#5 |
| `task14711_repeats/<setting>/r<n>/sympy__sympy-14711/` | Extra runs of 14711 only (r2–r9; r5–r9 for the planned production order) | #5 |
| `top3_6tasks/<setting>/r<n>/<task>/` | Top 3 models × 6 tasks × 3 rounds | #7 |
| `production_codestral_first/swe_final/r<n>/<task>/` | codestral-first order × 6 tasks × 4 rounds | #7 |
| `production_cohere_first/swe_cohere/r<n>/<task>/` | cohere-first order × 6 tasks × 3 rounds | #7 |
| `production_final/swe_final2/r<n>/<task>/` | Final order × 6 tasks × 2 rounds | #7 |

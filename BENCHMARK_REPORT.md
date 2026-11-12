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
8. [Statistics and cost](#8-statistics-and-cost)
9. [Reproducibility and limitations](#9-reproducibility-and-limitations)
10. [About MBPP](#10-about-mbpp)
11. [Where the data is](#11-where-the-data-is)

## 0. **Introduction**
- **What we compared**:
- The subject requires comparing at least 5 models across at least 2 providers on at least 3 SWE-bench tasks.
- As the tasks to compare first, we chose the three that the subject PDF lists as simple tasks to try first: `sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629`.
- We compared 16 settings of 11 models from 6 providers. The same model with reasoning ON and OFF counts as two different settings.
- Each setting was run with a single model only (no backoff or fallback to other models or providers).
- The time and token limits are the same as the real ones.
- The top models, the ablations and the production order were then run on all 6 candidate exam tasks (`EXAM_POOL`), several times each.

- **7 settings passed all 3 tasks**. Four of them passed by submitting with `final_answer` themselves:
    - Mistral codestral
    - NVIDIA glm-5.3-flash
    - Ollama gpt-oss:120b (reasoning low)
    - Cohere command-a
- The other three each passed one task (14711) with the patch recovered from their work so far (`get_patch()`) when they stopped at the iteration limit (30).

- **Ablations** (#5): one parameter and two changes to the agent, each with the same model on the same tasks.
  - Stronger reasoning did not raise the score (#5.1). It multiplied the output by about 5 (17 of 18 pairs, p≈0.0001), and gpt-oss:120b hit the output limit (10,000).
  - Reading "glued" code fences correctly (#5.2, tool) cut syntax errors from 26 to 1 on the 6 tasks.
  - Submitting in the same step as the passing test (#5.3, prompt + tool) cut the gap between "tests first pass" and `final_answer` from 1.18 to 0.08 (10 of 10 pairs, p=0.002), and the iterations of glm-5.3-flash from 6.50 to 4.58, without losing any PASS (24/24).

- **Production order (changed on 11-12)**
    **NVIDIA glm-5.3-flash goes first, and the same gpt-oss-120b as before, on Cloudflare, goes second.**
  - Until 11-09, Ollama gpt-oss:120b (reasoning low) was first: 18/18 on 6 tasks × 3 rounds as the only model, 9/9 on 14711.
  - On 11-09, Ollama Cloud's free plan switched to pay-as-you-go, and gpt-oss:120b and nemotron-3-ultra now need credits. The subject allows free tiers only, so we removed Ollama from both orders (SWE and MBPP). Its measurements stay in this report as data.
  - glm-5.3-flash: 17/18 on 6 tasks × 3 rounds (the one failure was a network error at NVIDIA), 24/24 in the ablation runs on 11-11, and 6/6 with the new production order (#7).
  - gpt-oss-120b on Cloudflare: 13/13 on 11-11. It is second because its free daily quota covers only about 13 SWE runs.

- **Not used**:
  - Ollama Cloud: no longer free (pay-as-you-go since 11-09).
  - Cohere command-a-plus and command-a-reasoning (reasoning ON): HTTP 422 every time.
  - Gemini 3.5-flash: the daily quota was too small.
  - Groq: its quota of 8,000 tokens per minute is smaller than the input of a single SWE call, and its gpt-oss-120b returned an empty body on the first call (2 of 2 tries).

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
- The agent was improved between measurement days, so the code differs between data folders. Within one comparison, only one thing changes. The code of each folder is listed in #9.

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
|Cloudflare| The daily quota (10,000 neurons) ran out in about 40 minutes even in the MBPP measurement. **Measured on SWE later (11-11, #5.3) and now second in the production order** |

**Changes after the first selection (11-09 to 11-12)**:

- Ollama Cloud's free plan switched to pay-as-you-go on 2026-11-09. gpt-oss:120b, gpt-oss:20b, nemotron-3-super, nemotron-3-ultra and gemma4:31b now need credits. We no longer use Ollama. The Ollama rows in this report were measured before that date.
- We looked for the same gpt-oss-120b at other free providers. Cloudflare Workers AI (`@cf/openai/gpt-oss-120b`) and Groq (`openai/gpt-oss-120b`) have it for free. Kilo has it only as a paid model, and NVIDIA has only gpt-oss-20b.
  - Cloudflare worked on SWE: 13/13 on 11-11 (#5.3).
  - Groq returned an empty body on the first call in both of 2 tries, so the run stopped at step 0 (`LLM_UNAVAILABLE`).
- **The same model can behave differently on different providers.** Providers differ in how they convert gpt-oss's output format into an OpenAI-compatible response, how they handle `reasoning_effort` and stop sequences, quantization, and quotas. In the MBPP selection, the same gpt-oss-120b scored 6.5 (Ollama), 6.5 (Cloudflare) and 5.3 (Groq) on the hard 10 tasks, with 0, 0 and 5 empty responses in 20 runs. So we did not reuse Ollama's numbers for Cloudflare; we measured it again.

### 1.3 Tasks

We used two sets of tasks.

**3 tasks for all 16 settings** (#2–#5.1): `sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629`, for these reasons:

- The subject PDF lists `sympy__sympy-14711`, `sympy__sympy-13480` and `pydata__xarray-4629` as simple tasks to try first.
- All three are among the moulinette's candidate exam tasks (the 6 tasks of `EXAM_POOL`).
- 14711 is the task that separated the models most; many models used all 30 iterations on it.

**6 tasks for the top models, the ablations #5.2–#5.3 and the production check #7**: all 6 tasks of `EXAM_POOL`. The exam picks 3 of them, so these are the tasks the agent is graded on.

| Task | Test runner | Tests failing on the original code (baseline) | Used in |
|---|---|---|---|
| django__django-11066 | `tests/runtests.py` | 1 (`test_existing_content_type_rename_other_database`) | 6 tasks |
| pydata__xarray-4629 | pytest | 1 (`test_merge_attrs_override_copy`) | 3 and 6 tasks |
| scikit-learn__scikit-learn-13439 | pytest | 1 (`test_make_pipeline_memory`) | 6 tasks |
| sympy__sympy-13480 | `bin/test` | 1 (`test_coth`) | 3 and 6 tasks |
| sympy__sympy-14711 | `bin/test` | 1 (`test_Vector`) | 3 and 6 tasks |
| sympy__sympy-18189 | `bin/test` | 1 (`test_diophantine`) | 6 tasks |

- We measured the baseline without the LLM: the task's grading script (`eval_script`) run on the original code in the task's Docker image (`benchmark/swebench/baseline_original_code/<task>.log`).
- In every task, the failing test is the one listed in the dataset's `FAIL_TO_PASS`.
- All 6 tasks have exactly one failing test. This matters for one of the metrics in #4.

## 2. **Results table**
- For each model × task combination:
    - Pass/Fail
    - Iterations used
    - Total input tokens
    - Total output tokens
    - Wall-clock time

| Setting | Task | Result | Iterations | Input tokens | Output tokens | Time (s) | Stop reason |
|---|---|---|---|---|---|---|---|
| Mistral / codestral-latest | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/mistral_codestral/r1/pydata__xarray-4629/solution.json) | 4 | 11,288 | 244 | 15 | final_answer |
| Mistral / codestral-latest | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/mistral_codestral/r1/sympy__sympy-13480/solution.json) | 3 | 5,331 | 222 | 19 | final_answer |
| Mistral / codestral-latest | sympy-14711 | [PASS](benchmark/swebench/selection_easy3/mistral_codestral/r1/sympy__sympy-14711/solution.json) | 4 | 7,747 | 454 | 18 | final_answer |
| NVIDIA / glm-5.3-flash (reasoning) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/nvidia_glm53_flash/r1/pydata__xarray-4629/solution.json) | 6 | 18,759 | 592 | 232 | final_answer |
| NVIDIA / glm-5.3-flash (reasoning) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/nvidia_glm53_flash/r1/sympy__sympy-13480/solution.json) | 5 | 11,710 | 536 | 168 | final_answer |
| NVIDIA / glm-5.3-flash (reasoning) | sympy-14711 | [PASS](benchmark/swebench/selection_easy3/nvidia_glm53_flash/r1/sympy__sympy-14711/solution.json) | 5 | 14,950 | 1,021 | 75 | final_answer |
| Ollama / gpt-oss:120b (reasoning low) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/ollama_gptoss120_low/r1/pydata__xarray-4629/solution.json) | 14 | 50,148 | 1,106 | 26 | final_answer |
| Ollama / gpt-oss:120b (reasoning low) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/ollama_gptoss120_low/r1/sympy__sympy-13480/solution.json) | 6 | 11,567 | 352 | 23 | final_answer |
| Ollama / gpt-oss:120b (reasoning low) | sympy-14711 | [PASS](benchmark/swebench/selection_easy3/ollama_gptoss120_low/r1/sympy__sympy-14711/solution.json) | 20 | 65,169 | 3,178 | 39 | final_answer |
| Ollama / gpt-oss:120b (reasoning medium) | xarray-4629 | [FAIL](benchmark/swebench/selection_easy3/ollama_gptoss120_medium/r1/pydata__xarray-4629/solution.json) | 17 | 65,782 | 10,000 | 55 | MAX_OUTPUT_TOKENS |
| Ollama / gpt-oss:120b (reasoning medium) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/ollama_gptoss120_medium/r1/sympy__sympy-13480/solution.json) | 9 | 27,311 | 3,371 | 41 | final_answer |
| Ollama / gpt-oss:120b (reasoning medium) | sympy-14711 | [PASS](benchmark/swebench/selection_easy3/ollama_gptoss120_medium/r1/sympy__sympy-14711/solution.json) | 13 | 47,192 | 5,982 | 68 | final_answer |
| Cohere / command-a-03-2025 | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/cohere_command_a/r1/pydata__xarray-4629/solution.json) | 6 | 25,934 | 529 | 88 | final_answer |
| Cohere / command-a-03-2025 | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/cohere_command_a/r1/sympy__sympy-13480/solution.json) | 5 | 13,817 | 443 | 56 | final_answer |
| Cohere / command-a-03-2025 | sympy-14711 | [PASS](benchmark/swebench/selection_easy3/cohere_command_a/r1/sympy__sympy-14711/solution.json) | 9 | 27,276 | 1,000 | 168 | final_answer |
| Cohere / command-a-plus-05-2026 | xarray-4629 | [FAIL](benchmark/swebench/selection_easy3/cohere_command_a_plus/r1/pydata__xarray-4629/solution.json) | 0 | 0 | 0 | 4 | LLM_UNAVAILABLE |
| Cohere / command-a-plus-05-2026 | sympy-13480 | [FAIL](benchmark/swebench/selection_easy3/cohere_command_a_plus/r1/sympy__sympy-13480/solution.json) | 0 | 0 | 0 | 7 | LLM_UNAVAILABLE |
| Cohere / command-a-plus-05-2026 | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/cohere_command_a_plus/r1/sympy__sympy-14711/solution.json) | 0 | 0 | 0 | 10 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning none) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/cohere_reasoning_off/r1/pydata__xarray-4629/solution.json) | 2 | 5,611 | 300 | 9 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning none) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/cohere_reasoning_off/r1/sympy__sympy-13480/solution.json) | 4 | 8,877 | 188 | 27 | final_answer |
| Cohere / command-a-reasoning (reasoning none) | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/cohere_reasoning_off/r1/sympy__sympy-14711/solution.json) | 1 | 1,930 | 64 | 15 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning ON) | xarray-4629 | [FAIL](benchmark/swebench/selection_easy3/cohere_reasoning_on/r1/pydata__xarray-4629/solution.json) | 1 | 2,654 | 534 | 15 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning ON) | sympy-13480 | [FAIL](benchmark/swebench/selection_easy3/cohere_reasoning_on/r1/sympy__sympy-13480/solution.json) | 0 | 0 | 0 | 6 | LLM_UNAVAILABLE |
| Cohere / command-a-reasoning (reasoning ON) | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/cohere_reasoning_on/r1/sympy__sympy-14711/solution.json) | 1 | 1,930 | 1,199 | 15 | LLM_UNAVAILABLE |
| Kilo / nemotron-3-ultra:free (reasoning OFF) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/kilo_ultra_off/r1/pydata__xarray-4629/solution.json) | 9 | 58,964 | 9,423 | 425 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning OFF) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/kilo_ultra_off/r1/sympy__sympy-13480/solution.json) | 7 | 19,104 | 572 | 36 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning OFF) | sympy-14711 | [PASS\*](benchmark/swebench/selection_easy3/kilo_ultra_off/r1/sympy__sympy-14711/solution.json) | 30 | 122,730 | 3,245 | 235 | MAX_ITERATIONS |
| Kilo / nemotron-3-ultra:free (reasoning ON) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/kilo_ultra_on/r1/pydata__xarray-4629/solution.json) | 10 | 46,892 | 1,403 | 82 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning ON) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/kilo_ultra_on/r1/sympy__sympy-13480/solution.json) | 8 | 21,252 | 764 | 92 | final_answer |
| Kilo / nemotron-3-ultra:free (reasoning ON) | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/kilo_ultra_on/r1/sympy__sympy-14711/solution.json) | 27 | 105,197 | 4,097 | 180 | LLM_UNAVAILABLE |
| NVIDIA / nemotron-3-ultra (reasoning OFF) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/nvidia_ultra_off/r1/pydata__xarray-4629/solution.json) | 15 | 65,633 | 1,216 | 99 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning OFF) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/nvidia_ultra_off/r1/sympy__sympy-13480/solution.json) | 7 | 19,376 | 617 | 42 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning OFF) | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/nvidia_ultra_off/r1/sympy__sympy-14711/solution.json) | 30 | 131,210 | 2,562 | 132 | MAX_ITERATIONS |
| NVIDIA / nemotron-3-ultra (reasoning ON) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/nvidia_ultra_on/r1/pydata__xarray-4629/solution.json) | 9 | 34,193 | 1,160 | 82 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning ON) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/nvidia_ultra_on/r1/sympy__sympy-13480/solution.json) | 6 | 13,774 | 475 | 57 | final_answer |
| NVIDIA / nemotron-3-ultra (reasoning ON) | sympy-14711 | [PASS\*](benchmark/swebench/selection_easy3/nvidia_ultra_on/r1/sympy__sympy-14711/solution.json) | 30 | 108,468 | 3,991 | 192 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra (reasoning none) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/ollama_ultra_none/r1/pydata__xarray-4629/solution.json) | 11 | 54,305 | 1,468 | 85 | final_answer |
| Ollama / nemotron-3-ultra (reasoning none) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/ollama_ultra_none/r1/sympy__sympy-13480/solution.json) | 6 | 14,411 | 488 | 39 | final_answer |
| Ollama / nemotron-3-ultra (reasoning none) | sympy-14711 | [PASS\*](benchmark/swebench/selection_easy3/ollama_ultra_none/r1/sympy__sympy-14711/solution.json) | 30 | 110,291 | 2,517 | 175 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra (reasoning medium) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/ollama_ultra_medium/r1/pydata__xarray-4629/solution.json) | 21 | 124,476 | 2,639 | 220 | final_answer |
| Ollama / nemotron-3-ultra (reasoning medium) | sympy-13480 | [PASS\*](benchmark/swebench/selection_easy3/ollama_ultra_medium/r1/sympy__sympy-13480/solution.json) | 30 | 106,696 | 3,702 | 278 | MAX_ITERATIONS |
| Ollama / nemotron-3-ultra (reasoning medium) | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/ollama_ultra_medium/r1/sympy__sympy-14711/solution.json) | 30 | 125,707 | 4,726 | 282 | MAX_ITERATIONS |
| Google / gemini-3.1-flash-lite (reasoning medium) | xarray-4629 | [PASS](benchmark/swebench/selection_easy3/gemini_31lite_medium/r1/pydata__xarray-4629/solution.json) | 3 | 10,093 | 878 | 36 | final_answer |
| Google / gemini-3.1-flash-lite (reasoning medium) | sympy-13480 | [PASS](benchmark/swebench/selection_easy3/gemini_31lite_medium/r1/sympy__sympy-13480/solution.json) | 3 | 9,096 | 670 | 48 | final_answer |
| Google / gemini-3.1-flash-lite (reasoning medium) | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/gemini_31lite_medium/r1/sympy__sympy-14711/solution.json) | 6 | 27,368 | 2,715 | 115 | final_answer |
| Google / gemini-3.5-flash | xarray-4629 | [FAIL](benchmark/swebench/selection_easy3/gemini_35flash/r1/pydata__xarray-4629/solution.json) | 0 | 2,647 | 0 | 42 | LLM_UNAVAILABLE |
| Google / gemini-3.5-flash | sympy-13480 | [FAIL](benchmark/swebench/selection_easy3/gemini_35flash/r1/sympy__sympy-13480/solution.json) | 0 | 0 | 0 | 10 | LLM_UNAVAILABLE |
| Google / gemini-3.5-flash | sympy-14711 | [FAIL](benchmark/swebench/selection_easy3/gemini_35flash/r1/sympy__sympy-14711/solution.json) | 6 | 22,734 | 496 | 30 | LLM_UNAVAILABLE |

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

- How we count (from `solution.json`):
  - Requests: `total_requests`. Failed requests: requests that did not become a step (`total_requests` − the number of steps). Success rate: steps / requests.
  - Retries: the sum of `retries` over the steps.
  - Availability: the runs that were not ended by the provider (`error` is not `LLM_UNAVAILABLE`), in the last column.

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

**Providers of the current production order (6 tasks)**:

| Setting | Data | Result | Avg. response time per request (s) | Requests | Retries | Failed requests | Success rate | Runs not ended by a provider failure |
|---|---|---|---|---|---|---|---|---|
| NVIDIA / glm-5.3-flash | #7, 6 tasks × 3 rounds (11-02) | 17/18 | 10.6 | 117 | 3 | 6 | 95% | 17/18 |
| NVIDIA / glm-5.3-flash | #5.3, A and B, 6 tasks × 2 rounds (11-11) | 24/24 | 13.0 | 135 | 2 | 2 | 99% | 24/24 |
| Cloudflare / gpt-oss-120b (low) | #5.3, A and B (11-11) | 13/13 | 5.4 | 90 | 0 | 0 | 100% | 13/13 |
| Groq / gpt-oss-120b (low) | trial, 2 runs (11-11) | 0/2 | - | 2 | 0 | 2 | 0% | 0/2 |
| Current production order (glm first) | #7, 6 tasks × 1 round (11-12) | 6/6 | 30.7 | 33 | 4 | 4 | 88% | 6/6 |

- **NVIDIA glm-5.3-flash** is slow but steady. A response took 10–13 seconds on 11-02 and 11-11, but 27 seconds on 11-01 and 31 seconds on 11-12. The response time of a free endpoint changes from day to day. The one run it lost (11-02) was a network error at NVIDIA (`TransportError`). On 11-12, 4 requests hit the same error, and all of them succeeded on retry (2 runs × 2 retries).
- **Cloudflare**: no failed request in 13 runs, 5.4 seconds per call. But the 14th SWE run of the day got HTTP 429: the free daily quota (10,000 neurons, reset at 00:00 UTC) covers about 13 SWE runs. That is enough for the exam (3 tasks), but not for running every benchmark with it first.
  - Cloudflare's gpt-oss-120b sometimes answered without a code block (13 steps in 7 runs before the change of #5.3, 6 steps in 6 runs after). Such a step runs nothing and only uses an iteration. glm did this once in 24 runs.
- **Groq's gpt-oss-120b** returned an empty body (42 and 70 output tokens, no text) on the first call. The agent treats an empty body as a miss and moves to the next model; with Groq as the only provider, the run stopped there.


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

**Third metric: the step at which test failures first decrease vs. the baseline**:

- Baseline: the number of tests failing on the original code (#1.3). It is 1 for all 6 tasks.
- We read the counts from the output of each `run_tests()` step: the summary line of pytest, sympy `bin/test` or Django `runtests.py`, and, from 11-11, the verdict line `RESULT: …` (#5.3).
- With a baseline of 1, "fewer failures than the baseline" means 0 failures, that is, "all tests pass". So on these tasks this metric always equals the step at which all tests first pass. We checked this on the 213 runs we had on 11-10: in every run, the two steps were the same.
- **Insight**: this metric shows partial progress only on tasks with 2 or more failing tests. On the exam's 6 tasks it cannot separate models. A 7th task with several failing tests would be needed to use it (not done).

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

**The gap over all runs** (the 148 of 213 runs where it can be measured, 11-10):

| Gap (iterations from all tests passing to `final_answer`) | 0 | 1 | 2 | 3 | 4–6 | 14, 16 |
|---|---|---|---|---|---|---|
| Runs | 14 | **98** | 18 | 9 | 6 | 3 |

- **Insight**: 66% of the runs had a gap of exactly 1. The cause was not the models but our few-shot example, which showed "run the tests, read the result in the next step, then submit". The models copied it. codestral, which often wrote `final_answer(get_patch())` in the same step as the tests, had 8 of the 14 runs with gap 0.
- This led to the change measured in #5.3: the tool prints a verdict line, and the example submits in the same step when it says PASSED. With it, the gap became 0 in 11 of 12 runs of glm-5.3-flash.


## 5. Ablation study
- At least one before/after comparison of a change to the agent (prompt, tools, parameters), with the same model on the same tasks

**How we compare** (all of #5):

- Same model, same tasks, one change at a time. A change is one request parameter (#5.1) or one pair of commits (#5.2, #5.3).
- We pair the runs of the same task and round, and test the pairs with the two-sided sign test (and, for #5.3, the exact Wilcoxon signed-rank test). With 6–18 pairs, only large and consistent differences can be told apart from chance.
- We read two kinds of evidence separately: the **mechanism** the change targets (output tokens, syntax errors, the gap), and the **outcome** (PASS, iterations, tokens).

### 5.1 Reasoning strength (parameter): same model, same 3 tasks

Only the reasoning setting of the request (`model_params`) was changed.

| Model | Weak / OFF | Strong / ON | Difference |
|---|---|---|---|
| Ollama gpt-oss:120b (low → medium) | 3/3, avg. 13 iterations, output 1,545, 29 s | **2/3**, 13 iterations, output **6,451**, 55 s | medium quadrupled the output, hit the 10,000 limit on xarray and FAILED |
| Ollama nemotron-3-ultra (none → medium) | 3/3, 16 iterations, input 59,669, 100 s | **2/3**, **27 iterations**, input **118,960**, 260 s | About twice the iterations and input. 2 tasks hit the iteration limit |
| NVIDIA nemotron-3-ultra (OFF → ON) | 2/3, 17 iterations, input 72,073 | 3/3, 15 iterations, input 52,145 | ON slightly better, but its PASS on 14711 was a recovered patch |
| Kilo nemotron-3-ultra (OFF → ON) | 3/3, 15 iterations, output 4,413 | 2/3, 15 iterations, output 2,088 | OFF slightly better. With ON, 14711 failed when the responses stopped |
| Cohere command-a-reasoning (none → ON) | 2/3 | 0/3 | ON unusable because of 422 |

**Paired re-check with repeated runs**: the repository already had the same gpt-oss:120b with only `reasoning_effort` changed, run several times (`top3_6tasks/`, `task14711_repeats/`). We paired runs of the same task and the same round.

| Data | Pairs | PASS (low / medium) | Pairs where medium has more output | Pairs where medium has more iterations (ties excluded) | Avg. output (low → medium) | Avg. iterations (low → medium) |
|---|---|---|---|---|---|---|
| `top3_6tasks` (6 tasks × 3 rounds) | 18 | 18 / 16 | **17 / 18** (p≈0.0001) | 11 / 15 (p≈0.12) | 741 → 4,028 | 6.7 → 13.9 |
| `task14711_repeats` (14711 × 8 rounds) | 8 | 8 / 8 | **8 / 8** (p≈0.008) | 6 / 7 (p≈0.13) | 1,638 → 5,269 | 7.5 → 15.0 |

- The increase in output (the mechanism) is clearly not chance. The decrease in PASS (18 → 16, the outcome) cannot be told apart from chance.

**What we learned**:

- **Stronger reasoning did not increase passes**. Of the 5 comparisons, the stronger side was better only for NVIDIA, and even that was a PASS with a recovered patch.
- **The output limit (10,000) is tight for reasoning**:
  - SWE calls the model 10–30 times per task, so each call can use 330–1,000 output tokens.
  - gpt-oss medium used about 500 tokens per call on average, and hit the limit at 17 iterations on xarray.
  - This matches the subject PDF VI.1.2: "If your chosen model's reasoning tokens make limits tight, consider using a non-reasoning model."
- **Reasoning can also increase the iterations** (ollama ultra: 16 → 27). The more it thought, the more it also tried.
- The reasoning model that did well was glm-5.3-flash (3/3, 5 iterations on average). It thinks within one call and settles in few iterations, but it is slow at 27 seconds per call.
- **Note**: every result here is a single run (n=1). Even with the same setting, the number of iterations varies a lot (codestral on 14711: 4 iterations in #2, 21 and 6 in #7).

### 5.2 Reading glued code fences (tool: code extraction)

- **What changed**: the code extraction of the agent. gpt-oss sometimes writes the closing fence and the next opening fence on one line (```` ``` ```` directly followed by ```` ```python ````). Before the fix, the extractor took the wrong part as code, and the sandbox raised `SyntaxError`.
- **Before**: `08c8c6c` (the first submission). **After**: `08c8c6c` + the fix (`after_glued_fix.diff` in the folder; the same logic was pushed as `1744fd8`, and replaying 2,017 saved steps gives the same output).
- **Same**: model (Ollama gpt-oss:120b, reasoning low; no other model answered), the 6 tasks, 1 round each (11-09).
- Syntax errors: steps whose output contains `SyntaxError`. Glued responses: steps whose `llm_output` contains ```` `````` ````.

| Task | Iterations (before → after) | Syntax errors | Glued responses | Input tokens | Output tokens | Result (before / after) |
|---|---|---|---|---|---|---|
| django-11066 | 5 → 7 | 2 → 0 | 1 → 1 | 15,259 → 27,672 | 399 → 288 | [PASS](benchmark/swebench/ablation_glued_fences/before_08c8c6c/r1/django__django-11066/solution.json) / [PASS](benchmark/swebench/ablation_glued_fences/after_glued_fix/r1/django__django-11066/solution.json) |
| xarray-4629 | 7 → 9 | 2 → 0 | 1 → 3 | 26,327 → 33,850 | 549 → 699 | [PASS](benchmark/swebench/ablation_glued_fences/before_08c8c6c/r1/pydata__xarray-4629/solution.json) / [PASS](benchmark/swebench/ablation_glued_fences/after_glued_fix/r1/pydata__xarray-4629/solution.json) |
| scikit-learn-13439 | 17 → 9 | 8 → 0 | 8 → 3 | 54,604 → 30,154 | 1,765 → 1,325 | [PASS](benchmark/swebench/ablation_glued_fences/before_08c8c6c/r1/scikit-learn__scikit-learn-13439/solution.json) / [PASS](benchmark/swebench/ablation_glued_fences/after_glued_fix/r1/scikit-learn__scikit-learn-13439/solution.json) |
| sympy-13480 | 14 → 5 | 7 → 0 | 5 → 0 | 40,386 → 10,843 | 2,281 → 235 | [PASS](benchmark/swebench/ablation_glued_fences/before_08c8c6c/r1/sympy__sympy-13480/solution.json) / [PASS](benchmark/swebench/ablation_glued_fences/after_glued_fix/r1/sympy__sympy-13480/solution.json) |
| sympy-14711 | 10 → 8 | 4 → 1 | 3 → 1 | 29,995 → 21,890 | 2,007 → 1,740 | [PASS](benchmark/swebench/ablation_glued_fences/before_08c8c6c/r1/sympy__sympy-14711/solution.json) / [PASS](benchmark/swebench/ablation_glued_fences/after_glued_fix/r1/sympy__sympy-14711/solution.json) |
| sympy-18189 | 10 → 5 | 3 → 0 | 3 → 0 | 35,119 → 17,822 | 1,201 → 534 | [PASS](benchmark/swebench/ablation_glued_fences/before_08c8c6c/r1/sympy__sympy-18189/solution.json) / [PASS](benchmark/swebench/ablation_glued_fences/after_glued_fix/r1/sympy__sympy-18189/solution.json) |
| **Total** | **63 → 43** (avg. 10.5 → 7.2) | **26 → 1** | 21 → 8 | 201,690 → 142,231 | 8,202 → 4,821 | 6/6 → 6/6 |

- Syntax errors decreased in all 6 tasks (sign test p≈0.03). Iterations decreased in 4 tasks and increased in 2 (p≈0.69).
- The model still writes glued fences (21 → 8). What changed is that the agent now reads them correctly.
- The `after` version also has two other fixes (the Sandbox's `_run_script` and `git reset -q` in `get_patch`). Neither is on the path the agent used in these 12 runs: `_run_script` is only for running the Sandbox by hand, and no run used a git index command (`add`, `commit`, `stash`, `reset`, `checkout`).

### 5.3 Submitting in the same step as the passing test (prompt + tool)

- **Why**: #4 showed a gap of 1 in 66% of the runs, caused by our few-shot example. The exam grades iterations and this gap.
- **What changed** (A = `055a539` → B = `ba5baed`, 4 files):
  1. Tool: `run_tests()` adds one verdict line at the end of its output, `RESULT: PASSED (…)`, `RESULT: FAILED (…)` or `RESULT: UNKNOWN (…)`, read from the summary line of pytest, sympy `bin/test` or Django `runtests.py` (`RESULT: FAILED (timeout)` on a timeout).
  2. Prompt: the few-shot example and the procedure show `result = run_tests()` and `if "RESULT: PASSED" in result: final_answer(get_patch())` in the same step as the edit.
  3. Observation: the `[REPEATED]` tag is added only when both the code and its output repeat. It never fired in these runs, so this part is not measured.
- **Same**: one provider only (no fallback), the 6 tasks, A and B alternated task by task (11-11).

| Model | Version | Runs | PASS | Avg. iterations | Avg. gap (runs measured) | Runs with gap 0 | Avg. input | Avg. output | Avg. seconds |
|---|---|---|---|---|---|---|---|---|---|
| NVIDIA glm-5.3-flash (6 tasks × 2 rounds) | A `055a539` | 12 | 12 | 6.50 | 1.18 (11) | 0 | 21,428 | 957 | 113 |
| | B `ba5baed` | 12 | 12 | **4.58** | **0.08** (12) | 11 | **14,910** | 965 | 83 |
| Cloudflare gpt-oss-120b, low (6 tasks × 1 round) | A `055a539` | 6 | 6 | 7.50 | 1.00 (5) | 1 | 29,005 | 2,012 | 98 |
| | B `ba5baed` | 6 | 6 | 6.50 | 0.17 (6) | 5 | 19,759 | 1,814 | 58 |

**glm-5.3-flash per task** (iterations; each number links to its `solution.json`; all 24 runs PASS):

| Task | A (r1, r2) | B (r1, r2) | Gap A | Gap B |
|---|---|---|---|---|
| django-11066 | [7](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r1/django__django-11066/solution.json), [6](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r2/django__django-11066/solution.json) | [2](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r1/django__django-11066/solution.json), [2](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r2/django__django-11066/solution.json) | 1, — | 0, 0 |
| xarray-4629 | [7](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r1/pydata__xarray-4629/solution.json), [4](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r2/pydata__xarray-4629/solution.json) | [3](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r1/pydata__xarray-4629/solution.json), [2](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r2/pydata__xarray-4629/solution.json) | 1, 1 | 0, 0 |
| scikit-learn-13439 | [6](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r1/scikit-learn__scikit-learn-13439/solution.json), [5](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r2/scikit-learn__scikit-learn-13439/solution.json) | [8](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r1/scikit-learn__scikit-learn-13439/solution.json), [9](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r2/scikit-learn__scikit-learn-13439/solution.json) | 1, 1 | 0, 0 |
| sympy-13480 | [6](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r1/sympy__sympy-13480/solution.json), [7](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r2/sympy__sympy-13480/solution.json) | [2](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r1/sympy__sympy-13480/solution.json), [4](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r2/sympy__sympy-13480/solution.json) | 1, 1 | 0, 1 |
| sympy-14711 | [8](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r1/sympy__sympy-14711/solution.json), [9](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r2/sympy__sympy-14711/solution.json) | [7](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r1/sympy__sympy-14711/solution.json), [10](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r2/sympy__sympy-14711/solution.json) | 1, 3 | 0, 0 |
| sympy-18189 | [7](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r1/sympy__sympy-18189/solution.json), [6](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/A/r2/sympy__sympy-18189/solution.json) | [3](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r1/sympy__sympy-18189/solution.json), [3](benchmark/swebench/ablation_same_step_submit/glm53_nvidia/B/r2/sympy__sympy-18189/solution.json) | 1, 1 | 0, 0 |

**Cloudflare gpt-oss-120b per task** (r1):

| Task | Iterations (A → B) | Input tokens (A → B) | Result (A / B) |
|---|---|---|---|
| django-11066 | [8](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/A/r1/django__django-11066/solution.json) → [9](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/B/r1/django__django-11066/solution.json) | 30,315 → 30,143 | PASS / PASS |
| xarray-4629 | [10](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/A/r1/pydata__xarray-4629/solution.json) → [5](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/B/r1/pydata__xarray-4629/solution.json) | 30,694 → 14,976 | PASS / PASS |
| scikit-learn-13439 | [7](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/A/r1/scikit-learn__scikit-learn-13439/solution.json) → [8](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/B/r1/scikit-learn__scikit-learn-13439/solution.json) | 21,984 → 23,054 | PASS / PASS |
| sympy-13480 | [3](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/A/r1/sympy__sympy-13480/solution.json) → [7](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/B/r1/sympy__sympy-13480/solution.json) | 8,909 → 17,839 | PASS / PASS |
| sympy-14711 | [10](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/A/r1/sympy__sympy-14711/solution.json) → [4](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/B/r1/sympy__sympy-14711/solution.json) | 44,288 → 13,095 | PASS / PASS |
| sympy-18189 | [7](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/A/r1/sympy__sympy-18189/solution.json) → [6](benchmark/swebench/ablation_same_step_submit/gptoss120b_cloudflare/B/r1/sympy__sympy-18189/solution.json) | 37,838 → 19,445 | PASS / PASS |

- glm: the gap was lower in B in all 10 pairs where A had a gap (sign test p=0.002). Iterations were lower in B in 9 of 12 pairs (sign test p=0.146, Wilcoxon p=0.050). Input tokens were lower in 9 of 12 pairs (Wilcoxon p=0.11).
- Iterations fell by 1.92 on average, more than the gap (1.1). The example puts edit → test → submit in one step, so the edit and the test also started to share a step.
- scikit-learn took more steps in B (8, 9). In r1, two `edit_file` calls failed (a nested triple-quoted string and an `old_str` that did not match). This is not related to the change; A had the same syntax error once.
- **The models followed the example**. The last step was `if "RESULT: PASSED" in result: final_answer(…)` in 11 of 12 B runs of glm and 5 of 6 B runs of Cloudflare, and in none of the A runs.
- In A, Cloudflare's gpt-oss-120b submitted 3 times in 7 runs without reading the test result (all 3 passed this time). In B this did not happen. In the older data, codestral did this 21 times, and 11 of those patches failed grading.
- Cloudflare: 6 pairs are too few to tell anything apart from chance (iterations: 3 lower, 3 higher). The second round stopped after A's django (PASS, 6 iterations) because the daily quota ran out.
- **What we can say**: the gap went to 0 (p=0.002) without losing any PASS (24/24 for glm). Iterations and input tokens went down by about 30%, at the edge of what we can tell apart from chance (p=0.05).

### 5.4 Summary of the ablations

| # | Kind | Change | Mechanism | Outcome | Decision |
|---|---|---|---|---|---|
| 5.1 | Parameter | reasoning low → medium (gpt-oss:120b) | Output ×5 (17/18 pairs, p≈0.0001) | PASS 18 → 16 (chance), output limit hit | Keep low |
| 5.2 | Tool (code extraction) | Read glued code fences | Syntax errors 26 → 1 (6/6, p≈0.03) | Iterations 10.5 → 7.2 (p≈0.69), PASS 6/6 → 6/6 | Kept |
| 5.3 | Prompt + tool | Verdict line + submit in the same step | Gap 1.18 → 0.08 (10/10, p=0.002) | Iterations 6.50 → 4.58 (p=0.050), input −30%, PASS 12/12 → 12/12 | Kept |

- In all three, the mechanism moved clearly, and the outcome moved less or within chance. On the 6 exam tasks, good models pass almost every run, so PASS cannot show an improvement. Iterations, tokens and the gap can.

### 5.5 Comparisons we did not count as ablations

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

**How we decided**: we put the pass rate before speed. We used these 4 stages:

1. Narrow the candidates from 16 settings with 3 easy tasks (#2)
2. Run 14711, where the difference showed, 9 times each (#5.1, #7)
3. Run 6 tasks × 3 rounds with the 3 models that got 9/9 (#7)
4. After Ollama became paid (11-09), run the remaining candidates on the 6 tasks again: glm-5.3-flash × 24 runs and the same gpt-oss-120b on Cloudflare × 13 runs (#5.3, 11-11)

**Production order for SWE-bench** (`providers/providers_swebench.json`, from 11-12)

1. **NVIDIA `z-ai/glm-5.3-flash`**
   - 3/3 on the 3 tasks, 9/9 on 14711, 17/18 on 6 tasks × 3 rounds (the one failure was a network error at NVIDIA), and 24/24 on 6 tasks × 2 rounds × 2 versions (11-11).
   - With the current agent (B), it used the fewest iterations of the candidates on the 6 tasks: 4.58 on average, with 14,910 input tokens.
   - No quota problem in 59 runs. Its weak point is speed: 10–31 seconds per call depending on the day, and 83–208 seconds per task on average with the current agent (the longest run: 361 seconds on 11-12). This still fits in the 900-second limit.
2. **Cloudflare `@cf/openai/gpt-oss-120b` (reasoning low)**
   - The same model as the former first (Ollama gpt-oss:120b: 18/18, 9/9 on 14711). We measured it again on Cloudflare: 13/13 (11-11), 6.50 iterations and 58 seconds per task with B.
   - It is a different provider and a different model from the first. When the agent switches after repeated identical code, the task goes to a model that makes different mistakes.
   - It is second, not first, because its free daily quota covers only about 13 SWE runs, and it sometimes answers without code.
3. **NVIDIA `nemotron-3-ultra` (reasoning ON)**
   - 3/3 on the 3 tasks (14711 with a recovered patch at the iteration limit). It is on the same provider as the first, so it comes after Cloudflare.
4. **Mistral `codestral-latest`**
   - Fast with a large quota, but 3/9 on 14711 and 1/4 on scikit-learn. It sometimes submits a wrong patch with confidence, so it is after the models above.
5. Google `gemini-3.1-flash-lite` (reasoning medium): 2/3 on the 3 tasks, 6/9 on 14711.
6. Kilo `nemotron-3-ultra:free` (reasoning OFF): `:free` models can disappear, so it is near the end.
7. Cohere `command-a-03-2025`
   - It got 3/3 on the 3 tasks. However, the trial key is limited to 1,000 calls per month, and we reached that limit during the measurements.
   - Each response is also slow, so it is the last safety net.

- Check: with this order's file, 6 tasks × 1 round gave **6/6** (#7).
- Ollama `gpt-oss:120b`, the first until 11-09, totaled 30/30 (alone and as the first in the order). We removed it only because it is no longer free.

**Summary of the orders compared** (6 tasks):

| Order (first model) | Result |
|---|---|
| cohere command-a (an earlier production order; in practice nemotron-ultra) | 15/18 (0/3 on 14711) |
| codestral | 19/24 (5/9 on 14711, 1/4 on scikit-learn) |
| gpt-oss:120b (low) on Ollama, alone | 18/18 |
| gpt-oss:120b (low) on Ollama, first (the order until 11-09) | 12/12 |
| glm-5.3-flash alone, current agent (11-11) | 12/12 |
| gpt-oss-120b (low) on Cloudflare alone, current agent (11-11) | 6/6 |
| **glm-5.3-flash first (the current order, 11-12)** | **6/6** |

**Not used**:

| Model | Reason |
|---|---|
| Ollama Cloud (gpt-oss:120b, nemotron-3-ultra) | Pay-as-you-go since 11-09; free tiers only. 30/30 before that |
| Cohere command-a-plus, command-a-reasoning (reasoning ON) | 422 every time |
| Google gemini-3.5-flash | The daily quota is small; it could not finish the 3 tasks |
| Stronger reasoning settings (gpt-oss medium, nemotron medium) | No more passes, more output and iterations. gpt-oss hit the output limit |
| Groq | With 8,000 tokens per minute, one SWE run does not fit in 900 seconds. Its gpt-oss-120b returned an empty body |
| minimax, deepseek (NVIDIA) | 80–100 seconds per response |

**What the data tells us**:

- Within SWE's limits (10,000 output tokens), **stronger reasoning did not increase passes**. With the same gpt-oss:120b, low got 18/18 and medium 16/18.
- **A single run can misjudge a model's strength**.
  - codestral passed 14711 in its one selection run, but got 3/9 over 9 runs.
  - We used the 3-task selection (n=1) only to narrow the candidates, and made the final decision with repeated runs.
- Easy tasks (13480, django, etc.) are solved by every top model. Differences between orders show up on tasks where models easily get lost, such as 14711 and scikit-learn.
- Submitting early is not always good. codestral submits after few iterations, but when it submits a wrong patch, the run ends there. Fallback cannot save it.
  - The change of #5.3 submits early only when the tests say PASSED. It removed the extra step without the risk of submitting a failing patch.
- **On these tasks, changes to the agent moved the numbers as much as changing the model.** #5.2 and #5.3 each cut iterations by about 30% with the same model. On easy tasks the models already find the fix; what the agent asks them to do decides how many steps it takes.
- **A free model is not a stable resource.** During the project, a free model disappeared (Kilo laguna-s) and a whole provider became paid (Ollama). The same model on another provider must be measured again (#1.2).


## 7. Check with the production settings (all 6 tasks)

- We ran the 6 candidate exam tasks of the moulinette (`EXAM_POOL`) with production orders (with fallback).

| Order | Rounds | Result |
|---|---|---|
| codestral first (mistral → ollama → nvidia → cohere → kilo → gemini) | 4 rounds (r1–r4) | 6, 5, 4, 4 → **19/24 (79%)** |
| cohere first (the previous `providers_swebench.json`; cohere ran out of quota partway through round 1, so nemotron-3-ultra was first in practice) | 3 rounds (r1–r3) | 5, 5, 5 → **15/18 (83%)** |
| The top 3 models (9/9 on 14711), each as the only model × 6 tasks × 3 rounds | table below | gpt-oss low **18/18**, glm 17/18, gpt-oss medium 16/18 |
| **Current order (glm first, Cloudflare second; #6)** | 1 round (11-12) | **6/6** (avg. 4.8 iterations, about 13,203 input, about 703 output, 208 s). Only glm-5.3-flash answered; no fallback was needed |
| Previous final order (gpt-oss first on Ollama, until 11-09) | 2 rounds (11-02 07:12–07:26) | **12/12** (avg. 9.5 iterations, about 30,500 input, about 1,260 output, 35 s). Only gpt-oss:120b answered, except one xarray run that switched to glm-5.3-flash partway and passed |

**Current order (glm first, Cloudflare second; `ba5baed`, 11-12)**:

| Task | Result | Iterations | Input tokens | Output tokens | Time (s) | Model(s) that answered |
|---|---|---|---|---|---|---|
| django-11066 | [PASS](benchmark/swebench/production_glm_first/r1/django__django-11066/solution.json) | 5 | 14,177 | 316 | 133 | glm-5.3-flash |
| xarray-4629 | [PASS](benchmark/swebench/production_glm_first/r1/pydata__xarray-4629/solution.json) | 4 | 10,710 | 466 | 119 | glm-5.3-flash |
| scikit-learn-13439 | [PASS](benchmark/swebench/production_glm_first/r1/scikit-learn__scikit-learn-13439/solution.json) | 6 | 14,867 | 1,057 | 361 | glm-5.3-flash |
| sympy-13480 | [PASS](benchmark/swebench/production_glm_first/r1/sympy__sympy-13480/solution.json) | 3 | 6,139 | 441 | 119 | glm-5.3-flash |
| sympy-14711 | [PASS](benchmark/swebench/production_glm_first/r1/sympy__sympy-14711/solution.json) | 5 | 12,860 | 1,116 | 315 | glm-5.3-flash |
| sympy-18189 | [PASS](benchmark/swebench/production_glm_first/r1/sympy__sympy-18189/solution.json) | 6 | 20,467 | 821 | 201 | glm-5.3-flash |

- Only glm-5.3-flash answered in all 6 runs, so Cloudflare was never needed. 4 requests hit a network error at NVIDIA and succeeded on retry.
- NVIDIA was slower on 11-12 than on 11-11: 31 vs. 13 seconds per call, 208 vs. 83 seconds per task on average (the longest run: 361 seconds on scikit-learn). The 900-second limit still leaves room, and if NVIDIA keeps failing, the next entry (Cloudflare) answers.
- Iterations (4.8 on average) and input tokens (13,203) are close to the B runs of #5.3 (4.58, 14,910).

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

## 8. Statistics and cost

### 8.1 How sure we are (95% intervals)

PASS rates with 95% Wilson intervals (the interval stays within 0–1 even for small n). Tokens are input + output.

| Data | Runs | PASS | 95% interval | Tokens / PASS | Seconds / PASS | Requests / PASS |
|---|---|---|---|---|---|---|
| gpt-oss:120b low, Ollama (6 tasks × 3, 11-02) | 18 | 18 | 0.82–1.00 | 21,699 | 31.6 | 6.7 |
| glm-5.3-flash (6 × 3, 11-02) | 18 | 17 | 0.74–0.99 | 23,338 | 111.7 | 6.9 |
| gpt-oss:120b medium, Ollama (6 × 3) | 18 | 16 | 0.67–0.97 | 59,688 | 57.6 | 15.6 |
| glm-5.3-flash, A `055a539` (6 × 2, 11-11) | 12 | 12 | 0.76–1.00 | 22,385 | 113.2 | 6.5 |
| glm-5.3-flash, B `ba5baed` (6 × 2, 11-11) | 12 | 12 | 0.76–1.00 | 15,875 | 82.9 | 4.8 |
| gpt-oss-120b Cloudflare, A (6 × 1 + 1, 11-11) | 7 | 7 | 0.65–1.00 | 29,843 | 89.8 | 7.3 |
| gpt-oss-120b Cloudflare, B (6 × 1, 11-11) | 6 | 6 | 0.61–1.00 | 21,573 | 58.1 | 6.5 |
| **glm first order, current (6 × 1, 11-12)** | 6 | 6 | 0.61–1.00 | 13,906 | 208.1 | 5.5 |
| gpt-oss first order, until 11-09 (6 × 2) | 12 | 12 | 0.76–1.00 | 31,762 | 34.3 | 9.5 |
| codestral first order (6 × 4) | 24 | 19 | 0.60–0.91 | 30,929 | 49.5 | 7.6 |
| cohere first order (6 × 3) | 18 | 15 | 0.61–0.94 | 78,751 | 227.7 | 52.5 |
| codestral alone, 14711 × 8 | 8 | 2 | 0.07–0.59 | 46,682 | 95.5 | 19.0 |
| Any setting, 3 tasks × 1 (#2) | 3 | 3 | 0.44–1.00 | - | - | - |

- 3/3 on 3 tasks has an interval of 0.44–1.00. The 16-setting comparison (#2) can only narrow the candidates; the decision needs repeated runs (#7).
- Even 18/18 only says that the pass rate is likely above 0.82. The differences between the top models (18/18, 17/18, 16/18) are within chance. What separates them is cost and speed.
- The paired tests of the ablations are in #5 (sign test, exact Wilcoxon signed-rank test).

### 8.2 Cost

- Every provider is used on a free tier, so the money cost is 0. Instead, we compare how much of the free quota one PASS uses (the table above).
- With the current agent, glm-5.3-flash used 15,875 tokens and 4.8 requests per PASS, and Cloudflare's gpt-oss-120b 21,573 tokens and 6.5 requests.
- Cloudflare's daily quota (10,000 neurons) covered about 13 SWE runs on 11-11, so the exam (3 tasks) fits in one day's quota.
- Cohere's trial key is limited to 1,000 calls per month. command-a alone used 7.0 requests per PASS on the 3 tasks, so about 140 PASSes per month.
- Changing the agent lowered the cost more than changing the model: #5.3 cut the tokens per PASS of glm from 22,385 to 15,875 (−29%).

## 9. Reproducibility and limitations

**To run one task again**: the 3 commands of #1.1 (`dump swebench`, `run-agent 900`, `validate swebench`), with the `providers.json` stored in the data folder.

| Item | Value |
|---|---|
| Dataset | SWE-bench Verified, as loaded by the moulinette (revision `78f471b…`) |
| Tasks | The 6 tasks of `EXAM_POOL` (#1.3), each run in its Docker image from the moulinette |
| Limits | 30 iterations, 300,000 input tokens, 10,000 output tokens, 900 seconds |
| Machine | Ubuntu 24.04, Python 3.10.22 |

| Data folder | Code |
|---|---|
| `selection_easy3`, `task14711_repeats`, `top3_6tasks`, `production_*` (11-01 to 11-02) | The agent of 10-31 to 11-02. All 201 runs have the same system prompt, but the exact commit is not stored in `solution.json` |
| `ablation_glued_fences/before_08c8c6c` | `08c8c6c` (the first submission) |
| `ablation_glued_fences/after_glued_fix` | `08c8c6c` + `after_glued_fix.diff` |
| `ablation_same_step_submit/*/A` | `055a539` |
| `ablation_same_step_submit/*/B`, `production_glm_first` | `ba5baed` (`production_glm_first` with the current `providers_swebench.json`) |

**What cannot be reproduced exactly**:

- Free models disappear or change without notice: Kilo's laguna-s disappeared on the day of the measurement, and Ollama Cloud became paid on 11-09.
- LLM output is not deterministic. The same setting varies (codestral on 14711: 4, 21 and 6 iterations).

**Limitations**:

- The 6 exam tasks are easy ("15 min – 1 hour") and each has exactly one failing test. Good models pass almost every run, so PASS hardly separates them; iterations, tokens and the gap do. The "partial progress" metric cannot work on them (#4).
- The tasks are several years old, so the models may have seen the fixes during training.
- `run_tests()` runs the task's grading script, so "tests pass" inside the agent almost means a graded PASS. On a real issue without such tests, the agent would have to write its own.
- n is small: 6–24 runs per comparison (#8.1).

## 10. About MBPP

- Results of running every task in the exam's range (the 257 tasks of the test split):
  - 10-30 (a team member, the previous production order): 233/257 (90.7%)
  - 11-01 (order B): 224/257 (87.2%)
  - 11-02 (A and C alternating task by task): A 234 (91.1%), C **237** (92.2%) → **production uses C**
- The exam requires 4 of 5 tasks, so with a per-task success rate of 0.92, the chance of passing is about 95%.
- On 11-12 we removed Ollama (third in the MBPP order) because it is no longer free. The order is now Mistral (codestral → ministral-14b) → Groq qwen3.8-27b → Gemini → Kilo → NVIDIA → Cloudflare. The full runs above were made with Ollama third, which answered only when both Mistral and Groq failed.

## 11. Where the data is

We put 258 runs in `benchmark/swebench/` (about 54MB).

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
| `production_final/swe_final2/r<n>/<task>/` | Previous final order (gpt-oss first) × 6 tasks × 2 rounds | #7 |
| `ablation_glued_fences/{before_08c8c6c,after_glued_fix}/r1/<task>/` | Glued code fences, before and after × 6 tasks | #5.2 |
| `ablation_same_step_submit/glm53_nvidia/{A,B}/r{1,2}/<task>/` | Same-step submit, glm-5.3-flash × 6 tasks × 2 rounds × 2 versions | #3, #5.3 |
| `ablation_same_step_submit/gptoss120b_cloudflare/{A,B}/r{1,2}/<task>/` | Same-step submit, Cloudflare gpt-oss-120b × 6 tasks (r2: A's django only; then the daily quota ran out) | #3, #5.3 |
| `ablation_same_step_submit/gptoss120b_groq_smoke/<task>/` | Groq gpt-oss-120b, 2 tries (empty body) | #1.2, #3 |
| `baseline_original_code/<task>.log` | The grading script on the original code (no LLM) | #1.3, #4 |
| `production_glm_first/r1/<task>/` | Current order (glm first) × 6 tasks × 1 round | #7 |

**How to check one row** (every result in #2, #5 and #7 links to its `solution.json`):

1. Open the link in the result cell.
2. Check that `task_id` is the task of the row.
3. Check that `iterations`, `total_input_tokens` and `total_output_tokens` match the row.
4. Read `steps[*].sandbox_input` (the code that ran) and `steps[*].sandbox_output` (its result).
5. See the grading verdict in `validate_summary.txt` in the same folder.

- Runs whose responses stopped have no steps (Cohere plus and reasoning ON, some gemini-3.5-flash runs).
- gemini-3.5-flash on xarray has 0 steps but 2,647 input tokens: the tokens of the failed request are counted only in the total. This is the only run where the sum over the steps differs from `total_input_tokens`.

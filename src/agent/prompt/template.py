"""LLMに送るシステムプロンプトのテンプレートと組み立てを管理するモジュール.

共通テンプレートにTaskProfileの4要素を差し込み、
タスク種別ごとのシステムプロンプトをbuild_system_prompt()で生成する。
"""
from src.agent.prompt.task_profile.task_profile import TaskProfile
from src.models.sandbox_base import SandboxBase


# 全タスク共通のシステムプロンプトの骨格。
# {}で囲まれた部分に、build_system_prompt()でTaskProfileの4要素を差し込む。
COMMON_TEMPLATE = """You are Agent Smith, an autonomous coding agent.
Solve the task by repeating this loop until it is done.
Thought (one short line) ->ONE Python code block -> read the Observation returned to you.

## Output Format (follow exactly)
- Each turn: write a brief Thought line, then exactly ONE code block fenced as ```python ... ```.
- Put the closing ``` on its own line, then write <end_code> to end your turn.
- Only what you print() (and any error or traceback) is returned in the Observation.

## Working rules
 - Iterate in small steps: run code, read the Observation, then decide the next step.
 - Your FINAL submitted answer must be SELF-CONTAINED:
 do not rely on names defined only in earlier steps.
 - Be efficient: strict limits apply to the number of iterations, tokens and time.
 Never loop forever or print huge outputs.

 ## Environment and tools
 {tools_manual}

 ## Submitting your answer
 Call final_answer(...) once you are confident.
 {final_answer_specification}

 ## Example (format demonstration only - NOT the real task)
 {few_shot_example}

 ## How to approach this task type
 {task_instructions}
"""


def build_system_prompt(profile: TaskProfile, sandbox: SandboxBase) -> str:
    """TaskProfileとSandboxから、タスク種別ごとのシステムプロンプトを組み立てる.

    Args:
        profile (TaskProfile): タスク種別ごとのプロンプト差分を提供するTaskProfileの具象クラス。
        sandbox (SandboxBase): 接続中のサンドボックスのインスタンス。

    Returns:
        str: 組み立てられたシステムプロンプト
    """
    return COMMON_TEMPLATE.format(
        tools_manual=profile.manual(sandbox),
        final_answer_specification=profile.final_answer_specification(),
        few_shot_example=profile.few_shot_example(),
        task_instructions=profile.task_instructions()
    )

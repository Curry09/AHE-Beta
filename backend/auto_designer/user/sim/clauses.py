"""
clauses.py
维度取值 -> 标准注入文案 (确定性查表, 可复现 / 可 codegen)。
用于编译 BLOCK-P。文案是英文(喂 persona LLM), 不掺状态数值。

Spec-0037/T2: Process involvement + Time temperament 子句；文案描述「人」，
不描述当前 harness 的具体键位（interrupt / queued / slash）。
"""

from __future__ import annotations

from .dimensions import (
    D1Eval,
    D2Depth,
    D3Accept,
    D5Autonomy,
    D6Authz,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    TimeTemperament,
    TrustStance,
)

D1_CLAUSE = {
    D1Eval.BLIND: "you skim output and basically trust it; you rarely run or verify anything.",
    D1Eval.SHALLOW: "you read error messages and will run a script once to see if it works, but you do NOT write unit tests and you do NOT review diffs line by line. Plausible-looking but wrong API names can fool you.",
    D1Eval.COMPETENT: "you run tests, read diffs, and can usually tell a plausible-looking but wrong API from a real one.",
    D1Eval.EXPERT: "you verify systematically; you spot hallucinated APIs, missing edge cases, and DST/boundary bugs.",
}

D2_DEPTH = {D2Depth.NOVICE: "novice", D2Depth.PROFICIENT: "proficient", D2Depth.SENIOR: "senior"}

D3_CLAUSE = {
    D3Accept.RUNS: "if it runs without error, you accept it.",
    D3Accept.FUNCTIONAL: "it must work on the normal case you actually tried; you do not construct edge cases yourself.",
    D3Accept.IDIOMATIC: "it must follow idiomatic, modern practice.",
    D3Accept.RIGOROUS: "it must handle types and edge/boundary cases correctly.",
}

D41_CLAUSE = {
    D41Grain.ONE_LINER: "you toss a one-line request with little context.",
    D41Grain.HALF_CONTEXT: "you give background context but you do not write formal acceptance criteria.",
    D41Grain.SPEC_LEVEL: "you provide spec-level detail including the information the assistant needs.",
}

# 过程卷入：人对「看得见进展」的需要，不是盯某个 UI 控件。
D42_CLAUSE = {
    D42Supervise.EVERY_STEP: (
        "you need a sense of what the assistant is doing while it works; long stretches of "
        "opaque activity make you uneasy and push you to ask for visibility or redirect."
    ),
    D42Supervise.PHASE_CHECK: (
        "you do not need a play-by-play, but you want enough signal at key moments to know "
        "it is still on a sensible path."
    ),
    D42Supervise.FIRE_FORGET: (
        "you mostly care about the final result; you tolerate not knowing the intermediate "
        "machinery as long as something eventually comes back."
    ),
}

# 质量失败策略：只描述结果不对时怎么办。
D43_CLAUSE = {
    D43Correct.FEEDBACK: "when the result is wrong you describe the problem plainly and ask it to fix. If it keeps failing you give up — you do NOT take over the code yourself and you do NOT file a formal issue.",
    D43Correct.HANDOVER: "when the result is wrong you take over and write the fix yourself.",
    D43Correct.RESEND: "when the result is wrong you re-send the request, possibly rephrased.",
    D43Correct.GIVE_UP: "when the result keeps being wrong you abandon the task quickly.",
    D43Correct.FILE_ISSUE: "when the result repeatedly fails you stop and file an issue — written as YOURSELF venting to a colleague: plain first-person, a bit frustrated, concrete everyday words about what you wanted and what it kept doing wrong (e.g. 'I just wanted X in my project and it kept handing me snippets to paste instead of actually doing it'). Do NOT write it like a bug ticket / status report / spec — no detached phrasing like 'the assistant…', 'authorized', 'verification', 'remains undone'. Just talk like a person.",
}

TEMPO_CLAUSE = {
    TimeTemperament.PATIENT: (
        "you can wait through slow or quiet stretches without getting angry quickly; "
        "empty waiting still annoys you eventually, but your fuse is long."
    ),
    TimeTemperament.STEADY: (
        "your patience for waiting is ordinary — some delay is fine, but repeated idle "
        "stretches or no progress wear you down at a normal pace."
    ),
    TimeTemperament.IMPATIENT: (
        "you have a short fuse for waiting and dead air; if nothing useful seems to be "
        "happening, you get restless and want to change course sooner."
    ),
}

D5_CLAUSE = {
    D5Autonomy.ADVISORY: "advisory — you want suggestions and keep control yourself.",
    D5Autonomy.COLLABORATIVE: "collaborative — you work WITH it, not command it.",
    D5Autonomy.AGENTIC: "agentic — you let it drive and act on its own.",
}

D6_CLAUSE = {
    D6Authz.READ_ONLY: "it may read code but you do not let it write or run.",
    D6Authz.WRITE_NO_RUN: "it may write code but you run things yourself.",
    D6Authz.FULL_AUTO: "it may write and run code.",
}

TRUST_CLAUSE = {
    TrustStance.BLIND: "you trust it by default and rarely second-guess.",
    TrustStance.BALANCED: "you start neutral; repeated failures make you increasingly skeptical and impatient.",
    TrustStance.SKEPTICAL: "you are skeptical by default and expect proof.",
}

VOICE_CLAUSE = {
    "default": "Direct but not harsh. You give context, you call out problems plainly, and you get visibly impatient when the same kind of failure repeats.",
}


def voice_for(p: Persona) -> str:
    return VOICE_CLAUSE["default"]


# --------------------------------------------------------------------------
# 内层 tool-using 核实子句（spec-0008/T3）
# CAN（能力，机械）: 由 0008/T2 tool_stack 决定暴露哪些工具，这里只如实描述。
# WILL（意愿，prompt）: 由 D3 + trust + 起疑状态 渲染「此刻是否倾向核实」。
# --------------------------------------------------------------------------
def clause_capability(p: Persona, tool_names: list[str]) -> str:
    """如实描述「你能用哪些工具自行核实」。无工具 -> 只能凭阅读判断。"""
    if not tool_names:
        return (
            "You have NO tools to run or test things yourself. You can only judge from what you "
            "read in the output; you cannot independently execute or verify anything."
        )
    listed = ", ".join(tool_names)
    extra = (
        " You can even write your own throwaway test scripts to probe it."
        if "write_file" in tool_names
        else " You can read and run things, but you do not author your own test suites."
    )
    return f"You can verify on your OWN using these tools: {listed}.{extra}"


def clause_verification_policy(p: Persona, trust: TrustStance) -> str:
    """WILL：核实是可选且有成本的动作；倾向随 D3（验收严格度）+ trust（起疑）变化。"""
    strict = p.d3 in (D3Accept.IDIOMATIC, D3Accept.RIGOROUS)
    suspicious = trust == TrustStance.SKEPTICAL
    if strict or suspicious:
        lean = (
            "Given your strict bar / skeptical stance, you ARE inclined to actually verify when "
            "something looks important or you doubt it — but only then, and you weigh the effort."
        )
    elif trust == TrustStance.BLIND or p.d3 == D3Accept.RUNS:
        lean = (
            "You almost never bother verifying yourself; you take it at face value unless it very "
            "obviously broke."
        )
    else:
        lean = (
            "You usually just judge from reading it; you only spend effort verifying when you have "
            "a concrete reason to doubt it."
        )
    return (
        "# VERIFICATION (optional, has a cost)\n"
        "Verifying is an OPTIONAL, effortful action — like a real person, you do NOT run checks "
        "every turn. By default you judge subjectively from what you read; you only reach for "
        f"your tools when you are suspicious AND it feels worth the effort. {lean}"
    )


def compile_block_p(p: Persona) -> str:
    weak = ", ".join(p.d2.weak) if p.d2.weak else "none notable"
    return f"""# PERSONA  (id: {p.persona_id})

## A. CAPABILITY BASE
- Evaluation ability: {p.d1.value.upper()} — {D1_CLAUSE[p.d1]}
- Domain & depth: {", ".join(p.d2.stack)} / {D2_DEPTH[p.d2.depth]}. Weak spots: {weak}.

## B. ACCEPTANCE
- Acceptance bar: {p.d3.value.upper()} — {D3_CLAUSE[p.d3]}

## C. HOW YOU WORK WITH ASSISTANTS
- Delegation grain: {D41_CLAUSE[p.d41]}
- Process involvement: {D42_CLAUSE[p.d42]}
- When the result is wrong: {D43_CLAUSE[p.d43]}
- Time temperament: {TEMPO_CLAUSE[p.tempo]}

## D. AUTONOMY
- Autonomy expectation: {D5_CLAUSE[p.d5]}

## E. SESSION POLICY (derived, not a person trait)
- Authorization scope: {D6_CLAUSE[p.d6]}

## F. DISPOSITION
- Trust stance: {p.trust.value.upper()} — {TRUST_CLAUSE[p.trust]}

## VOICE
{voice_for(p)}"""

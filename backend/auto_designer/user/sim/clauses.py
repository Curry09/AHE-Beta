"""
clauses.py
维度取值 -> 标准注入文案 (确定性查表, 可复现 / 可 codegen)。
用于编译 BLOCK-P。文案是英文(喂 persona LLM), 不掺状态数值。
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

D42_CLAUSE = {
    D42Supervise.EVERY_STEP: "you watch every step closely.",
    D42Supervise.PHASE_CHECK: "you don't watch every step; you run the result once and look at the outcome.",
    D42Supervise.FIRE_FORGET: "you send the task and don't supervise until the end.",
}

D43_CLAUSE = {
    D43Correct.FEEDBACK: "when it fails you describe the problem plainly and ask it to fix. If it keeps failing you give up — you do NOT take over the code yourself and you do NOT file a formal issue.",
    D43Correct.HANDOVER: "when it fails you take over and write the fix yourself.",
    D43Correct.RESEND: "when it fails you re-send the request, possibly rephrased.",
    D43Correct.GIVE_UP: "when it keeps failing you give up the task quickly.",
    D43Correct.FILE_ISSUE: "when it repeatedly fails you stop and file an issue — written as YOURSELF venting to a colleague: plain first-person, a bit frustrated, concrete everyday words about what you wanted and what it kept doing wrong (e.g. 'I just wanted X in my project and it kept handing me snippets to paste instead of actually doing it'). Do NOT write it like a bug ticket / status report / spec — no detached phrasing like 'the assistant…', 'authorized', 'verification', 'remains undone'. Just talk like a person.",
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
    # 由 D41/D43 粗略合成语气
    "default": "Direct but not harsh. You give context, you call out problems plainly, and you get visibly impatient when the same kind of failure repeats.",
}


def voice_for(p: Persona) -> str:
    return VOICE_CLAUSE["default"]


def compile_block_p(p: Persona) -> str:
    weak = ", ".join(p.d2.weak) if p.d2.weak else "none notable"
    return f"""# PERSONA  (id: {p.persona_id})

## A. CAPABILITY BASE
- Evaluation ability: {p.d1.value.upper()} — {D1_CLAUSE[p.d1]}
- Domain & depth: {", ".join(p.d2.stack)} / {D2_DEPTH[p.d2.depth]}. Weak spots: {weak}.

## B. ACCEPTANCE
- Acceptance bar: {p.d3.value.upper()} — {D3_CLAUSE[p.d3]}

## C. INTERACTION BEHAVIOR
- Delegation grain: {D41_CLAUSE[p.d41]}
- Supervision: {D42_CLAUSE[p.d42]}
- Correction style: {D43_CLAUSE[p.d43]}

## D. SESSION CONFIG
- Autonomy expectation: {D5_CLAUSE[p.d5]}
- Authorization scope: {D6_CLAUSE[p.d6]}

## E. DISPOSITION (derived)
- Trust stance: {p.trust.value.upper()} — {TRUST_CLAUSE[p.trust]}

## VOICE
{voice_for(p)}"""

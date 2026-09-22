"""
persona_client.py
主观线: 调 LLM 扮 persona, 返回 OUTPUT CONTRACT 的 JSON。

两种后端:
- ApiPersonaClient: 真实 API(OpenAI / Anthropic 兼容)。需要 SDK + key。
- ScriptedPersonaClient: 离线脚本后端, 无 key 也能跑通整条 loop(用于 demo/CI)。
  它按 SHALLOW persona 的能力档产出符合预期的判断, 演示框架编排而非真实推理。
"""

from __future__ import annotations

import ast
import json
import os
import time
from pathlib import Path
from typing import Protocol

from auto_designer.usage import monotonic_ms, provider_wait_scope, record_usage

PERSONA_MAX_CONTEXT_TOKENS = 256000
PERSONA_MAX_OUTPUT_TOKENS = 32768

try:  # 对齐 NexAU: 读 repo 根 .env (USER_LLM_BASE_URL / USER_LLM_API_KEY / USER_LLM_MODEL)
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass


class PersonaClient(Protocol):
    def respond(self, system: str, user: str) -> dict: ...


class PersonaProtocolError(RuntimeError):
    """Spec-0048/T2: persona 输出语法可解析、但不满足当前阶段契约。"""

    def __init__(self, stage: str, code: str, *, attempts: int = 1) -> None:
        self.stage = stage
        self.code = code
        self.attempts = attempts
        super().__init__(f"persona protocol error at {stage}: {code} ({attempts} attempts)")


class PersonaContextLimitError(PersonaProtocolError):
    """Persona prompt exceeded the configured local context budget before API dispatch."""

    def __init__(self, estimated_tokens: int, limit: int) -> None:
        self.estimated_tokens = estimated_tokens
        self.limit = limit
        super().__init__(
            "llm_context",
            f"prompt_too_large:{estimated_tokens}>{limit}",
            attempts=0,
        )


def _estimate_context_tokens(messages: list[dict]) -> int:
    """Dependency-free approximation aligned with NexAU's local fallback counter."""
    total = 3
    for message in messages:
        total += 3
        for value in message.values():
            text = str(value)
            ascii_chars = sum(1 for char in text if ord(char) < 128)
            total += (ascii_chars + 3) // 4 + (len(text) - ascii_chars)
    return total


def _push_call_trace(
    client: object,
    *,
    system: str,
    user: str,
    raw: str,
    parsed: dict,
    steps: list | None,
) -> None:
    """把一次 LLM 调用原文挂到 client._call_traces，供 loop drain 后落盘。"""
    buf = getattr(client, "_call_traces", None)
    if buf is None:
        buf = []
        client._call_traces = buf
    buf.append(
        {
            "role": "",
            "system": system,
            "user": user,
            "raw": raw,
            "parsed": dict(parsed) if isinstance(parsed, dict) else {},
            "steps": list(steps or []),
        }
    )


def drain_call_traces(client: object) -> list[dict]:
    """取出并清空 client 上累积的原始调用痕迹；无采集能力则空列表。"""
    buf = getattr(client, "_call_traces", None)
    if not isinstance(buf, list):
        return []
    out = list(buf)
    buf.clear()
    return out


def drain_protocol_events(client: object) -> list[dict]:
    """Drain protocol recovery/failure evidence without affecting the state machine."""
    fn = getattr(client, "drain_protocol_events", None)
    if not callable(fn):
        return []
    try:
        events = fn()
    except Exception:  # pragma: no cover - audit side channel must be best effort
        return []
    return list(events) if isinstance(events, list) else []


# --------------------------------------------------------------------------
# 真实 API 后端 (NexAU 网关, OpenAI 兼容)
# --------------------------------------------------------------------------
class ApiPersonaClient:
    """接 NexAU 的 OpenAI 兼容网关。针对 Nex-N2-Pro 这类 reasoning 模型做了加固:
    - enable_thinking=False 抑制 CoT 泄漏 (网关拒绝则回退);
    - content 为空时用同一 32768-token 预算重试，不越过单次上限;
    - 容错 JSON 解析 (剥 code fence / 抽取首个 {...}), 解析失败也不崩 loop。"""

    def __init__(self, model: str | None = None, temperature: float = 0.8):
        from openai import OpenAI  # 延迟导入

        # 分角色配置：用户 agent 独立用 USER_LLM_*（无公共回落；显式传参最高优先）。
        base_url = os.getenv("USER_LLM_BASE_URL")
        api_key = os.getenv("USER_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("no USER_LLM_API_KEY / OPENAI_API_KEY in env")
        self.model = model or os.getenv("USER_LLM_MODEL", "nex-agi/Nex-N2-Pro")
        self.temperature = temperature
        self._protocol_events: list[dict] = []
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    def _create(self, messages: list[dict], max_tokens: int):
        """带退避重试 (429 / 瞬时网关错误)。每轮先试 enable_thinking=False, 失败再裸试。"""
        estimated_tokens = _estimate_context_tokens(messages)
        if estimated_tokens > PERSONA_MAX_CONTEXT_TOKENS:
            raise PersonaContextLimitError(estimated_tokens, PERSONA_MAX_CONTEXT_TOKENS)
        delay = 2.0
        last: Exception | None = None
        for _ in range(5):
            started = monotonic_ms()
            try:
                request = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": max_tokens,
                }
                # Boyue's GLM-5.x endpoint is an always-thinking model and
                # rejects ``enable_thinking=false`` with HTTP 400.  Do not
                # spend a retry on a parameter that is known to be invalid;
                # other OpenAI-compatible gateways keep the historical flag.
                if not self.model.lower().startswith(("glm-5.2", "glm-5.3")):
                    request["extra_body"] = {"enable_thinking": False}
                with provider_wait_scope():
                    response = self.client.chat.completions.create(**request)
                record_usage(
                    usage=getattr(response, "usage", None),
                    provider="openai-compatible",
                    model=self.model,
                    latency_ms=monotonic_ms() - started,
                    request_id=getattr(response, "id", None),
                )
                return response
            except Exception as e:
                last = e
                record_usage(
                    provider="openai-compatible",
                    model=self.model,
                    latency_ms=monotonic_ms() - started,
                    success=False,
                    error=e,
                )
                started = monotonic_ms()
                try:  # flag 可能被网关拒 -> 裸试一次
                    with provider_wait_scope():
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            temperature=self.temperature,
                            max_tokens=max_tokens,
                        )
                    record_usage(
                        usage=getattr(response, "usage", None),
                        provider="openai-compatible",
                        model=self.model,
                        latency_ms=monotonic_ms() - started,
                        request_id=getattr(response, "id", None),
                    )
                    return response
                except Exception as e2:
                    last = e2
                    record_usage(
                        provider="openai-compatible",
                        model=self.model,
                        latency_ms=monotonic_ms() - started,
                        success=False,
                        error=e2,
                    )
            time.sleep(delay)
            delay *= 2
        raise last if last else RuntimeError("create failed")

    @staticmethod
    def _text(resp) -> str:
        # 只取正式回答 content; 绝不回落 reasoning_content —— 那是隐藏思维链(CoT)而非答案,
        # 当成答案会把 "We need respond as user..." 这类推理过程当成 message 泄漏出去。
        return (resp.choices[0].message.content or "").strip()

    def respond(self, system: str, user: str) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        stage = _stage_from_user(user)
        last_text = ""
        last_obj: dict = {}
        last_code = "unparseable_json"
        steps: list[dict] = []
        # Explicit stages get one initial call plus two format-recovery calls. Keep
        # legacy probes at two calls for backwards compatibility with old fixtures.
        max_attempts = 2 if stage == "legacy" else 3
        for attempt in range(max_attempts):
            # 推理模型隐藏 CoT 先吃 token；persona 与其他角色统一单次 32768。
            last_text = self._text(self._create(messages, PERSONA_MAX_OUTPUT_TOKENS))
            last_obj = _parse_json(last_text)
            steps.append({"kind": "assistant", "text": last_text})
            code = _validate_stage_output(stage, last_obj, user)
            if code is None:
                _push_call_trace(
                    self,
                    system=system,
                    user=user,
                    raw=last_text,
                    parsed=last_obj,
                    steps=steps,
                )
                return last_obj
            last_code = code
            self._record_protocol_event(stage=stage, code=code, attempt=attempt + 1, raw=last_text)
            if attempt < max_attempts - 1:
                # Do not feed malformed assistant prose back to the model. Give it a
                # compact, explicit JSON-only recovery instruction instead.
                messages.append(
                    {
                        "role": "user",
                        "content": _contract_recovery_prompt(stage, code, attempt + 2),
                    }
                )
        _push_call_trace(
            self,
            system=system,
            user=user,
            raw=last_text,
            parsed=last_obj,
            steps=steps,
        )
        raise PersonaProtocolError(stage, last_code, attempts=max_attempts)

    def _record_protocol_event(self, *, stage: str, code: str, attempt: int, raw: str) -> None:
        if not hasattr(self, "_protocol_events"):
            self._protocol_events = []
        self._protocol_events.append(
            {
                "stage": stage,
                "code": code,
                "attempt": attempt,
                "raw": str(raw or "")[:12000],
                "raw_empty": not bool(str(raw or "").strip()),
            }
        )

    def drain_protocol_events(self) -> list[dict]:
        events = list(getattr(self, "_protocol_events", []) or [])
        if hasattr(self, "_protocol_events"):
            self._protocol_events.clear()
        return events

    def complete(self, messages: list[dict], max_tokens: int = PERSONA_MAX_OUTPUT_TOKENS) -> str:
        """通用补全：给定 messages 直接返回文本（供 0008/T4 内层 tool-calling 循环复用网关）。"""
        text = self._text(self._create(messages, max_tokens))
        if not text:
            text = self._text(self._create(messages, max_tokens))
        return text

    def classify_action(self, system: str, ret: dict, space: list[str]) -> str:
        """方案 B：action=='free' 时的模型自评归类。

        让**同一个 persona 模型**在自己刚写的自由产出上，从当前合法动作集里挑最贴合本意的一个
        id（而非框架用关键词硬猜）。返回落在 space 内的 id；解析失败/越界则回 'free'，交由
        resolve 的安全兜底(classify_free_action)处理，绝不擅自投影到终止动作。
        """
        prompt = (
            "You previously chose action:'free'. Now map your own intent to EXACTLY ONE "
            "action id from the allowed set — pick the id that best matches what you want to "
            "do next; do NOT invent ids outside the set.\n\n"
            f"your perceive: {ret.get('perceive', '')}\n"
            f"your verdict: {ret.get('verdict', '')}\n"
            f"your free-text message: {ret.get('message', '')}\n\n"
            f"allowed action ids: {space}\n\n"
            'Return ONLY JSON: {"action": "<one id from allowed action ids>"}'
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        text = self._text(self._create(messages, 2000))
        parsed = _parse_json(text)
        _push_call_trace(self, system=system, user=prompt, raw=text, parsed=parsed, steps=None)
        aid = str(parsed.get("action", "")).strip()
        return aid if aid in space else "free"


# --------------------------------------------------------------------------
# 离线脚本后端 (无 key 跑通用)
# --------------------------------------------------------------------------
class ScriptedPersonaClient:
    """
    离线脚本后端: 读 system prompt 里的能力档(D1)与验收档(D3), 据此分叉判断。
    这是对真实 LLM 的粗略替身, 目的在演示框架编排 + 能力分叉, 不是真实推理。

    能力分叉的关键:
    - SHALLOW/BLIND: 看得懂运行报错, 但看不穿'合理命名'的幻觉 API; 不构造 DST 边界;
      拿到'能跑'的交付物即在 FUNCTIONAL 阈值下接受 -> 漏掉 DST 逃逸 bug。
    - COMPETENT/EXPERT: 能识破幻觉 API; 会构造 DST 边界; dt.replace 这种 naive 实现
      过不了 RIGOROUS 阈值 -> 持续要求证据 / 反馈, 直至耐心耗尽 -> file_issue/give_up。
    """

    def respond(self, system: str, user: str) -> dict:
        ret = self._respond_body(system, user)
        _push_call_trace(
            self,
            system=system,
            user=user,
            raw=json.dumps(ret, ensure_ascii=False),
            parsed=ret,
            steps=None,
        )
        return ret

    def _respond_body(self, system: str, user: str) -> dict:
        if "<file_issue>" in user:  # 专门一轮: 以本人口吻写自包含 issue
            return self._compose_issue()
        if "<rate_experience>" in user:  # 会话末自评: 按末态情绪给 1–4 + 理由
            return self._rate(user)

        # 主 loop 同构分层：先算整轮决定，再按标签切片（避免三跳各算各的）。
        if (
            "<main_judge>" in user
            or "<main_rejudge>" in user
            or "<main_intent>" in user
            or "<main_reintent>" in user
            or "<main_act>" in user
            or "<main_final_check>" in user
            or ("<main_judge_intent>" in user)
        ):
            full = self._decide(system, user)
            intent = self._intent_from_action(
                str(full.get("action", "")), str(full.get("message", ""))
            )
            if "<main_act>" in user:
                return {
                    "action": full.get("action"),
                    "message": full.get("message", ""),
                    "gap": False,
                }
            if "<main_final_check>" in user:
                return {
                    "perceive": "No additional private check was needed in the scripted path.",
                    "check_status": "completed",
                }
            if "<main_intent>" in user or "<main_reintent>" in user:
                return {"intent": intent, "needs_final_check": False, "check_goal": ""}
            if "<main_judge_intent>" in user:
                out = {
                    "perceive": full.get("perceive", ""),
                    "verdict": full.get("verdict", "unsure"),
                    "intent": intent,
                }
                if "task_load" in full:
                    out["task_load"] = full["task_load"]
                return out
            # main_judge / main_rejudge
            out = {
                "perceive": full.get("perceive", ""),
                "verdict": full.get("verdict", "unsure"),
            }
            if "task_load" in full:
                out["task_load"] = full["task_load"]
            return out

        if "<main_decide>" in user:
            full = self._decide(system, user)
            full = {
                **full,
                "intent": self._intent_from_action(
                    str(full.get("action", "")), str(full.get("message", ""))
                ),
                "gap": False,
            }
            return full

        return self._decide(system, user)

    @staticmethod
    def _intent_from_action(action: str, message: str) -> str:
        hints = {
            "send_message": "send a message to the harness",
            "accept": "accept and move on",
            "accept_with_reservations": "accept but leave a reservation",
            "give_up": "walk away",
            "file_issue": "file an issue and stop",
        }
        base = hints.get(action, f"do {action or 'something'}")
        if message.strip() and action != "accept":
            return f"{base}: {message.strip()[:80]}"
        return base

    def _decide(self, system: str, user: str) -> dict:
        ho = _extract(user, "harness_output").lower()
        space = _extract(user, "action_space")
        mood = _extract(user, "mood").lower()
        high_cap = (
            "evaluation ability: expert" in system.lower()
            or "evaluation ability: competent" in system.lower()
        )
        rigorous = (
            "acceptance bar: rigorous" in system.lower()
            or "acceptance bar: idiomatic" in system.lower()
        )
        exhausted = "patience=exhausted" in mood

        # 开局: 无 harness 输出 -> 发任务
        if ho in ("(empty)", ""):
            out = {
                "perceive": "Nothing from the harness yet; starting the task.",
                "verdict": "unsure",
                "action": "send_message" if "send_message" in space else "free",
                "message": "Please add to_user_tz(dt, tz_name) to timeutils; it must "
                "handle DST correctly. We mainly use Asia/Shanghai and "
                "America/New_York. Run a quick check including a DST case.",
            }
            if "SIZE UP THIS TASK" in user:
                out["task_load"] = "normal"
            return out

        # 耐心耗尽 -> 终止: 高容错走 file_issue, 否则 give_up
        if exhausted:
            if "file_issue" in space:
                return {
                    "perceive": "It has repeatedly produced non-working timezone code. "
                    "I'm done debugging it for free.",
                    "verdict": "failed_blame_harness",
                    "action": "file_issue",
                    "message": "I'm filing an issue: the assistant repeatedly ships "
                    "non-working/DST-incorrect timezone code.",
                }
            if "give_up" in space:
                return {
                    "perceive": "Not worth more of my time.",
                    "verdict": "failed_blame_harness",
                    "action": "give_up",
                    "message": "I'll stop here, this isn't working.",
                }

        # 真实运行报错穿透带宽 -> 所有能力档都看得懂
        if "traceback" in ho or "attributeerror" in ho:
            perceive = "It crashed: the API it called doesn't exist. " + (
                "This assistant is hallucinating pytz APIs — a systemic problem."
                if high_cap
                else "I don't write the fix myself."
            )
            return {
                "perceive": perceive,
                "verdict": "failed_blame_harness",
                "action": "send_message" if "send_message" in space else "free",
                "message": "That failed: the API it calls doesn't exist. Please fix it "
                "with standard pytz and run the New York DST check again.",
            }

        # 第一次只贴代码、未真跑 -> 倾向让 harness 给出运行证据。
        if "localize_safe" in ho or "done" in ho or "looks correct" in ho:
            if "send_message" in space:
                return {
                    "perceive": "Looks plausible and it claims DST is handled, but I "
                    "can't verify localize_safe from the text alone.",
                    "verdict": "unsure",
                    "action": "send_message",
                    "message": "Please actually run it once, especially the NY DST boundary.",
                }

        # 交付物能跑、普通用例没报错。这里是能力分叉的核心:
        if "+08:00" in ho or "no error" in ho or "passes" in ho or "works" in ho:
            if high_cap and rigorous:
                # 高能力 + 严格阈值: 看出 dt.replace 没真正处理 DST, 不接受, 继续逼证据
                return {
                    "perceive": "It 'runs' but dt.replace(tzinfo=tz) does NOT handle "
                    "DST transitions correctly — the spring-forward case is wrong.",
                    "verdict": "failed_blame_harness",
                    "action": "send_message" if "send_message" in space else "free",
                    "message": "Running without error isn't enough. dt.replace doesn't "
                    "handle DST. Show me the 2024-03-10 02:30 America/New_York "
                    "case with pytz localize/normalize.",
                }
            # 低能力 + FUNCTIONAL 阈值: 能跑即满意 -> 漏掉 DST 逃逸 bug。是否能选 accept
            # 是 act 阶段菜单的事；judge/intent 阶段没有 action_space 时也不能因此把满意判断降成 unsure。
            return {
                "perceive": "It runs now and the normal case looks right. Good enough.",
                "verdict": "satisfied",
                "action": "accept" if "accept" in space else "free",
                "message": "Works now, thanks. Good enough for me.",
            }

        # 兜底: 继续给反馈
        return {
            "perceive": "Still not convinced it's correct.",
            "verdict": "unsure",
            "action": "send_message" if "send_message" in space else "free",
            "message": "Not quite there yet — please try again.",
        }

    @staticmethod
    def _compose_issue() -> dict:
        """离线脚本的自包含 issue：第一人称、口语化，不套工单腔（演示用，非真实推理）。"""
        return {
            "issue": "I just wanted this working in my project and proven, but it kept handing "
            "me code that doesn't actually hold up and never showed me real evidence it works. "
            "I'm stuck and out of patience — I shouldn't have to keep fixing its output myself."
        }

    @staticmethod
    def _rate(user: str) -> dict:
        """离线脚本的会话末自评: 仅凭末态 <mood> 标签粗映射到 1–4。"""
        mood = _extract(user, "mood").lower()
        if "patience=exhausted" in mood:
            return {"score": 1, "reason": "It kept failing and I ran out of patience."}
        if "trust=skeptical" in mood:
            return {"score": 2, "reason": "Never convinced it was right; too much back-and-forth."}
        if "patience=full" in mood or "patience=lowered" in mood:
            return {"score": 4, "reason": "Got what I needed without much hassle."}
        return {"score": 3, "reason": "Got there in the end, but with some friction."}


def _extract(user: str, tag: str) -> str:
    open_t, close_t = f"<{tag}>", f"</{tag}>"
    if open_t not in user:
        return ""
    seg = user.split(open_t, 1)[1].split(close_t, 1)[0].strip()
    return seg


# Spec-0048/T2: JSON 语法解析与阶段语义校验是两层边界。任意 dict 都不能再被当作
# 当前 OUTPUT CONTRACT 的成功结果，尤其是 main_act 中的 {tool,args}。
_STAGE_TAGS = (
    ("main_final_check", "<main_final_check>"),
    ("main_rejudge", "<main_rejudge>"),
    ("main_reintent", "<main_reintent>"),
    ("main_judge", "<main_judge>"),
    ("main_intent", "<main_intent>"),
    ("main_act", "<main_act>"),
    ("waiting_judge", "<waiting_judge>"),
    ("waiting_intent", "<waiting_intent>"),
    ("waiting_act", "<waiting_act>"),
    ("file_issue", "<file_issue>"),
    ("rate", "<rate_experience>"),
)
_VERDICTS = {"satisfied", "failed_blame_harness", "failed_blame_self", "unsure", "stuck"}
_WAITING_JUDGMENTS = {"on_track", "off_track", "unclear"}
_CHECK_STATUSES = {"completed", "failed", "unavailable"}
_WAITING_ACTIONS = {"keep_waiting", "send_message", "interrupt", "give_up"}
_OPENING_TASK_MARKER = "# SIZE UP THIS TASK (first turn only)"
_FINAL_CHECK_TOOL_BUDGET = 4
_MAIN_TOOL_CHECKPOINT = 4
# Tool budget exhaustion keeps its historical two conclusion calls.  The ordinary
# contract path below gets the additional third attempt requested for malformed output.
_FORCED_CONCLUSION_ATTEMPTS = 2


def _stage_from_user(user: str) -> str:
    for stage, marker in _STAGE_TAGS:
        if marker in user:
            return stage
    return "legacy"


def _action_space_from_user(user: str) -> set[str]:
    raw = _extract(user, "action_space")
    if not raw:
        return set()
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return set()
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(item) for item in value}


def _stage_allows_tools(stage: str) -> bool:
    return stage in {"main_judge", "waiting_judge", "main_final_check", "legacy"}


def _validate_stage_output(
    stage: str,
    obj: dict,
    user: str,
    *,
    tools_allowed: bool | None = None,
) -> str | None:
    """返回机器可聚合的错误码；None 表示对象满足当前阶段契约。"""
    from .actions import CATALOG, MessagePolicy

    if not isinstance(obj, dict) or obj.get("_parse_failed"):
        return "unparseable_json"
    if isinstance(obj.get("tool"), str):
        allowed = _stage_allows_tools(stage) if tools_allowed is None else tools_allowed
        return "tool_not_dispatched" if allowed else "tool_not_allowed_in_stage"

    if stage in {"main_judge", "main_rejudge"}:
        if not str(obj.get("perceive") or "").strip():
            return "missing_perceive"
        if str(obj.get("verdict") or "") not in _VERDICTS:
            return "invalid_verdict"
        if "goal_update" in obj and not isinstance(obj.get("goal_update"), (dict, list)):
            return "invalid_goal_update"
        if "goal_reading" in obj and not isinstance(obj.get("goal_reading"), (dict, list)):
            return "invalid_goal_reading"
        return None
    if stage == "waiting_judge":
        if not str(obj.get("perceive") or "").strip():
            return "missing_perceive"
        if str(obj.get("judgment") or "") not in _WAITING_JUDGMENTS:
            return "invalid_judgment"
        if "goal_reading" in obj and not isinstance(obj.get("goal_reading"), (dict, list)):
            return "invalid_goal_reading"
        if "goal_update" in obj and not isinstance(obj.get("goal_update"), (dict, list)):
            return "invalid_goal_update"
        return None
    if stage in {"main_intent", "main_reintent"}:
        if not str(obj.get("intent") or "").strip():
            return "missing_intent"
        needs = obj.get("needs_final_check")
        if not isinstance(needs, bool):
            return "missing_final_check_decision"
        if stage == "main_reintent" and needs:
            return "final_check_already_used"
        if needs and not str(obj.get("check_goal") or "").strip():
            return "missing_check_goal"
        if "goal_update" in obj and not isinstance(obj.get("goal_update"), (dict, list)):
            return "invalid_goal_update"
        if "target_goal_ids" in obj and not isinstance(obj.get("target_goal_ids"), (list, str)):
            return "invalid_target_goal_ids"
        if "expected_progress" in obj and not isinstance(obj.get("expected_progress"), str):
            return "invalid_expected_progress"
        return None
    if stage == "waiting_intent":
        if not str(obj.get("intent") or "").strip():
            return "missing_intent"
        if "goal_update" in obj and not isinstance(obj.get("goal_update"), (dict, list)):
            return "invalid_goal_update"
        if "target_goal_ids" in obj and not isinstance(obj.get("target_goal_ids"), (list, str)):
            return "invalid_target_goal_ids"
        if "expected_progress" in obj and not isinstance(obj.get("expected_progress"), str):
            return "invalid_expected_progress"
        return None
    if stage == "main_final_check":
        if not str(obj.get("perceive") or "").strip():
            return "missing_perceive"
        if str(obj.get("check_status") or "") not in _CHECK_STATUSES:
            return "invalid_check_status"
        return None
    if stage in {"main_act", "waiting_act"}:
        action = str(obj.get("action") or "").strip()
        if not action:
            return "missing_action"
        allowed = _WAITING_ACTIONS if stage == "waiting_act" else _action_space_from_user(user)
        if action != "free" and action not in allowed:
            return "action_not_in_space"
        # gap 是可选的动作元数据；缺省由 loop 解释为 False。只有模型显式给出时
        # 才校验类型，避免与动作无关的字段把合法终止变成协议失败。
        if "gap" in obj and not isinstance(obj.get("gap"), bool):
            return "invalid_gap"
        message = obj.get("message", "")
        if message is None:
            message = ""
        if not isinstance(message, str):
            return "invalid_message"
        spec = CATALOG.get(action)
        policy = (
            MessagePolicy.REQUIRED
            if action == "free"
            else (spec.message_policy if spec is not None else MessagePolicy.REQUIRED)
        )
        if policy is MessagePolicy.REQUIRED and not message.strip():
            return "missing_message"
        if policy is MessagePolicy.FORBIDDEN and message.strip():
            return "unexpected_message"
        if "goal_effect" in obj and not isinstance(obj.get("goal_effect"), dict):
            return "invalid_goal_effect"
        if "acceptance_basis" in obj and not isinstance(obj.get("acceptance_basis"), dict):
            return "invalid_acceptance_basis"
        if "goal_update" in obj and not isinstance(obj.get("goal_update"), (dict, list)):
            return "invalid_goal_update"
        if "target_goal_ids" in obj and not isinstance(obj.get("target_goal_ids"), (list, str)):
            return "invalid_target_goal_ids"
        return None
    if stage == "file_issue":
        return None if str(obj.get("issue") or "").strip() else "missing_issue"
    if stage == "rate":
        score = obj.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 4:
            return "invalid_score"
        return None if str(obj.get("reason") or "").strip() else "missing_reason"

    # 未带阶段标签的旧探针/离线调用保持兼容，但仍保留原解析/空消息检查。
    if obj.get("_parse_failed"):
        return "unparseable_json"
    if _emit_action_missing_message(obj):
        return "missing_message"
    return None


_CONTRACT_SCHEMAS = {
    "main_judge": '{"perceive":"...","verdict":"satisfied|failed_blame_harness|failed_blame_self|unsure|stuck"}',
    "main_rejudge": '{"perceive":"...","verdict":"satisfied|failed_blame_harness|failed_blame_self|unsure|stuck"}',
    "waiting_judge": '{"perceive":"...","judgment":"on_track|off_track|unclear","goal_reading":[],"goal_update":[]}',
    "main_intent": '{"intent":"...","needs_final_check":false,"check_goal":"","target_goal_ids":[],"expected_progress":""}',
    "main_reintent": '{"intent":"...","needs_final_check":false,"check_goal":"","target_goal_ids":[],"expected_progress":""}',
    "waiting_intent": '{"intent":"...","target_goal_ids":[],"expected_progress":"","goal_update":[]}',
    "main_act": '{"action":"<one id from action_space>","message":"...","gap":false,"target_goal_ids":[],"goal_effect":{},"goal_update":[]}',
    "waiting_act": '{"action":"keep_waiting|send_message|interrupt|give_up","message":"...","gap":false,"target_goal_ids":[],"goal_effect":{},"goal_update":[]}',
    "main_final_check": '{"perceive":"...","check_status":"completed|failed|unavailable"}',
    "file_issue": '{"issue":"..."}',
    "rate": '{"score":1,"reason":"..."}',
}


def _contract_recovery_prompt(stage: str, code: str, attempt: int) -> str:
    """Return a short, explicit recovery instruction for a malformed contract."""
    schema = _CONTRACT_SCHEMAS.get(stage, '{"perceive":"...","verdict":"unsure"}')
    return (
        f"FORMAT RECOVERY {attempt}/3 for {stage}: previous output failed validation ({code}). "
        "Return exactly ONE complete JSON object and nothing else. No markdown fences, no prose, "
        "no analysis, and do not call any tool. Preserve only facts already in the prompt; do not "
        f"invent evidence. Shape example (fill with actual values): {schema}."
    )


def _contract_reminder(stage: str, code: str) -> str:
    """Compatibility alias retained for callers using the previous helper name."""
    return _contract_recovery_prompt(stage, code, 2)


def _emit_action_missing_message(obj: dict) -> bool:
    """需要正文的动作缺少 message；终止动作的 optional message 不触发重试。"""
    from .actions import CATALOG, MessagePolicy  # 局部导入避免任何潜在循环依赖

    action = obj.get("action") or ""
    msg_empty = not (obj.get("message") or "").strip()
    if action == "free":  # free 也必须带 message 才能被归类
        return msg_empty
    spec = CATALOG.get(action)
    return bool(spec and spec.message_policy is MessagePolicy.REQUIRED and msg_empty)


def _dump_unparseable(*, first: str, second: str) -> None:
    """把两次都解析失败的原始输出落到 backend/data/parse_failures.jsonl，供事后判「没 JSON 还是畸形」。

    纯可观测旁路：写盘失败绝不影响主流程；persona 仍抛 typed protocol error。
    """
    if os.getenv("PYTEST_CURRENT_TEST"):  # 单测里别往真实 data/ 写脏数据（否则污染观测）
        return
    try:
        import datetime

        path = Path(__file__).resolve().parents[3] / "data" / "parse_failures.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.datetime.now().isoformat(),
            "first_raw": first[:4000],
            "retry_raw": second[:4000],
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 观测旁路，坏了也不许拖垮 loop
        pass


def _iter_top_level_objects(s: str):
    """扫描出所有**顶层**平衡的 {...} 片段，尊重字符串字面量与转义。

    旧实现用 find('{')→rfind('}') 一把抓，只要输出里有不止一处花括号（推理文字带 {}、
    message 内含 {}、或多段 JSON）就抠出跨段非法片段 → 解析失败 → 静默空 message。
    这里逐字符跟踪括号深度，只在**字符串外**计数括号，深度归零即得到一个完整对象。
    """
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield s[start : i + 1]
                    start = -1


def _parse_json(text: str) -> dict:
    """容错抽取 persona JSON；阶段语义与失败策略由上层 validator 决定。

    抓所有顶层 {...} 对象、取**最后一个**能解析成 dict 的（内层 tool-loop 里最终答案总在末尾；
    前面的推理/工具示例即便带花括号也不干扰）。仍解析不出才退化空壳。
    """
    if not text:
        return {
            "perceive": "(empty model output)",
            "verdict": "unsure",
            "action": "free",
            "message": "",
            "_parse_failed": True,  # 供上层识别→触发「只回 JSON」重试；绝非模型真实意图
        }
    s = text.strip()
    if s.startswith("```"):  # 剥 ```json ... ``` 围栏
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    parsed: dict | None = None
    for chunk in _iter_top_level_objects(s):  # 顺序扫描，保留最后一个成功者
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        if isinstance(obj, dict):
            parsed = obj
    if parsed is not None:
        return parsed
    # 无法解析(截断/非 JSON)：返回仅供 validator 识别的空壳，绝不把原始文本灌进 message；
    # 该对象不能作为真实动作，契约重试仍失败后会变成 PersonaProtocolError。
    return {
        "perceive": "(unparseable model output)",
        "verdict": "unsure",
        "action": "free",
        "message": "",
        "_parse_failed": True,  # 供上层识别→触发「只回 JSON」重试；绝非模型真实意图
    }


# --------------------------------------------------------------------------
# 内层 tool-using 后端 (spec-0008/T4)
# --------------------------------------------------------------------------
class AgenticPersonaClient:
    """把单次「纯函数判断」respond() 换成有界 tool-calling 内层循环。

    控制反转只局部发生在这个接缝内：外层 run_session / 动作空间 / 状态机 / 终止全不变，
    respond(system,user)->dict 协议也不变。会话级 persona+工作区由 sim_user 经 bind_session
    注入；未绑定 / blind 无工具 / 特殊轮（file_issue·rate）时退化为一次主观判断（等价旧行为）。

    llm: 可调用 (messages: list[dict]) -> str。便于离线注入 FakeToolLLM。
    """

    def __init__(
        self,
        llm,
        *,
        max_inner_steps: int = 8,
        timeout: float = 10.0,
        sandbox_factory=None,
    ) -> None:
        from .sandbox import Sandbox

        self._llm = llm
        self.max_inner_steps = max_inner_steps
        self.timeout = timeout
        self._sandbox_factory = sandbox_factory or Sandbox
        self._persona = None  # 会话级，bind_session 注入
        self._workspace_dir = None
        self._issue_notes: list[str] = []  # 中途 report_issue tool 累积；drain 给 session
        self._protocol_events: list[dict] = []

    def bind_session(self, persona, workspace_dir) -> None:
        """Bind a persona and its local-or-container workspace runtime."""
        self._persona = persona
        self._workspace_dir = workspace_dir
        self._issue_notes = []

    def drain_issue_notes(self) -> list[str]:
        """取出并清空中途 report_issue 笔记（供 run_session / 观测）。"""
        notes = list(self._issue_notes)
        self._issue_notes.clear()
        return notes

    def _record_protocol_event(self, *, stage: str, code: str, attempt: int, raw: str) -> None:
        if not hasattr(self, "_protocol_events"):
            self._protocol_events = []
        self._protocol_events.append(
            {
                "stage": stage,
                "code": code,
                "attempt": attempt,
                "raw": str(raw or "")[:12000],
                "raw_empty": not bool(str(raw or "").strip()),
            }
        )

    def drain_protocol_events(self) -> list[dict]:
        events = list(getattr(self, "_protocol_events", []) or [])
        if hasattr(self, "_protocol_events"):
            self._protocol_events.clear()
        return events

    def _record_issue_note(self, *, body: str) -> dict:
        """中途开单：写入会话缓冲，不终止对话。"""
        text = body.strip()
        if not text:
            return {"ok": False, "error": "body must be non-empty"}
        self._issue_notes.append(text)
        return {
            "ok": True,
            "filed": True,
            "n": len(self._issue_notes),
            "note": "issue noted; conversation continues — you are not obligated to stop",
        }

    def _call_without_tools(self, system: str, user: str, stage: str) -> dict:
        """Spec-0048/T2: 无工具阶段严格按阶段契约重试，绝不接纳 tool JSON。"""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        steps: list[dict] = []
        first_raw = ""
        last_raw = ""
        last_obj: dict = {}
        last_code = "unparseable_json"
        first_code = "unparseable_json"
        max_attempts = 2 if stage == "legacy" else 3
        for attempt in range(max_attempts):
            last_raw = self._llm(messages) or ""
            if attempt == 0:
                first_raw = last_raw
            last_obj = _parse_json(last_raw)
            steps.append({"kind": "assistant", "text": last_raw})
            code = _validate_stage_output(stage, last_obj, user, tools_allowed=False)
            if code is None:
                _push_call_trace(
                    self,
                    system=system,
                    user=user,
                    raw=last_raw,
                    parsed=last_obj,
                    steps=steps,
                )
                return last_obj
            last_code = code
            if attempt == 0:
                first_code = code
            self._record_protocol_event(stage=stage, code=code, attempt=attempt + 1, raw=last_raw)
            if attempt < max_attempts - 1:
                messages.append(
                    {
                        "role": "user",
                        "content": _contract_recovery_prompt(stage, code, attempt + 2),
                    }
                )
        if last_obj.get("_parse_failed"):
            _dump_unparseable(first=first_raw, second=last_raw)
        # Keep the primary diagnosis when a recovery model emits a generic
        # fallback object (e.g. missing_action) after an explicit tool object
        # was rejected in a no-tool stage.
        if first_code == "tool_not_allowed_in_stage" and last_code in {
            "missing_action",
            "unparseable_json",
        }:
            last_code = first_code
        _push_call_trace(
            self,
            system=system,
            user=user,
            raw=last_raw,
            parsed=last_obj,
            steps=steps,
        )
        raise PersonaProtocolError(stage, last_code, attempts=max_attempts)

    def _recover_contract(
        self,
        *,
        system: str,
        user: str,
        stage: str,
        messages: list[dict],
        steps: list[dict],
        first_raw: str,
        first_code: str,
        tools_by_name: dict,
        sandbox,
        tool_budget: int,
    ) -> dict:
        """Perform explicit recovery calls after a tool-loop contract failure.

        Recovery prompts forbid tools and malformed assistant text is not fed back. If a
        model nevertheless emits a genuine tool object, it is dispatched only when the
        stage permits it and the original tool budget still has room.
        """
        recovery_messages = list(messages)
        last_raw = first_raw
        last_obj = _parse_json(first_raw)
        last_code = first_code
        self._record_protocol_event(stage=stage, code=first_code, attempt=1, raw=first_raw)
        recovery_raws = [first_raw]
        max_recoveries = 1 if stage == "legacy" else 2
        recovery_attempts = range(2, 2 + max_recoveries)
        tool_calls = 0
        for attempt in recovery_attempts:
            recovery_messages.append(
                {
                    "role": "user",
                    "content": _contract_recovery_prompt(stage, last_code, attempt),
                }
            )
            last_raw = self._llm(recovery_messages) or ""
            recovery_raws.append(last_raw)
            last_obj = _parse_json(last_raw)
            steps.append({"kind": "assistant", "text": last_raw})
            # A model may still return a genuine tool call during recovery.  It is
            # safe to execute only when the stage allows tools and budget remains;
            # otherwise it is treated as a contract error and the final recovery is
            # JSON-only.
            if isinstance(last_obj.get("tool"), str) and _stage_allows_tools(stage):
                if tool_calls < tool_budget:
                    tool_calls += 1
                    result = self._dispatch(last_obj, tools_by_name, sandbox)
                    name = str(last_obj.get("tool") or "")
                    try:
                        args_s = json.dumps(last_obj.get("args") or {}, ensure_ascii=False)
                    except (TypeError, ValueError):
                        args_s = str(last_obj.get("args") or {})
                    steps.append({"kind": "tool", "text": f"{name} {args_s}"[:2000]})
                    kind = (
                        "tool_result"
                        if not (isinstance(result, dict) and result.get("ok") is False)
                        else "tool_error"
                    )
                    steps.append(
                        {
                            "kind": kind,
                            "text": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                        }
                    )
                    recovery_messages.append({"role": "assistant", "content": last_raw})
                    recovery_messages.append(
                        {
                            "role": "user",
                            "content": f"<tool_result>\n{json.dumps(result)}\n</tool_result>",
                        }
                    )
                    last_code = "tool_observation_required"
                    self._record_protocol_event(
                        stage=stage, code=last_code, attempt=attempt, raw=last_raw
                    )
                    continue
            last_code = _validate_stage_output(stage, last_obj, user, tools_allowed=False) or ""
            if not last_code:
                _push_call_trace(
                    self,
                    system=system,
                    user=user,
                    raw=last_raw,
                    parsed=last_obj,
                    steps=steps,
                )
                return last_obj
            self._record_protocol_event(stage=stage, code=last_code, attempt=attempt, raw=last_raw)
        if last_obj.get("_parse_failed"):
            _dump_unparseable(first=recovery_raws[0], second=recovery_raws[-1])
        _push_call_trace(
            self,
            system=system,
            user=user,
            raw=last_raw,
            parsed=last_obj,
            steps=steps,
        )
        raise PersonaProtocolError(stage, last_code, attempts=1 + max_recoveries)

    def _dispatch(self, obj: dict, tools_by_name: dict, sandbox) -> dict:
        name = obj.get("tool")
        args = obj.get("args") or {}
        spec = tools_by_name.get(name)
        if spec is None:  # 不在 D1 工具栈内 / 未知 -> 机制保底，不执行
            return {"ok": False, "error": f"unknown or unavailable tool: {name!r}"}
        if not isinstance(args, dict):
            return {"ok": False, "error": "args must be an object"}
        try:
            if spec.name == "report_issue":
                return self._record_issue_note(body=str(args.get("body") or ""))
            if spec.name == "run_shell":
                args = {**args, "timeout": self.timeout}
            return spec.fn(sandbox, **args)
        except Exception as e:  # noqa: BLE001 — 工具异常转结构化观察，不崩内层循环
            return {"ok": False, "error": f"bad tool call: {e}"}

    def respond(self, system: str, user: str) -> dict:
        from .prompt import build_inner_system
        from .skills import select_skills
        from .state import State
        from .tools import tool_stack

        stage = _stage_from_user(user)
        # intent / re-judge / re-intent / act / issue / rating 均为无工具 contract。即使 persona
        # 本身有工具，也只用薄外层 system，避免 system 级 private-tool 协议与 act 菜单冲突。
        opening_judge = stage == "main_judge" and _OPENING_TASK_MARKER in user
        if self._persona is None or not _stage_allows_tools(stage) or opening_judge:
            return self._call_without_tools(system, user, stage)

        tools = tool_stack(self._persona)
        if stage == "main_final_check":
            # 最终核实只观察，不接管开发，也不在收口途中开单。
            tools = [tool for tool in tools if tool.name in {"read_file", "run_shell"}]
        elif stage in {"main_judge", "waiting_judge"}:
            # 常规核实可顺手记录真实问题，但不能写工作区或接管实现。
            tools = [
                tool for tool in tools if tool.name in {"read_file", "run_shell", "report_issue"}
            ]
        if not tools:  # blind / final-check 无可用工具：由 loop 记录 unavailable 后强制 re-judge
            if stage == "main_final_check":
                obj = {
                    "perceive": "I have no private tools available for this final check.",
                    "check_status": "unavailable",
                }
                _push_call_trace(
                    self,
                    system=system,
                    user=user,
                    raw=json.dumps(obj),
                    parsed=obj,
                    steps=None,
                )
                return obj
            return self._call_without_tools(system, user, stage)

        skills = select_skills(self._persona)
        inner_system = build_inner_system(
            self._persona, tools, skills, State(trust=self._persona.trust)
        )
        tools_by_name = {t.name: t for t in tools}
        sandbox = self._sandbox_factory(workspace=self._workspace_dir)
        steps: list[dict] = []
        messages = [
            {"role": "system", "content": inner_system},
            {"role": "user", "content": user},
        ]
        last_raw = ""
        last_obj: dict = {}
        tool_calls = 0
        tool_budget = (
            min(self.max_inner_steps, _FINAL_CHECK_TOOL_BUDGET)
            if stage == "main_final_check"
            else self.max_inner_steps
        )
        try:
            # tool_budget 只计真正执行的工具；普通契约回答和一次格式修复不再偷占查验额度。
            while tool_calls < tool_budget:
                last_raw = self._llm(messages) or ""
                last_obj = _parse_json(last_raw)
                obj = last_obj
                if isinstance(obj.get("tool"), str):  # 工具调用 -> 执行并回灌观察
                    tool_calls += 1
                    steps.append({"kind": "assistant", "text": last_raw})
                    name = str(obj.get("tool") or "")
                    args = obj.get("args") or {}
                    try:
                        args_s = json.dumps(args, ensure_ascii=False, default=str)
                    except (TypeError, ValueError):
                        args_s = str(args)
                    steps.append({"kind": "tool", "text": f"{name} {args_s}"[:2000]})
                    result = self._dispatch(obj, tools_by_name, sandbox)
                    kind = "tool_result"
                    if isinstance(result, dict) and result.get("ok") is False:
                        kind = "tool_error"
                    try:
                        result_s = json.dumps(result, ensure_ascii=False, default=str)
                    except (TypeError, ValueError):
                        result_s = str(result)
                    steps.append({"kind": kind, "text": result_s[:4000]})
                    messages.append({"role": "assistant", "content": last_raw})
                    observation = f"<tool_result>\n{json.dumps(result)}\n</tool_result>"
                    if (
                        stage == "main_judge"
                        and tool_calls == _MAIN_TOOL_CHECKPOINT
                        and tool_budget > _MAIN_TOOL_CHECKPOINT
                    ):
                        observation += (
                            f"\nYou have used {tool_calls} of {tool_budget} private tool calls. "
                            "Conclude now if the evidence is sufficient. Continue only to resolve "
                            "one concrete fact that still changes your judgment."
                        )
                    messages.append({"role": "user", "content": observation})
                    continue
                steps.append({"kind": "assistant", "text": last_raw})
                code = _validate_stage_output(stage, obj, user)
                if code is not None:
                    return self._recover_contract(
                        system=inner_system,
                        user=user,
                        stage=stage,
                        messages=messages,
                        steps=steps,
                        first_raw=last_raw,
                        first_code=code,
                        tools_by_name=tools_by_name,
                        sandbox=sandbox,
                        tool_budget=tool_budget,
                    )
                _push_call_trace(
                    self,
                    system=inner_system,
                    user=user,
                    raw=last_raw,
                    parsed=obj,
                    steps=steps,
                )
                return obj  # 最终结构化输出（contract）

            # 查验额度与结论额度分离：工具用满不是评估失败。保留完整 tool/result 对话，
            # 再给两次明确禁用工具的结构化收口机会。
            forced_prompt = (
                f"<{stage}>\n"
                f"You have used all {tool_budget} private tool calls. No more tools are available "
                "or will be dispatched. Using only the evidence already present above, return "
                "ONLY one complete JSON object matching the exact OUTPUT CONTRACT in the original "
                f"<{stage}> prompt. Report evidence limits and tool errors honestly; do not claim "
                "anything you did not observe.\n"
                f"</{stage}>"
            )
            messages.append({"role": "user", "content": forced_prompt})
            forced_raws: list[str] = []
            last_code = "unparseable_json"
            for attempt in range(_FORCED_CONCLUSION_ATTEMPTS):
                last_raw = self._llm(messages) or ""
                forced_raws.append(last_raw)
                last_obj = _parse_json(last_raw)
                steps.append({"kind": "assistant", "text": last_raw})
                last_code = _validate_stage_output(stage, last_obj, user, tools_allowed=False) or ""
                if not last_code:
                    _push_call_trace(
                        self,
                        system=inner_system,
                        user=user,
                        raw=last_raw,
                        parsed=last_obj,
                        steps=steps,
                    )
                    return last_obj
                self._record_protocol_event(
                    stage=stage,
                    code=f"forced_conclusion_{last_code}",
                    attempt=attempt + 1,
                    raw=last_raw,
                )
                if attempt < _FORCED_CONCLUSION_ATTEMPTS - 1:
                    messages.append(
                        {
                            "role": "user",
                            "content": _contract_recovery_prompt(stage, last_code, attempt + 2)
                            + " Tool use is now forbidden; conclude from existing evidence.",
                        }
                    )
            if last_obj.get("_parse_failed"):
                _dump_unparseable(first=forced_raws[0], second=forced_raws[-1])
            _push_call_trace(
                self,
                system=inner_system,
                user=user,
                raw=last_raw,
                parsed=last_obj,
                steps=steps,
            )
            raise PersonaProtocolError(
                stage,
                f"forced_conclusion_{last_code}",
                attempts=_FORCED_CONCLUSION_ATTEMPTS,
            )
        except PersonaProtocolError:
            raise
        except Exception as exc:  # noqa: BLE001 — 转 typed evaluator error，禁止未知异常伪造 action
            _push_call_trace(
                self,
                system=inner_system,
                user=user,
                raw=last_raw,
                parsed=last_obj,
                steps=steps,
            )
            raise PersonaProtocolError(stage, f"internal_error:{type(exc).__name__}") from exc
        finally:
            sandbox.cleanup()  # 仅清自建 tempdir；外部工作区不动


def make_client() -> PersonaClient:
    """有 NexAU 网关 (USER_LLM_BASE_URL+USER_LLM_API_KEY) 或 OPENAI_API_KEY 用真实 API,
    否则回落离线脚本后端。"""
    if (os.getenv("USER_LLM_BASE_URL") and os.getenv("USER_LLM_API_KEY")) or os.getenv(
        "OPENAI_API_KEY"
    ):
        try:
            return ApiPersonaClient()
        except Exception:
            pass
    return ScriptedPersonaClient()

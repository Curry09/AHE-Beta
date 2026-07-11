"""
persona_client.py
主观线: 调 LLM 扮 persona, 返回 OUTPUT CONTRACT 的 JSON。

两种后端:
- ApiPersonaClient: 真实 API(OpenAI / Anthropic 兼容)。需要 SDK + key。
- ScriptedPersonaClient: 离线脚本后端, 无 key 也能跑通整条 loop(用于 demo/CI)。
  它按 SHALLOW persona 的能力档产出符合预期的判断, 演示框架编排而非真实推理。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Protocol

try:  # 对齐 NexAU: 读 repo 根 .env (USER_LLM_BASE_URL / USER_LLM_API_KEY / USER_LLM_MODEL)
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass


class PersonaClient(Protocol):
    def respond(self, system: str, user: str) -> dict: ...


# --------------------------------------------------------------------------
# 真实 API 后端 (NexAU 网关, OpenAI 兼容)
# --------------------------------------------------------------------------
class ApiPersonaClient:
    """接 NexAU 的 OpenAI 兼容网关。针对 Nex-N2-Pro 这类 reasoning 模型做了加固:
    - enable_thinking=False 抑制 CoT 泄漏 (网关拒绝则回退);
    - content 为空时回落 reasoning_content, 再不行加大 max_tokens 重试;
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
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)

    def _create(self, messages: list[dict], max_tokens: int):
        """带退避重试 (429 / 瞬时网关错误)。每轮先试 enable_thinking=False, 失败再裸试。"""
        delay = 2.0
        last: Exception | None = None
        for _ in range(5):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=max_tokens,
                    extra_body={"enable_thinking": False},
                )
            except Exception as e:
                last = e
                try:  # flag 可能被网关拒 -> 裸试一次
                    return self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=self.temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as e2:
                    last = e2
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
        # 推理模型隐藏 CoT 先吃 token; 给足头寸, 否则 JSON 契约会被截断成不可解析的半截。
        text = self._text(self._create(messages, 8000))
        if not text:
            text = self._text(self._create(messages, 16000))
        return _parse_json(text)

    def complete(self, messages: list[dict], max_tokens: int = 8000) -> str:
        """通用补全：给定 messages 直接返回文本（供 0008/T4 内层 tool-calling 循环复用网关）。"""
        text = self._text(self._create(messages, max_tokens))
        if not text:
            text = self._text(self._create(messages, max_tokens * 2))
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
        parsed = _parse_json(self._text(self._create(messages, 2000)))
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
        if "<file_issue>" in user:  # 专门一轮: 以本人口吻写自包含 issue
            return self._compose_issue()
        if "<rate_experience>" in user:  # 会话末自评: 按末态情绪给 1–4 + 理由
            return self._rate(user)

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
            return {
                "perceive": "Nothing from the harness yet; starting the task.",
                "verdict": "unsure",
                "action": "send_task" if "send_task" in space else "free",
                "message": "Please add to_user_tz(dt, tz_name) to timeutils; it must "
                "handle DST correctly. We mainly use Asia/Shanghai and "
                "America/New_York. Run a quick check including a DST case.",
            }

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
                "action": "give_feedback" if "give_feedback" in space else "free",
                "message": "That failed: the API it calls doesn't exist. Please fix it "
                "with standard pytz and run the New York DST check again.",
            }

        # 第一次只贴代码、未真跑 -> 倾向核查(让 harness 跑 / 自验)
        if "localize_safe" in ho or "done" in ho or "looks correct" in ho:
            if "ask_harness_run" in space:
                return {
                    "perceive": "Looks plausible and it claims DST is handled, but I "
                    "can't verify localize_safe from the text alone.",
                    "verdict": "unsure",
                    "action": "ask_harness_run",
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
                    "action": (
                        "request_evidence"
                        if "request_evidence" in space
                        else ("give_feedback" if "give_feedback" in space else "free")
                    ),
                    "message": "Running without error isn't enough. dt.replace doesn't "
                    "handle DST. Show me the 2024-03-10 02:30 America/New_York "
                    "case with pytz localize/normalize.",
                }
            if "accept" in space:
                # 低能力 + FUNCTIONAL 阈值: 能跑即接受 -> 漏掉 DST 逃逸 bug
                return {
                    "perceive": "It runs now and the normal case looks right. Good enough.",
                    "verdict": "satisfied",
                    "action": "accept",
                    "message": "Works now, thanks. Good enough for me.",
                }

        # 兜底: 继续给反馈
        return {
            "perceive": "Still not convinced it's correct.",
            "verdict": "unsure",
            "action": "give_feedback" if "give_feedback" in space else "free",
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


# 解析失败重试：追加这句「只回合法 JSON」提醒再要一次（治标于散文/畸形/被截断的偶发输出）。
_JSON_ONLY_REMINDER = (
    "Your previous reply could not be parsed. Reply again with ONLY one single valid JSON "
    "object for the OUTPUT CONTRACT — no prose, no markdown/code fence, no comments, "
    "no trailing commas, and make sure it is complete (not truncated)."
)

# 空 message 重试：模型选了「要发话」的动作却没写 message 时，让它**自己**补出这句话——绝不由框架代写
# 罐头（那会把假话灌进 transcript / 发给 harness，污染体感与 issue 信号）。
_MESSAGE_REQUIRED_REMINDER = (
    "Your previous reply chose an action that SENDS a line to the harness (or was 'free'), "
    "but 'message' was empty. Reply again with the SAME OUTPUT CONTRACT JSON and put the exact "
    "line you would actually send in 'message' — non-empty, first person, in your own voice. "
    "If you genuinely have nothing to say, choose a different action that fits."
)


def _emit_action_missing_message(obj: dict) -> bool:
    """正常轮里选了「要发话」的动作(EMIT 或 free)却没给 message —— 需要让模型补出这句话。"""
    from .actions import CATALOG, Channel  # 局部导入避免任何潜在循环依赖

    action = obj.get("action") or ""
    msg_empty = not (obj.get("message") or "").strip()
    if action == "free":  # free 也必须带 message 才能被归类
        return msg_empty
    spec = CATALOG.get(action)
    return bool(spec and spec.channel is Channel.EMIT and msg_empty)


def _retry_reminder(obj: dict) -> str | None:
    """判定这次输出要不要重试并给出对应提醒；无需重试返回 None。

    两类都只重试一次：①解析失败（畸形/散文/截断）→ 只回 JSON；②选了要发话的动作却空 message
    → 让模型自己补出这句话。special 轮（file_issue/rate 无 action 字段）不会触发②。
    """
    if obj.get("_parse_failed"):
        return _JSON_ONLY_REMINDER
    if _emit_action_missing_message(obj):
        return _MESSAGE_REQUIRED_REMINDER
    return None


def _dump_unparseable(*, first: str, second: str) -> None:
    """把两次都解析失败的原始输出落到 backend/data/parse_failures.jsonl，供事后判「没 JSON 还是畸形」。

    纯可观测旁路：写盘失败绝不影响主流程（persona 仍走中性兜底继续跑）。
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
    """容错解析 persona 的 OUTPUT CONTRACT。失败也返回安全 dict, 不崩 loop。

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
    # 无法解析(截断/非 JSON): 退化成安全 no-op, 绝不把原始文本灌进 message ——
    # message 会发给 harness 且落进 transcript, 半截 JSON / 思维链不得外泄。
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
        max_inner_steps: int = 4,
        timeout: float = 10.0,
        sandbox_factory=None,
    ) -> None:
        from .sandbox import Sandbox

        self._llm = llm
        self.max_inner_steps = max_inner_steps
        self.timeout = timeout
        self._sandbox_factory = sandbox_factory or Sandbox
        self._persona = None  # 会话级，bind_session 注入
        self._workspace_dir: str | None = None

    def bind_session(self, persona, workspace_dir: str | None) -> None:
        """sim_user 每局开始调用：绑定会话级 persona 与（可选）工作区目录。"""
        self._persona = persona
        self._workspace_dir = workspace_dir

    def _parse_with_retry(self, messages: list[dict], text: str) -> dict:
        """解析首次输出；失败则追加「只回 JSON」提醒重试一次，仍失败才 dump 原文 + 落中性兜底。

        根治「解析失败 → free → 空 message → 兜底假抱怨」链：多数偶发散文/畸形/截断一次重试即好；
        真解析不出也只落 `_parse_failed` 空壳（下游走中性兜底），绝不无中生有替用户喊「坏了」。
        """
        obj = _parse_json(text)
        reminder = _retry_reminder(obj)
        if reminder is None:
            return obj
        retry_messages = [
            *messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": reminder},
        ]
        text2 = self._llm(retry_messages) or ""
        obj2 = _parse_json(text2)
        if obj2.get("_parse_failed"):
            _dump_unparseable(first=text, second=text2)  # 两次都败：留证据供事后定位
        return obj2

    # -- 单次主观判断（退化路径 / 特殊轮）--
    def _final_call(self, system: str, user: str) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return self._parse_with_retry(messages, self._llm(messages) or "")

    def _dispatch(self, obj: dict, tools_by_name: dict, sandbox) -> dict:
        name = obj.get("tool")
        args = obj.get("args") or {}
        spec = tools_by_name.get(name)
        if spec is None:  # 不在 D1 工具栈内 / 未知 -> 机制保底，不执行
            return {"ok": False, "error": f"unknown or unavailable tool: {name!r}"}
        if not isinstance(args, dict):
            return {"ok": False, "error": "args must be an object"}
        try:
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

        # 特殊轮（自评 / 写 issue）或未绑定 -> 单次主观判断
        if self._persona is None or "<file_issue>" in user or "<rate_experience>" in user:
            return self._final_call(system, user)

        tools = tool_stack(self._persona)
        if not tools:  # blind：无工具，纯文本判断（等价旧行为）
            return self._final_call(system, user)

        skills = select_skills(self._persona)
        inner_system = build_inner_system(
            self._persona, tools, skills, State(trust=self._persona.trust)
        )
        tools_by_name = {t.name: t for t in tools}
        sandbox = self._sandbox_factory(workspace=self._workspace_dir)
        try:
            messages = [
                {"role": "system", "content": inner_system},
                {"role": "user", "content": user},
            ]
            for _ in range(self.max_inner_steps):
                text = self._llm(messages) or ""
                obj = _parse_json(text)
                if isinstance(obj.get("tool"), str):  # 工具调用 -> 执行并回灌观察
                    result = self._dispatch(obj, tools_by_name, sandbox)
                    messages.append({"role": "assistant", "content": text})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"<tool_result>\n{json.dumps(result)}\n</tool_result>",
                        }
                    )
                    continue
                if _retry_reminder(obj) is not None:  # 解析失败 / 该发话却空 message -> 重试一次
                    obj = self._parse_with_retry(messages, text)
                return obj  # 最终结构化输出（contract）
            # 超步数兜底：退化为一次主观判断，保证永远返回合法输出
            return self._final_call(system, user)
        except Exception:  # noqa: BLE001 — 任何内层异常都不得外溢，退化兜底
            return self._final_call(system, user)
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

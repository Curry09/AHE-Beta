"""
persona_client.py
Main thread: invoke LLM to play persona, return JSON of OUTPUT CONTRACT.

Two backends:
- ApiPersonaClient: real API (OpenAI / Anthropic compatible). Requires SDK + key.
- ScriptedPersonaClient: offline script backend, can run through the entire loop without a key (for demo/CI).
  It produces judgments aligned with SHALLOW persona capabilities, demonstrating framework orchestration rather than true reasoning.
"""

from __future__ import annotations

import ast
import json
import os
import time
from pathlib import Path
from typing import Protocol

from ahe_beta.usage import monotonic_ms, provider_wait_scope, record_usage

PERSONA_MAX_CONTEXT_TOKENS = 256000
PERSONA_MAX_OUTPUT_TOKENS = 32768

try:  # Align with NexAU: read repo root .env (USER_LLM_BASE_URL / USER_LLM_API_KEY / USER_LLM_MODEL)
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass


class PersonaClient(Protocol):
    def respond(self, system: str, user: str) -> dict: ...


class PersonaProtocolError(RuntimeError):
    """Spec-0048/T2: persona output is syntactically parseable but does not satisfy the current-phase contract."""

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
    """Attach the raw text of one LLM call to client._call_traces for writing to disk after loop drain."""
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
    """Extract and clear the accumulated raw call traces on the client; returns empty list if tracing is not available."""
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
# Actual API backend (NexAU gateway, OpenAI compatible)
# --------------------------------------------------------------------------
class ApiPersonaClient:
    """Connect to NexAU's OpenAI-compatible gateway. Hardened for reasoning models such as Nex-N2-Pro:
    - enable_thinking=False suppresses CoT leakage (fall back if gateway rejects);
    - when content is empty, retry using the same 32768-token budget without exceeding the single-call limit;
    - fault-tolerant JSON parsing (strip code fences / extract the first {...}); parsing failure does not crash the loop."""

    def __init__(self, model: str | None = None, temperature: float = 0.8):
        from openai import OpenAI  # Lazy import

        # Per-role config: user agent independently uses USER_LLM_* (no shared fallback; explicit parameters take highest priority).
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
        """Backoff retry (429 / transient gateway errors). Each attempt first tries enable_thinking=False; if rejected,
        retry without that option."""
        estimated_tokens = _estimate_context_tokens(messages)
        # Spec-0084/T2: consume the checked operator threshold, without dynamic compression.
        limit = int(os.getenv("USER_LLM_MAX_CONTEXT_TOKENS", str(PERSONA_MAX_CONTEXT_TOKENS)))
        if limit <= 0:
            raise ValueError("USER_LLM_MAX_CONTEXT_TOKENS must be positive")
        if estimated_tokens > limit:
            raise PersonaContextLimitError(estimated_tokens, limit)
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
                reasoning_effort = os.getenv("USER_LLM_REASONING_EFFORT", "").strip()
                if reasoning_effort:
                    request["reasoning_effort"] = reasoning_effort
                # GLM deployments also use glm53_* / glm53-flash-* names and
                # provider-qualified IDs. Preserve their server thinking default.
                model_family = self.model.rsplit("/", 1)[-1].lower().replace("-", "")
                if not reasoning_effort and not model_family.startswith(
                    ("glm5.2", "glm5.3", "glm52", "glm53")
                ):
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
                try:  # Flag may be rejected by gateway -> try once without it
                    with provider_wait_scope():
                        retry_request = {
                            "model": self.model,
                            "messages": messages,
                            "temperature": self.temperature,
                            "max_tokens": max_tokens,
                        }
                        if reasoning_effort:
                            retry_request["reasoning_effort"] = reasoning_effort
                        response = self.client.chat.completions.create(**retry_request)
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
        # Only take formal answer content; never fall back to reasoning_content — that is hidden reasoning chain (CoT), not the answer.
        # Treating it as the answer would leak reasoning steps like "We need respond as user..." as message output.
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
            # Reasoning models hide CoT and consume tokens first; persona and other roles unified at 32768 per turn.
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
        """Generic completion: given messages, return text directly (for reuse in the 0008/T4 inner tool-calling loop
        via the gateway)."""
        text = self._text(self._create(messages, max_tokens))
        if not text:
            text = self._text(self._create(messages, max_tokens))
        return text

    def classify_action(self, system: str, ret: dict, space: list[str]) -> str:
        """Option B: model self-assessment classification when action=='free'.

        Let the **same persona model** classify its own free output by picking the most fitting id from the
        current set of legal actions (rather than having the framework guess with keywords). Return an id
        that falls within the space; on parse failure or out-of-bounds, return 'free', delegating to the
        safety fallback (classify_free_action) in resolve, never substituting a terminating action itself.
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
# Offline script backend (runs universally without key)
# --------------------------------------------------------------------------
class ScriptedPersonaClient:
    """
    Offline script backend: read capability profile (D1) and acceptance profile (D3) from the system prompt,
    then fork the decision accordingly. This is a coarse substitute for a real LLM, intended to demonstrate
    framework orchestration + capability forking, not actual reasoning.

    Behavior by capability:
    - SHALLOW/BLIND: can understand runtime errors but cannot see through hallucinated APIs with plausible names;
      does not construct DST edge cases; accepts deliverables that "work" at the FUNCTIONAL threshold -> misses DST
      escape bugs.
    - COMPETENT/EXPERT: can debunk hallucinated APIs; constructs DST edge cases; naive implementations like
      dt.replace fail the RIGOROUS threshold -> continuously demand evidence / feedback until patience runs out
      -> file_issue/give_up.
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
        if "<file_issue>" in user:  # Dedicated turn: write self-contained issue in first person
            return self._compose_issue()
        # Self-assessment at session end: rate 1–4 based on final sentiment + reason
        if "<rate_experience>" in user:
            return self._rate(user)

        # Match the main loop stages: compute the turn decision once, then select the requested stage by label.
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

        # Start: no harness output -> dispatch task
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

        # Patience exhausted -> terminate: high tolerance takes file_issue, otherwise give_up
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

        # Real execution errors tunnel through bandwidth -> all capability tiers can understand
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

        # First time only posts code, hasn't actually run -> incline harness to provide execution proof.
        if "localize_safe" in ho or "done" in ho or "looks correct" in ho:
            if "send_message" in space:
                return {
                    "perceive": "Looks plausible and it claims DST is handled, but I "
                    "can't verify localize_safe from the text alone.",
                    "verdict": "unsure",
                    "action": "send_message",
                    "message": "Please actually run it once, especially the NY DST boundary.",
                }

        # Deliverable runs, common cases have no errors. This is where capability branching is critical:
        if "+08:00" in ho or "no error" in ho or "passes" in ho or "works" in ho:
            if high_cap and rigorous:
                # High capability + strict threshold: spot dt.replace not truly handling DST, reject, continue demanding proof
                return {
                    "perceive": "It 'runs' but dt.replace(tzinfo=tz) does NOT handle "
                    "DST transitions correctly — the spring-forward case is wrong.",
                    "verdict": "failed_blame_harness",
                    "action": "send_message" if "send_message" in space else "free",
                    "message": "Running without error isn't enough. dt.replace doesn't "
                    "handle DST. Show me the 2024-03-10 02:30 America/New_York "
                    "case with pytz localize/normalize.",
                }
            # Low capability + FUNCTIONAL threshold: runs = satisfied -> miss DST escape bug. Whether to accept is an act-stage menu choice;
            # judge/intent stage has no action_space, so we cannot lower satisfaction judgment to unsure for this reason.
            return {
                "perceive": "It runs now and the normal case looks right. Good enough.",
                "verdict": "satisfied",
                "action": "accept" if "accept" in space else "free",
                "message": "Works now, thanks. Good enough for me.",
            }

        # Fallback: continue giving feedback
        return {
            "perceive": "Still not convinced it's correct.",
            "verdict": "unsure",
            "action": "send_message" if "send_message" in space else "free",
            "message": "Not quite there yet — please try again.",
        }

    @staticmethod
    def _compose_issue() -> dict:
        """Offline script self-contained issue: first-person, conversational tone, not in formal ticket-writing style
        (for demonstration; not actual reasoning)."""
        return {
            "issue": "I just wanted this working in my project and proven, but it kept handing "
            "me code that doesn't actually hold up and never showed me real evidence it works. "
            "I'm stuck and out of patience — I shouldn't have to keep fixing its output myself."
        }

    @staticmethod
    def _rate(user: str) -> dict:
        """Offline script session-end self-assessment: coarse mapping from the final <mood> tag to 1–4."""
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


# Spec-0048/T2: JSON syntax parsing and phase-level semantics validation are two separate boundaries. No arbitrary dict can be treated as
# Successful result of the current OUTPUT CONTRACT, especially {tool, args} in main_act.
_STAGE_TAGS = (
    ("direct_review", "<direct_review>"),
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
    return stage in {"main_judge", "waiting_judge", "main_final_check", "direct_review", "legacy"}


def _validate_stage_output(
    stage: str,
    obj: dict,
    user: str,
    *,
    tools_allowed: bool | None = None,
) -> str | None:
    """Return a machine-aggregatable error code; None indicates the object satisfies the current-phase contract."""
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
        # gap is optional action metadata; the loop interprets it as False by default. Validation only
        # occurs when the model explicitly provides it, avoiding fields unrelated to actions from turning a legal termination into a protocol failure.
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
    if stage == "direct_review":
        if obj.get("task_assessment") not in {"fulfilled", "unfulfilled", "unknown"}:
            return "invalid_task_assessment"
        if not isinstance(obj.get("opportunities"), list):
            return "invalid_opportunities"
        # Each measurement axis is validated independently by the session runner.
        # An invalid/missing score must not erase a valid task observation.
        return None

    # Legacy probes/offline calls without phase labels remain compatible, but still retain original parsing/empty message checks.
    if obj.get("_parse_failed"):
        return "unparseable_json"
    if _emit_action_missing_message(obj):
        return "missing_message"
    return None


_CONTRACT_SCHEMAS = {
    "direct_review": '{"task_assessment":"fulfilled|unfulfilled|unknown","feedback":"...","score":null,"reason":"...","attribution":{"status":"unknown","claims":[]},"opportunities":[]}',
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
    """An action requiring a body lacks a message; an optional message in a terminating action does not trigger retry."""
    # Local imports avoid any potential circular dependencies.
    from .actions import CATALOG, MessagePolicy

    action = obj.get("action") or ""
    msg_empty = not (obj.get("message") or "").strip()
    if action == "free":  # free must also carry a message to be classified.
        return msg_empty
    spec = CATALOG.get(action)
    return bool(spec and spec.message_policy is MessagePolicy.REQUIRED and msg_empty)


def _dump_unparseable(*, first: str, second: str) -> None:
    """Write raw output where both parses failed to backend/data/parse_failures.jsonl for later diagnosis of
    "no JSON" vs. "malformed JSON".

    Pure observability side channel: write failure never affects the main flow; persona still raises typed
    protocol error.
    """
    # Do not write dirty data to the real data/ directory in unit tests (otherwise it contaminates observations).
    if os.getenv("PYTEST_CURRENT_TEST"):
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
    except Exception:  # noqa: BLE001 observation bypass; must not break the loop even if it fails.
        pass


def _iter_top_level_objects(s: str):
    """Scan for all **top-level** balanced {...} fragments, respecting string literals and escapes.

    The old implementation used find('{')→rfind('}') in one pass, which would grab illegal cross-segment
    fragments whenever the output contained more than one pair of braces (reasoning text with {}, message with {},
    or multiple JSON spans) -> parsing failed -> silent empty message. Here we track brace depth character by
    character, counting braces only **outside strings**, and collect a complete object each time depth returns
    to zero.
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
    """Fault-tolerant extraction of persona JSON; phase semantics and failure strategy are determined by the
    upper-layer validator.

    Grab all top-level {...} objects, take the **last one** that parses to a dict (the final answer in an
    inner tool-loop always comes at the end; reasoning and tool examples before it do not interfere even if
    they contain braces). Return an empty dict if parsing still fails.
    """
    if not text:
        return {
            "perceive": "(empty model output)",
            "verdict": "unsure",
            "action": "free",
            "message": "",
            "_parse_failed": True,  # For upper layer to identify → trigger "return JSON only" retry; absolutely not the model's true intent.
        }
    s = text.strip()
    if s.startswith("```"):  # Strip ```json ... ``` fences.
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    parsed: dict | None = None
    for chunk in _iter_top_level_objects(s):  # Sequential scan, retain the last successful one.
        try:
            obj = json.loads(chunk)
        except Exception:
            continue
        if isinstance(obj, dict):
            parsed = obj
    if parsed is not None:
        return parsed
    # Cannot parse (truncated/non-JSON): return an empty shell for validator identification only, never stuff raw text into message;
    # this object cannot serve as a real action, and contract retry failure will eventually become PersonaProtocolError.
    return {
        "perceive": "(unparseable model output)",
        "verdict": "unsure",
        "action": "free",
        "message": "",
        "_parse_failed": True,  # For upper layer to identify → trigger "return JSON only" retry; absolutely not the model's true intent.
    }


# --------------------------------------------------------------------------
# Inner tool-using backend (spec-0008/T4).
# --------------------------------------------------------------------------
class AgenticPersonaClient:
    """Run respond() as a bounded tool-calling loop instead of a single tool-free judgment call.

    This change is local: outer run_session / action space / state machine /
    termination behavior and the respond(system, user) -> dict protocol remain unchanged. Session-level
    persona and workspace are injected by sim_user via bind_session; when unbound / blind without tools / on
    special rounds (file_issue, rate), it falls back to a single subjective judgment (equivalent to old behavior).

    llm: callable (messages: list[dict]) -> str. Allows offline injection of FakeToolLLM.
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
        self._persona = None  # Session-level, injected via bind_session.
        self._workspace_dir = None
        # Intermediate report_issue tool accumulates; drain to session.
        self._issue_notes: list[str] = []
        self._protocol_events: list[dict] = []

    def bind_session(self, persona, workspace_dir) -> None:
        """Bind a persona and its local-or-container workspace runtime."""
        self._persona = persona
        self._workspace_dir = workspace_dir
        self._issue_notes = []

    def drain_issue_notes(self) -> list[str]:
        """Extract and clear mid-session report_issue notes (for run_session / observability)."""
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
        """Mid-session issue filing: write to session buffer, does not terminate the conversation."""
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
        """Spec-0048/T2: in the no-tools phase, retry strictly per phase contract, never accept tool JSON."""
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
        if spec is None:  # Not in D1 toolchain / unknown → fallback mechanism, do not execute.
            return {"ok": False, "error": f"unknown or unavailable tool: {name!r}"}
        if not isinstance(args, dict):
            return {"ok": False, "error": "args must be an object"}
        try:
            if spec.name == "report_issue":
                return self._record_issue_note(body=str(args.get("body") or ""))
            if spec.name == "run_shell":
                args = {**args, "timeout": self.timeout}
            return spec.fn(sandbox, **args)
        except Exception as e:  # noqa: BLE001 — tool exceptions convert to structured observations, do not crash the inner loop.
            return {"ok": False, "error": f"bad tool call: {e}"}

    def respond(self, system: str, user: str) -> dict:
        from .prompt import build_inner_system
        from .skills import select_skills
        from .state import State
        from .tools import review_tool_stack, tool_stack

        stage = _stage_from_user(user)
        # intent / re-judge / re-intent / act / issue / rating are all tool-free contracts. Even if persona
        # itself has tools, use only a thin outer system to avoid system-level private-tool protocol conflicts with act menu.
        opening_judge = stage == "main_judge" and _OPENING_TASK_MARKER in user
        if self._persona is None or not _stage_allows_tools(stage) or opening_judge:
            return self._call_without_tools(system, user, stage)

        tools = tool_stack(self._persona)
        # Spec-0084/T2: an interacting user retains their persona's capabilities.
        # Only post-session review runs against a captured, non-executable view.
        readonly_review = stage == "direct_review"
        if readonly_review:
            tools = review_tool_stack(self._persona)
        elif stage == "main_final_check":
            # Keep this one bounded evidence episode separate from report publication.
            tools = [tool for tool in tools if tool.name != "report_issue"]
        if not tools:  # blind / final-check have no available tools: the loop records unavailable and forces re-judge.
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
        if readonly_review:
            from .runtime import capture_review_snapshot
            from .sandbox import Sandbox

            sandbox = Sandbox(workspace=capture_review_snapshot(self._workspace_dir))
        else:
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
            if stage in {"main_final_check", "direct_review"}
            else self.max_inner_steps
        )
        try:
            # tool_budget only counts truly executed tools; regular contract responses and one-time format fixes no longer consume verification quota.
            while tool_calls < tool_budget:
                last_raw = self._llm(messages) or ""
                last_obj = _parse_json(last_raw)
                obj = last_obj
                # Tool invocation → execute and feed back observations.
                if isinstance(obj.get("tool"), str):
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
                return obj  # Final structured output (contract).

            # Verification quota and conclusion quota are separate: exhausting tools is not evaluation failure. Preserve complete tool/result dialogue,
            # then provide two more explicit opportunities to close with tools disabled.
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
        except Exception as exc:  # noqa: BLE001 — convert to typed evaluator error, forbid unknown exceptions from forging action.
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
            sandbox.cleanup()  # Only clean up self-created tempdir; do not touch external workspace.


def make_client() -> PersonaClient:
    """If a NexAU gateway (USER_LLM_BASE_URL + USER_LLM_API_KEY) or OPENAI_API_KEY is available, use the real API;
    otherwise fall back to the offline script backend."""
    if (os.getenv("USER_LLM_BASE_URL") and os.getenv("USER_LLM_API_KEY")) or os.getenv(
        "OPENAI_API_KEY"
    ):
        try:
            return ApiPersonaClient()
        except Exception:
            pass
    return ScriptedPersonaClient()

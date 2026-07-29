"""harness 多轮对话契约 HarnessInterface + 测试后端 FakeHarness（spec-0001/T2）。

用户侧仅依赖该协议，不感知 harness 内部（单/多 nexau 由其入口编排，真实后端 launcher 见 spec-0003）。
协议三方法 send/reset/close，合法生命周期 (reset? · send* · close)。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

# 未注入 script/callback 时的固定占位回复。
_PLACEHOLDER = "[fake-harness] no reply configured"


@runtime_checkable
class HarnessInterface(Protocol):
    """与 harness 的黑盒多轮对话协议（结构化子类型）。

    可选鸭子属性 `help_text: str`（该版本 harness 的 HELP.md 全文）：真实 launcher
    句柄与 FakeHarness 都带它，但**不列入协议成员**——runtime_checkable 会把数据成员纳入 isinstance 校验，
    列进来会让没有该属性的老桩失配。读方一律 `getattr(harness, "help_text", "")` 兜底，老后端也安全。
    """

    def send(self, message: str) -> str:
        """发送一条用户消息，返回 harness 本轮完整回复（非流式，单次整段 str；可为空串）。"""
        ...

    def reset(self) -> None:
        """丢弃当前会话状态，回到新一局起点。幂等。"""
        ...

    def close(self) -> None:
        """释放后端资源。幂等。"""
        ...


class FakeHarness:
    """测试后端：以 script（按序弹出）或 callback（动态产回复）注入确定性回复，二者互斥。

    记录收到的 message 序列（sent）供断言。close 后 send/reset 抛 RuntimeError。
    """

    def __init__(
        self,
        script: list[str] | None = None,
        callback: Callable[[str], str] | None = None,
    ) -> None:
        if script is not None and callback is not None:
            raise ValueError("script 与 callback 互斥，构造时只能择一")
        self._script = list(script) if script is not None else None
        self._callback = callback
        self._cursor = 0
        self._sent: list[str] = []
        self._closed = False
        self.help_text = ""  # 测试后端默认无帮助文本；需要时调用方直接赋值

    @property
    def sent(self) -> list[str]:
        """只读：收到的全部 message 序列。"""
        return list(self._sent)

    def send(self, message: str) -> str:
        self._ensure_open()
        self._sent.append(message)
        if self._callback is not None:
            return self._callback(message)
        if self._script is not None:
            reply = self._script[self._cursor]  # 耗尽则 IndexError，暴露轮数设定不足
            self._cursor += 1
            return reply
        return _PLACEHOLDER

    def reset(self) -> None:
        self._ensure_open()
        self._sent.clear()
        self._cursor = 0

    def close(self) -> None:
        self._closed = True  # 幂等：重复 close 不报错

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("FakeHarness 已关闭，不可再 send/reset")

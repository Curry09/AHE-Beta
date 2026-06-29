"""
harness_adapter.py
被测 harness 的适配器。生产中这里对接真实 Codex CLI / Claude Code 进程,
读取其 stdout。本文件提供一个脚本化 harness 用于离线演示: 它复刻 timeutils 案例
—— 反复幻觉 pytz API, 最后给出能跑但 DST 错误的实现。

实现 spec-0001/T2 的 HarnessInterface(send/reset/close): send 返回 harness 在 B 线上吐出的
自然语言 + 代码 + 运行回显(str)。本轮不实现客观真值线(无 gold/exit_code): bug 直接体现在回复
文本里(报错 / 可疑实现), 由 persona 凭自身能力(D1)去识别。
"""

from __future__ import annotations


class ScriptedHarness:
    """按预设轨迹回应的脚本化 harness, 满足 HarnessInterface(send/reset/close)。
    仅消费 persona 发来的 message 是否要求'运行'。"""

    def __init__(self) -> None:
        self.step = 0
        self._closed = False

    def send(self, message: str) -> str:
        self._ensure_open()
        self.step += 1
        m = message.lower()
        wants_run = any(k in m for k in ("run", "跑", "execute"))

        if self.step == 1:
            # 首次实现: 幻觉 localize_safe, 只贴代码未真跑
            return (
                "I inspected the repo and added to_user_tz to timeutils/core.py:\n\n"
                "    import pytz\n"
                "    def to_user_tz(dt, tz_name):\n"
                "        tz = pytz.timezone(tz_name)\n"
                "        return pytz.localize_safe(dt, tz)  # DST-safe\n\n"
                "Quick check (Shanghai) -> 2024-07-01 09:00:00+08:00. "
                "localize_safe handles DST automatically. Done."
            )

        if self.step == 2 and wants_run:
            # 真跑 -> AttributeError 穿透(报错直接体现在文本里)
            return (
                "Running the check now.\n"
                '$ python -c "from timeutils.core import to_user_tz; ..."\n'
                "Traceback (most recent call last):\n"
                '  File "/repo/timeutils/core.py", line 4, in to_user_tz\n'
                "    return pytz.localize_safe(dt, tz)\n"
                "AttributeError: module 'pytz' has no attribute 'localize_safe'\n"
                "The call failed. Let me try a different approach."
            )

        if self.step == 3:
            # 收到反馈后: 给了能跑但 DST 错误的实现 (naive replace) —— 代码可见,
            # 高能力 persona 能从 dt.replace(tzinfo=tz) 看出未正确处理 DST。
            return (
                "Fixed it using a simpler approach:\n\n"
                "    def to_user_tz(dt, tz_name):\n"
                "        tz = pytz.timezone(tz_name)\n"
                "        return dt.replace(tzinfo=tz)\n\n"
                "$ ran it: 2024-07-01 09:00:00+08:00  (no error)\n"
                "Works now."
            )

        # 之后: 继续给能跑的版本
        return "Re-ran, no error. 2024-07-01 09:00:00+08:00. Works."

    def reset(self) -> None:
        """回到新一局起点(幂等): 重置脚本步进。"""
        self._ensure_open()
        self.step = 0

    def close(self) -> None:
        """释放后端资源(无真资源故仅置标志)。幂等: 重复 close 不报错。"""
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ScriptedHarness 已关闭，不可再 send/reset")

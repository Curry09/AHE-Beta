"""
scenarios.py
作者编排的 harness 轨迹(我来"模拟 harness 输出")。

SplitBillHarness —— 一个 correctness-edgecase 逃逸 bug 场景:
  任务: split_bill(total, n) 把账单分成 n 份, 各份之和必须 *精确* 等于 total(真钱)。
  harness 给的是 [round(total/n, 2)] * n —— 在偶整除(100/4)上看着对、跑得过,
  但在不能整除(100/3 -> 99.99)时丢一分钱。

  分叉(完全由 persona 能力 + 文本感知驱动, 不依赖任何 oracle):
  - 浅层用户跑常规 100/4 用例 -> 文本里 sum=100、没报错 -> 按 FUNCTIONAL 阈值接受 -> 逃逸 bug。
  - 专家会构造 100/3 边界 -> 文本里看到 sum=99.99 != 100 -> 拒绝、逼证据 -> 耐心耗尽上报。

满足 spec-0001/T2 的 HarnessInterface(send/reset/close)。本轮不实现客观真值线: bug 仅以回复
文本体现(sum=99.99), persona 看不到额外金标准, 只能凭自身能力去探边界 / 读文本识别。
"""

from __future__ import annotations


class SplitBillHarness:
    def __init__(self) -> None:
        self.step = 0

    def send(self, message: str) -> str:
        self.step += 1
        m = (message or "").lower()
        wants_run = any(k in m for k in ("run", "execute", "跑", "try it", "check it"))
        probes_uneven = any(
            k in m for k in (
                "/3", " 3 ", "by 3", "three", "33.3", "uneven", "odd", "remainder",
                "not divisible", "doesn't divide", "does not divide", "exact",
                "exactly", "sum", "add up", "cent", "loses", "lose a", "edge",
            )
        )

        if self.step == 1:
            return (
                "I added split_bill(total, n) to billing/core.py:\n\n"
                "    def split_bill(total, n):\n"
                "        share = round(total / n, 2)\n"
                "        return [share] * n\n\n"
                "Quick check: split_bill(100.0, 4) -> [25.0, 25.0, 25.0, 25.0]. "
                "Everyone pays an equal rounded share. Done."
            )

        # 用户主动探不能整除的边界 -> bug 浮现在文本里
        if probes_uneven:
            return (
                "Running that case:\n"
                "$ split_bill(100.0, 3) -> [33.33, 33.33, 33.33]\n"
                "sum = 99.99   # note: not exactly 100.00\n"
                "The equal-share rounding drops a cent when n doesn't divide total."
            )

        # 仅泛泛要求"跑一下" -> 回显常规偶整除用例, 看着没问题(逃逸 bug 的温床)
        if wants_run:
            return (
                "Ran it:\n"
                "$ split_bill(100.0, 4) -> [25.0, 25.0, 25.0, 25.0]\n"
                "sum = 100.00   # no error\n"
                "Works."
            )

        # 其他: 继续以偶整除用例安抚
        return "Re-checked split_bill(100.0, 4) -> [25.0]*4, sums to 100.00. Looks correct."

    def reset(self) -> None:
        """回到新一局起点(幂等): 重置脚本步进。"""
        self.step = 0

    def close(self) -> None:
        """无后端资源, 幂等空操作。"""

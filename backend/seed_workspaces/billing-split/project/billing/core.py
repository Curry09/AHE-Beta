"""最小账单模块基线（seed 工作区 billing-split / spec-0008/T1）。

这是用户项目里**已有的基线**：一个可 import、可运行的 stdlib-only 模块，
但**故意不含任何分账实现**——分账逻辑（split_bill）是会话里要让助手新增、
并由用户在本工作区自行核实的目标。不含 gold / 答案（held-out 红线）。
"""

from __future__ import annotations


def format_amount(cents: int) -> str:
    """把「分」格式化为金额字符串（如 1234 -> '12.34'）。基线里已有的小工具。"""
    return f"{cents / 100:.2f}"


if __name__ == "__main__":
    # 基线自检：模块可直接运行（供 sandbox / materialize 测试断言其可跑）。
    print("billing module baseline ok:", format_amount(1234))

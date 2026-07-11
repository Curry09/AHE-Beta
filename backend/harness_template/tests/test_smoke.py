"""harness v0 冒烟自测：入口可导入、核心编排函数在位、协议常量成形。

这是 harness **自身**的回归测试起手式，也是 `tests/` 目录的约定示范：
- 只放 harness 本体（entry.py / agents / tools / 配置）的测试；仓边界钩子允许 `tests/`，
  但**绝不放被测任务的项目或测试代码**（那些代码本就进不了本仓，也是过拟合）。
- 改 entry.py 的对外行为时，在这里补对应的**确定性**回归（如超时/打断的回复形状、
  JSONL 协议一读一写配对），用廉价 mock，别整篇重放难任务。

entry.py 顶层只依赖标准库（nexau 在函数内懒加载），故可安全 `import entry`。
跑法（仓根）：`python3 -m unittest -v tests/test_smoke.py`。
"""

from __future__ import annotations

import importlib
import unittest


class HarnessSmokeTest(unittest.TestCase):
    def test_entry_imports_and_exposes_core_surface(self) -> None:
        """入口可导入且核心编排函数在位——挡住语法错误 / 误删核心函数。"""
        entry = importlib.import_module("entry")
        for name in ("main", "_reply", "_run_supervised", "_setup_workspace"):
            self.assertTrue(callable(getattr(entry, name, None)), f"entry.{name} 应可调用")

    def test_interrupt_reply_is_marked(self) -> None:
        """打断回复带 [interrupted] 标记且非空——协议契约的最小成形检查。"""
        entry = importlib.import_module("entry")
        self.assertTrue(entry._INTERRUPT_REPLY.startswith("[interrupted]"))


if __name__ == "__main__":
    unittest.main()

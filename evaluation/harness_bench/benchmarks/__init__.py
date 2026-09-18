"""Official benchmark metadata and grader adapters."""

from .base import BenchmarkPlugin, BudgetResolution, CaseSpec, GraderPlan
from .swebench import SweBenchPlugin
from .tau3 import Tau3Plugin
from .terminal_bench import TerminalBenchPlugin
from .tua_bench import TuaBenchPlugin

PLUGINS = {
    "SWE-bench Verified": SweBenchPlugin(),
    "Terminal-Bench 4.0": TerminalBenchPlugin(),
    "TUA-Bench": TuaBenchPlugin(),
    "tau3-bench Core/Text": Tau3Plugin(),
}


def get_plugin(name: str) -> BenchmarkPlugin:
    try:
        return PLUGINS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported benchmark: {name}") from exc


__all__ = [
    "BenchmarkPlugin",
    "BudgetResolution",
    "CaseSpec",
    "GraderPlan",
    "get_plugin",
]

"""Explicit versioned built-ins; no runtime Python plugins (Spec-0083/T1)."""

from __future__ import annotations

from .contracts import GradingAdapter

BUILTIN_VERSIONS = {
    "swebench": 1,
    "terminal-bench": 1,
    "tua-bench": 1,
    "nl2repo": 1,
    "custom": 1,
}


def get_adapter(name: str, contract_version: int = 1) -> GradingAdapter:
    if name not in BUILTIN_VERSIONS:
        raise ValueError(f"unsupported grading adapter: {name}")
    if type(contract_version) is not int or contract_version != BUILTIN_VERSIONS[name]:
        raise ValueError(f"unsupported {name} contract version: {contract_version}")
    from .adapters.custom import CustomAdapter
    from .adapters.nl2repo import NL2RepoAdapter
    from .adapters.swebench import SWEbenchAdapter
    from .adapters.terminal_bench import TerminalBenchAdapter
    from .adapters.tua_bench import TUABenchAdapter

    return {
        "swebench": SWEbenchAdapter,
        "terminal-bench": TerminalBenchAdapter,
        "tua-bench": TUABenchAdapter,
        "nl2repo": NL2RepoAdapter,
        "custom": CustomAdapter,
    }[name]()

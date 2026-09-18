from __future__ import annotations

from pathlib import Path

from evaluation.harness_bench.benchmarks.tau3 import Tau3Plugin
from evaluation.harness_bench.benchmarks.terminal_bench import TerminalBenchPlugin
from evaluation.harness_bench.schema import CaseRef, InteractionMode


def test_terminal_plugin_reads_official_budgets(tmp_path: Path) -> None:
    (tmp_path / "instruction.md").write_text("do the task", encoding="utf-8")
    (tmp_path / "task.toml").write_text(
        """
artifacts = ["/app/output.txt"]
[agent]
timeout_sec = 7200
[verifier]
timeout_sec = 60
[environment]
build_timeout_sec = 600
cpus = 2
memory_mb = 4096
storage_mb = 10240
""".strip(),
        encoding="utf-8",
    )
    case = CaseRef("Terminal-Bench 4.0", "demo", "rev", "digest", str(tmp_path))

    resolved = TerminalBenchPlugin().resolve_case(case, 1800)

    assert resolved.budget.agent_timeout_seconds == 7200
    assert resolved.budget.agent_source == "official_task_metadata"
    assert resolved.grader.timeout_seconds == 60
    assert resolved.grader.submission_paths == ("/app/output.txt",)


def test_tau3_uses_1800_fallback_and_native_user_only() -> None:
    case = CaseRef("tau3-bench Core/Text", "retail/76", "rev", "digest")
    resolved = Tau3Plugin().resolve_case(case, 1800)

    assert resolved.budget.agent_timeout_seconds == 1800
    assert resolved.budget.agent_source == "fallback_no_official_timeout"
    assert resolved.supported_interactions == frozenset({InteractionMode.BENCHMARK_NATIVE})

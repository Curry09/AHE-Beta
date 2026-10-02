#!/usr/bin/env python3
"""Run the nine non-tau tasks with one generated LLM user follow-up."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from adapters.harness_v0.llm_user_simulator import generate_followup
from daytona_common import load_env, safe_run_label, sha256_file

HERE = Path(__file__).resolve().parent
CASE_BATCHES = (
    (("run_daytona_harnessv0_requests6028.py", "--llm-user-simulator"),),
    (
        ("run_daytona_terminal_preflight.py", "--llm-user-simulator"),
        ("run_daytona_tua_preflight.py", "--llm-user-simulator"),
    ),
    (
        ("run_daytona_swe_case.py", "astropy__astropy-12907", "--llm-user-simulator"),
        ("run_daytona_terminal_case.py", "music-harmony", "--llm-user-simulator"),
    ),
    (
        ("run_daytona_swe_case.py", "django__django-15957", "--llm-user-simulator"),
        ("run_daytona_terminal_case.py", "production-planning", "--llm-user-simulator"),
    ),
    (
        ("run_daytona_tua_case.py", "010-pivot-product-revenue", "--llm-user-simulator"),
        ("run_daytona_tua_case.py", "080-convert-novel-epub", "--llm-user-simulator"),
    ),
)


async def run_case(index: int, total: int, argv: tuple[str, ...], env: dict[str, str]) -> int:
    name = f"{index + 1:02d}-{'-'.join(argv[1:])}"
    log_path = (
        HERE
        / "runs"
        / (
            f"controller-llm-user-{safe_run_label(env['HARNESS_EVAL_LABEL'])}-"
            f"{safe_run_label(env['HARNESS_MODEL'])}-{name}.log"
        )
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(HERE / argv[0]), *argv[1:]]
    print(f"CASE_START {index + 1}/{total} {' '.join(argv)}", flush=True)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=HERE,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    with log_path.open("w", encoding="utf-8") as stream:
        async for raw in process.stdout:
            output = raw.decode(errors="replace")
            stream.write(output)
            stream.flush()
            print(f"[{index + 1}] {output}", end="", flush=True)
    code = await process.wait()
    print(f"CASE_END {index + 1}/{total} exit={code} log={log_path}", flush=True)
    return code


def preflight_user_model(model: str) -> None:
    values = load_env()
    key = os.environ.get("OPENROUTER_API_KEY") or values.get("openrouter_api_key")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is unavailable for model preflight")
    audit = generate_followup(
        instruction="Create /tmp/result.txt containing the word ready.",
        agent_reply="I created the requested file.",
        model=model,
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
    )
    if not audit["followup"]:
        raise SystemExit(f"user simulator preflight returned empty content for {model}")
    print(f"USER_SIMULATOR_PREFLIGHT_OK model={model}", flush=True)


async def async_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--model", default="z-ai/glm-5.2")
    parser.add_argument("--user-simulator-model", default="z-ai/glm-5.2")
    parser.add_argument(
        "--subset",
        choices=("all", "preflight", "expanded"),
        default="all",
    )
    args = parser.parse_args()
    actual = sha256_file(args.archive)
    if actual != args.sha256:
        raise SystemExit(f"harness checksum mismatch: expected {args.sha256}, got {actual}")
    preflight_user_model(args.user_simulator_model)

    env = os.environ.copy()
    env["HARNESS_ARCHIVE"] = str(args.archive.resolve())
    env["HARNESS_EVAL_LABEL"] = args.label
    env["HARNESS_MODEL"] = args.model
    env["USER_SIMULATOR_MODEL"] = args.user_simulator_model
    batches = (
        CASE_BATCHES[:2]
        if args.subset == "preflight"
        else CASE_BATCHES[2:]
        if args.subset == "expanded"
        else CASE_BATCHES
    )
    total = sum(len(batch) for batch in batches)
    exit_codes: list[int] = []
    offset = 0
    for batch in batches:
        exit_codes.extend(
            await asyncio.gather(
                *(run_case(offset + i, total, argv, env) for i, argv in enumerate(batch))
            )
        )
        offset += len(batch)
    print(f"LLM_USER_SUITE_EXIT_CODES {exit_codes}", flush=True)
    return 1 if any(code == 1 for code in exit_codes) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))

#!/usr/bin/env python3
"""Run the fixed eight-case comparison set in memory-safe Daytona pairs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from daytona_common import load_env, safe_run_label, sha256_file

HERE = Path(__file__).resolve().parent
EXPECTED_CASES = (
    ("run_daytona_swe_case.py", "astropy__astropy-12907"),
    ("run_daytona_terminal_case.py", "music-harmony"),
    ("run_daytona_swe_case.py", "django__django-15957"),
    ("run_daytona_terminal_case.py", "production-planning"),
    ("run_daytona_tau3_preflight.py", "--domain", "retail", "--task-id", "76"),
    ("run_daytona_tua_case.py", "010-pivot-product-revenue"),
    (
        "run_daytona_tau3_preflight.py",
        "--domain",
        "telecom",
        "--task-id",
        "[service_issue]overdue_bill_suspension[PERSONA:Easy]",
    ),
    ("run_daytona_tua_case.py", "080-convert-novel-epub"),
)


async def run_case(
    index: int, total: int, argv: tuple[str, ...], env: dict[str, str]
) -> int:
    name = f"{index + 1:02d}-{'-'.join(argv[1:])}"
    log_path = (
        HERE
        / "runs"
        / f"controller-{safe_run_label(env['HARNESS_EVAL_LABEL'])}-{safe_run_label(env['HARNESS_MODEL'])}-{name}.log"
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
            text = raw.decode(errors="replace")
            stream.write(text)
            stream.flush()
            print(f"[{index + 1}] {text}", end="", flush=True)
    code = await process.wait()
    print(f"CASE_END {index + 1}/{total} exit={code} log={log_path}", flush=True)
    return code


def preflight_model(model: str) -> None:
    values = load_env()
    key = os.environ.get("OPENROUTER_API_KEY") or values.get("openrouter_api_key")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is unavailable for model preflight")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Call the ping tool exactly once."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "description": "Model API preflight tool.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "tool_choice": "required",
        "max_tokens": 128,
    }
    request = Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        result = json.load(response)
    message = result["choices"][0]["message"]
    if not message.get("tool_calls"):
        raise SystemExit(f"model preflight returned no tool call for {model}")
    print(f"MODEL_PREFLIGHT_OK model={model}", flush=True)


async def async_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--model", default="z-ai/glm-5.2")
    parser.add_argument("--user-simulator-model")
    parser.add_argument(
        "--standard-input-only",
        action="store_true",
        help="exclude tau3 and run the six non-interactive tasks without strict follow-ups",
    )
    args = parser.parse_args()
    actual = sha256_file(args.archive)
    if actual != args.sha256:
        raise SystemExit(f"harness checksum mismatch: expected {args.sha256}, got {actual}")
    preflight_model(args.model)

    env = os.environ.copy()
    env["HARNESS_ARCHIVE"] = str(args.archive.resolve())
    env["HARNESS_EVAL_LABEL"] = args.label
    env["HARNESS_MODEL"] = args.model
    env["USER_SIMULATOR_MODEL"] = args.user_simulator_model or args.model
    cases = EXPECTED_CASES
    if args.standard_input_only:
        cases = tuple(
            (*case, "--standard-input-only")
            for case in EXPECTED_CASES
            if case[0] != "run_daytona_tau3_preflight.py"
        )
    total = len(cases)
    # Each pair is at most 6 GiB + 4 GiB, matching the discovered org limit.
    exit_codes: list[int] = []
    for offset in range(0, total, 2):
        pair = cases[offset : offset + 2]
        exit_codes.extend(
            await asyncio.gather(
                *(run_case(offset + i, total, argv, env) for i, argv in enumerate(pair))
            )
        )
    print(f"BATCH_EXIT_CODES {exit_codes}", flush=True)
    # Task failures are valid measurements; only controller/infrastructure exit 1 fails the batch.
    return 1 if any(code == 1 for code in exit_codes) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))

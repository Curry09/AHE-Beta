"""Durable Harbor child process; credentials are resolved only at execution."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .contracts import runtime_identity


def load_credentials(path: Path | None) -> None:
    if path:
        from dotenv import load_dotenv

        load_dotenv(path, override=True)
    # Compose interpolation happens in this controller; these keys are not
    # included in the Harness environment. Graders have separate env slots.
    if os.environ.get("JUDGE_ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["JUDGE_ANTHROPIC_API_KEY"]
    if os.environ.get("JUDGE_ANTHROPIC_BASE_URL"):
        os.environ["ANTHROPIC_BASE_URL"] = os.environ["JUDGE_ANTHROPIC_BASE_URL"]
    os.environ.setdefault("JUDGE_ANTHROPIC_API_KEY", "")
    os.environ.setdefault("JUDGE_ANTHROPIC_BASE_URL", "")
    # Claude's SDK appends /v1/messages; OpenAI-compatible env files often
    # provide a base ending in /v1. Preserve that base for frozen Harnesses.
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    os.environ.setdefault("CLAUDE_LLM_BASE_URL", base.removesuffix("/v1"))


async def main(args):
    from harbor.models.job.config import JobConfig

    from harbor.job import Job

    receipt = args.config.parent / "worker.json"
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"pid": os.getpid(), "config": str(args.config.resolve()), "actor_launches": 1})
        + "\n"
    )
    temporary.replace(receipt)
    if args.env_file and not args.env_file.is_file():
        raise ValueError("Credential file is absent")
    load_credentials(args.env_file)
    raw = json.loads(args.config.read_text())
    settings = raw.pop("evaluation_runtime", None)
    if settings:
        from evaluation.credentials import values

        values(settings, args.env_file)
    if not os.environ.get("LLM_API_KEY") or not os.environ.get("LLM_BASE_URL"):
        raise ValueError("LLM_API_KEY and LLM_BASE_URL are required")
    # Attribute verifier and ARE sidecar judge traffic to this worker only.
    trial_tag = raw["job_name"].removeprefix("trial-")
    if not settings and os.environ.get("JUDGE_ANTHROPIC_BASE_URL"):
        tagged_judge_base = (
            os.environ["JUDGE_ANTHROPIC_BASE_URL"].rstrip("/") + "/trace/" + trial_tag
        )
        os.environ["JUDGE_ANTHROPIC_BASE_URL"] = tagged_judge_base
        os.environ["ANTHROPIC_BASE_URL"] = tagged_judge_base
    if runtime_identity()["digest"] != raw.pop("integration_runtime_digest"):
        raise ValueError("Evaluation runtime differs from the frozen manifest")
    job = await Job.create(JobConfig.model_validate(raw))
    await job.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--env-file", type=Path)
    asyncio.run(main(parser.parse_args()))

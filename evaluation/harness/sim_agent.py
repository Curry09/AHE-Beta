"""Harbor integration: a host persona controls a sandbox Harness via a file relay."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import sys
import time

from e2b.exceptions import NotFoundException
from harbor.environments.base import ExecResult

from .agent import PACKAGE, FrozenHarnessAgent
from .e2b_transport import retry_transport, wait_for_same_process

RELAY = "/opt/frozen-harness/interaction"


class SimulatedUserHarnessAgent(FrozenHarnessAgent):
    def __init__(self, *args, interaction, time_adaptation=True, **kwargs):
        if type(time_adaptation) is not bool:
            raise ValueError("time_adaptation must be boolean")
        self.time_adaptation = time_adaptation
        super().__init__(*args, time_adaptation=time_adaptation, **kwargs)
        self.interaction = interaction

    async def setup(self, environment):
        await super().setup(environment)
        # Only transport code enters E2B; persona code and its credentials stay on host.
        driver = PACKAGE / "sim_driver.py"
        await environment.upload_file(driver, "/opt/frozen-harness/driver.py")
        digest = hashlib.sha256(driver.read_bytes()).hexdigest()
        check = await environment.exec(
            "printf '%s  %s\\n' " + digest + " /opt/frozen-harness/driver.py | sha256sum -c -",
            user="root",
            timeout_sec=30,
        )
        if check.return_code:
            raise ValueError("Simulator transport upload digest mismatch")

    async def execute_driver(self, environment, command, **kwargs):
        sandbox = getattr(environment, "_sandbox", None)
        if sandbox is None:
            raise ValueError("reply_then_followup_v1 currently requires native E2B")
        started = time.monotonic()
        deadline = self._task_budget.deadline
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        instruction = (self.logs_dir / "public-instruction.md").read_text()
        user_key = os.environ.get("USER_LLM_API_KEY")
        user_base = os.environ.get("USER_LLM_BASE_URL")
        if not user_key or not user_base:
            raise ValueError("Explicit USER_LLM_API_KEY and USER_LLM_BASE_URL required")
        # Deliberately create a minimal child env: no E2B, Git, judge or Harness keys.
        child_env = {
            key: os.environ[key]
            for key in (
                "PATH",
                "HOME",
                "LANG",
                "SSL_CERT_FILE",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
                "no_proxy",
            )
            if key in os.environ
        }
        child_env.update(
            {
                "USER_LLM_API_KEY": user_key,
                "USER_LLM_BASE_URL": user_base,
                "USER_LLM_MODEL": self.interaction["user_model"].removeprefix("openai/"),
                "USER_LLM_READ_TIMEOUT_SEC": str(self.request_timeout_sec),
                "USER_LLM_REASONING_EFFORT": os.environ.get("USER_LLM_REASONING_EFFORT", "max"),
                "USER_LLM_MAX_OUTPUT_TOKENS": os.environ.get("USER_LLM_MAX_OUTPUT_TOKENS", "65536"),
                "AHE_BETA_USAGE_PATH": str(self.logs_dir / "user-llm-usage.jsonl"),
                "FULL_TRACE_DIR": str(self.logs_dir / "full-call-traces/simulated-user"),
                "PYTHONUNBUFFERED": "1",
            }
        )
        stdout, stderr = [], []
        command_env = dict(
            kwargs["env"], HARNESS_FORWARD_TIME_ADAPTATION="1" if self.time_adaptation else "0"
        )
        support = getattr(environment, "support", None)
        if support:
            command = support.command(command)
            command_env = support.command_env(command_env)
        command_env = environment._merge_env(command_env)
        user = environment._resolve_user(None)
        handle = await sandbox.commands.run(
            command,
            background=True,
            envs=command_env,
            user=str(user) if user is not None else "root",
            cwd=kwargs["cwd"],
            timeout=max(1, deadline - time.monotonic()) + 120,
            on_stdout=stdout.append,
            on_stderr=stderr.append,
        )
        remote_wait = asyncio.create_task(
            wait_for_same_process(
                handle,
                sandbox.commands,
                deadline + 120,
                stdout.append,
                stderr.append,
                self.logs_dir / "e2b-transport-reconnect.jsonl",
            )
        )
        worker = None
        latest = None
        final = None
        requests = 0
        reason = None
        closed = False

        async def write_remote(name, value):
            # The reader never observes a partially written JSON record.
            path = RELAY + "/" + name
            await retry_transport(
                lambda: sandbox.files.write(
                    path + ".upload", json.dumps(value, ensure_ascii=False), request_timeout=20
                ),
                deadline + 30,
                self.logs_dir / "e2b-transport-reconnect.jsonl",
                "file_write",
            )
            move = await retry_transport(
                lambda: environment.exec(
                    "if [ -e "
                    + shlex.quote(path + ".upload")
                    + " ]; then mv -- "
                    + shlex.quote(path + ".upload")
                    + " "
                    + shlex.quote(path)
                    + "; else test -e "
                    + shlex.quote(path)
                    + "; fi",
                    timeout_sec=20,
                ),
                deadline + 30,
                self.logs_dir / "e2b-transport-reconnect.jsonl",
                "file_commit",
            )
            if move.return_code:
                raise RuntimeError("Cannot commit relay record")

        async def read_remote(name):
            while True:
                try:
                    return json.loads(
                        await retry_transport(
                            lambda: sandbox.files.read(RELAY + "/" + name, request_timeout=10),
                            deadline + 30,
                            self.logs_dir / "e2b-transport-reconnect.jsonl",
                            "file_read",
                        )
                    )
                except NotFoundException:
                    if remote_wait.done():
                        result = await remote_wait
                        raise RuntimeError(
                            f"Remote relay exited before {name}: {result.exit_code}"
                        ) from None
                    await asyncio.sleep(0.7)

        async def freeze():
            nonlocal closed
            if closed:
                return
            await write_remote("stop.json", {"stop": True})
            await asyncio.wait_for(read_remote("closed.json"), timeout=30)
            await asyncio.wait_for(asyncio.shield(remote_wait), timeout=20)
            closed = True

        async def exchange(value):
            worker.stdin.write((json.dumps(value, ensure_ascii=False) + "\n").encode())
            await worker.stdin.drain()

        async def session():
            nonlocal worker, latest, final, requests
            await read_remote("ready.json")
            worker = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                str(PACKAGE / "sim_worker.py"),
                env=child_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=(self.logs_dir / "user-worker-stderr.log").open("wb"),
                limit=16 * 1024 * 1024,
            )
            await exchange(
                {"task": instruction, "remaining_seconds": max(0.01, deadline - time.monotonic())}
            )
            with (self.logs_dir / "user-events.jsonl").open("w") as events:
                while line := await worker.stdout.readline():
                    event = json.loads(line)
                    events.write(json.dumps(event, ensure_ascii=False) + "\n")
                    events.flush()
                    kind = event["type"]
                    if kind == "request":
                        await write_remote(f"request-{requests}.json", {"text": event["text"]})
                        response = await read_remote(f"reply-{requests}.json")
                        requests += 1
                        # A user-visible read-only observation, never a hidden verifier input.
                        diff = await environment.exec(
                            "git -C "
                            + shlex.quote(self.workdir)
                            + ' diff --no-ext-diff HEAD -- . ":(exclude)bug_patch.diff"',
                            timeout_sec=15,
                        )
                        public_diff = (diff.stdout or "")[:24000]
                        response["text"] += (
                            "\n\n[Public workspace inspection: current git diff; truncated at 24000 characters]\n"
                            + public_diff
                        )
                        await exchange(response)
                    elif kind == "progress":
                        latest = event["result"]
                        (self.logs_dir / "user-session-progress.json").write_text(
                            json.dumps(latest, ensure_ascii=False, indent=2)
                        )
                    elif kind == "freeze":
                        await freeze()
                        await exchange({"frozen": True})
                    elif kind == "result":
                        final = event["result"]
            code = await worker.wait()
            if code or final is None:
                raise RuntimeError("User simulator exited without a complete result")

        try:
            await asyncio.wait_for(session(), timeout=max(0.01, deadline - time.monotonic()))
        except TimeoutError:
            reason = "official_deadline"
        except asyncio.CancelledError:
            reason = "controller_cancelled"
            raise
        except Exception as error:
            reason = "simulator_invalid:" + type(error).__name__
            self.logger.warning("User simulator failed: %s", type(error).__name__)
        finally:
            # Stop model work first, then freeze the actor before Harbor collects the patch.
            if worker is not None and worker.returncode is None:
                worker.terminate()
                try:
                    await asyncio.wait_for(worker.wait(), 5)
                except TimeoutError:
                    worker.kill()
                    await worker.wait()
            if not closed:
                try:
                    await freeze()
                except Exception:
                    # Propagate to the base class's process owner cancellation boundary.
                    if not remote_wait.done():
                        remote_wait.cancel()
                    raise
            outcome = final or {
                "evaluation_status": "invalid",
                "end_reason": reason or "simulator_invalid",
                "experience": None,
                "last_progress": latest,
                "evaluation_error": {"kind": reason or "simulator_invalid"},
            }
            record = {
                "interaction": self.interaction,
                "elapsed_seconds": time.monotonic() - started,
                "harness_requests": requests,
                "result": outcome,
                "workspace_frozen": closed,
                "deadline_seconds": self.request_timeout_sec,
                "observation_policy": "public_task_completed_replies_readonly_git_diff",
                "first_message_policy": "exact_official_instruction",
                "stop_reason": reason,
            }
            (self.logs_dir / "user-session-result.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2)
            )
        result = await remote_wait
        return ExecResult(
            return_code=result.exit_code, stdout="".join(stdout), stderr="".join(stderr)
        )

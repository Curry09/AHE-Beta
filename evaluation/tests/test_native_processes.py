"""Actual pipeline and detached-process cancellation, without model calls."""

import asyncio
import os
import shlex
import shutil
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation.harbor.agents import ClaudeCodeAgent
from evaluation.harbor.processes import CommandCleanupError, CommandProcessOwner, NativeProcessOwner

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux process ownership")


class LocalEnvironment:
    """Like the E2B wait API, cancelling a wait does not kill the command."""

    def __init__(self, delay):
        self.delay = delay
        self.processes = []
        self.tasks = []

    async def _execute(self, command, cwd, delay):
        await asyncio.sleep(delay)
        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.processes.append(process)
        stdout, stderr = await process.communicate()
        return SimpleNamespace(
            return_code=process.returncode, stdout=stdout.decode(), stderr=stderr.decode()
        )

    async def exec(self, command, user=None, env=None, cwd=None, timeout_sec=None):
        delay = self.delay if "--preserve-children-on-success" in command else 0
        task = asyncio.create_task(self._execute(command, cwd, delay))
        self.tasks.append(task)
        return await asyncio.shield(task)

    async def close(self):
        for process in self.processes:
            if process.returncode is None:
                process.kill()
        await asyncio.gather(*self.tasks, return_exceptions=True)


def actor(directory):
    owner = NativeProcessOwner.__new__(NativeProcessOwner)
    owner.root = str(directory)
    owner.python = sys.executable
    owner.logs_dir = directory
    shutil.copyfile(
        Path(__file__).parents[1] / "harness/process_runner.py", directory / "process_runner.py"
    )
    agent = ClaudeCodeAgent(logs_dir=directory, model_name="unused", version="2.1.119")
    agent._process_owner = owner
    return agent


def pipeline(directory, finish):
    pulse = directory / "pulse"
    pid = directory / "writer.pid"
    writer = (
        "import os,time;from pathlib import Path;"
        f"Path({str(pid)!r}).write_text(str(os.getpid()));counter=0\n"
        "while True:\n"
        f" Path({str(pulse)!r}).write_text(str(counter));counter+=1;time.sleep(0.02)\n"
    )
    intermediate = (
        "import subprocess,sys;subprocess.Popen([sys.executable,'-c',"
        + repr(writer)
        + "],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
        "stderr=subprocess.DEVNULL)"
    )
    primary = (
        "import subprocess,sys,time;subprocess.run([sys.executable,'-c',"
        + repr(intermediate)
        + "],check=True);time.sleep("
        + str(0.3 if finish else 30)
        + ")"
    )
    return shlex.quote(sys.executable) + " -c " + shlex.quote(primary) + " | tee /dev/null"


async def ready(path):
    deadline = asyncio.get_running_loop().time() + 5
    while not path.exists():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("Fixture did not start")
        await asyncio.sleep(0.01)


def kill_writer(directory):
    path = directory / "writer.pid"
    if path.exists():
        try:
            os.kill(int(path.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_native_cancellation_reaps_detached_pipeline_and_preserves_other_command(tmp_path):
    async def run():
        environment = LocalEnvironment(0)
        agent = actor(tmp_path)
        other = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time;time.sleep(30)"
        )
        command = asyncio.create_task(agent.exec_as_agent(environment, pipeline(tmp_path, False)))
        try:
            await ready(tmp_path / "pulse")
            command.cancel()
            with pytest.raises(asyncio.CancelledError):
                await command
            before = (tmp_path / "pulse").read_text()
            await asyncio.sleep(0.15)
            assert (tmp_path / "pulse").read_text() == before
            writer_pid = int((tmp_path / "writer.pid").read_text())
            assert not await asyncio.to_thread(Path(f"/proc/{writer_pid}").exists)
            assert other.returncode is None
        finally:
            kill_writer(tmp_path)
            other.kill()
            await other.wait()
            await environment.close()

    asyncio.run(run())


def test_native_normal_exit_preserves_intentional_background_service(tmp_path):
    async def run():
        environment = LocalEnvironment(0)
        try:
            await actor(tmp_path).exec_as_agent(environment, pipeline(tmp_path, True))
            before = (tmp_path / "pulse").read_text()
            await asyncio.sleep(0.15)
            assert (tmp_path / "pulse").read_text() != before
        finally:
            kill_writer(tmp_path)
            await environment.close()

    asyncio.run(run())


def test_frozen_command_normal_exit_reaps_detached_work(tmp_path):
    async def run():
        environment = LocalEnvironment(0)
        owner = CommandProcessOwner(str(tmp_path), sys.executable, tmp_path)
        shutil.copyfile(
            Path(__file__).parents[1] / "harness/process_runner.py", tmp_path / "process_runner.py"
        )
        wrapped, _, _ = owner.command(pipeline(tmp_path, True))
        try:
            result = await environment.exec(wrapped)
            assert result.return_code == 0
            before = (tmp_path / "pulse").read_text()
            await asyncio.sleep(0.15)
            assert (tmp_path / "pulse").read_text() == before
            writer_pid = int((tmp_path / "writer.pid").read_text())
            assert not await asyncio.to_thread(Path(f"/proc/{writer_pid}").exists)
        finally:
            kill_writer(tmp_path)
            await environment.close()

    asyncio.run(run())


def test_native_transport_failure_reaps_the_running_detached_tree(tmp_path):
    class BrokenTransport(LocalEnvironment):
        async def exec(self, command, user=None, env=None, cwd=None, timeout_sec=None):
            if "--preserve-children-on-success" not in command:
                return await super().exec(command, user, env, cwd, timeout_sec)
            self.tasks.append(asyncio.create_task(self._execute(command, cwd, 0)))
            await ready(tmp_path / "pulse")
            raise ConnectionError("remote command result stream disconnected")

    async def run():
        environment = BrokenTransport(0)
        try:
            with pytest.raises(ConnectionError, match="result stream disconnected"):
                await actor(tmp_path).exec_as_agent(environment, pipeline(tmp_path, False))
            before = (tmp_path / "pulse").read_text()
            await asyncio.sleep(0.15)
            assert (tmp_path / "pulse").read_text() == before
            writer_pid = int((tmp_path / "writer.pid").read_text())
            assert not await asyncio.to_thread(Path(f"/proc/{writer_pid}").exists)
        finally:
            kill_writer(tmp_path)
            await environment.close()

    asyncio.run(run())


def test_cancellation_before_remote_start_prevents_late_work(tmp_path):
    async def run():
        environment = LocalEnvironment(0.3)
        command = asyncio.create_task(
            actor(tmp_path).exec_as_agent(environment, pipeline(tmp_path, False))
        )
        try:
            await asyncio.sleep(0.05)
            command.cancel()
            with pytest.raises(asyncio.CancelledError):
                await command
            await asyncio.gather(*environment.tasks)
            assert not (tmp_path / "writer.pid").exists()
        finally:
            kill_writer(tmp_path)
            await environment.close()

    asyncio.run(run())


def test_uncertain_cleanup_is_not_silently_swallowed(tmp_path):
    owner = NativeProcessOwner.__new__(NativeProcessOwner)
    owner.python = sys.executable
    owner.logs_dir = tmp_path
    environment = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(return_code=1)))
    with pytest.raises(CommandCleanupError):
        asyncio.run(owner.cancel_shielded(environment, "/tmp/unused.pid", "/tmp/unused.cancel"))

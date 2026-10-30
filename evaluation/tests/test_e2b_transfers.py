"""Retained task artifacts use streaming, bounded and repeatable E2B uploads."""

import asyncio
import io
from types import SimpleNamespace

from evaluation.environments.e2b import HarnessE2BEnvironment


def test_upload_reopens_stream_after_transport_failure(tmp_path):
    data = b"retained model bytes" * 500
    source = tmp_path / "model.bin"
    source.write_bytes(data)
    calls = []
    streams = []

    async def write(path, stream, **kwargs):
        assert isinstance(stream, io.BufferedReader)
        streams.append(stream)
        calls.append((path, stream.read(), kwargs))
        if len(calls) == 1:
            raise TimeoutError("interrupted upload")

    env = HarnessE2BEnvironment.__new__(HarnessE2BEnvironment)
    env._sandbox = SimpleNamespace(files=SimpleNamespace(write=write))
    asyncio.run(env.upload_file(source, "/app/model.bin"))
    assert len(calls) == 2
    assert all(path == "/app/model.bin" and payload == data for path, payload, _ in calls)
    assert all(options["request_timeout"] == 600 for _, _, options in calls)
    assert all(stream.closed for stream in streams)
    assert source.read_bytes() == data

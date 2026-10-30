"""Small-file transport through Harbor's public provider-neutral interface."""

import tempfile
from pathlib import Path


async def read_bytes(environment, path):
    with tempfile.TemporaryDirectory(prefix="harbor-bridge-") as temporary:
        local = Path(temporary) / "payload"
        await environment.download_file(path, local)
        return local.read_bytes()


async def write_bytes(environment, path, data):
    if isinstance(data, str):
        data = data.encode()
    with tempfile.TemporaryDirectory(prefix="harbor-bridge-") as temporary:
        local = Path(temporary) / "payload"
        local.write_bytes(data)
        await environment.upload_file(local, path)


async def list_requests(environment):
    result = await environment.exec(
        "find /opt/harbor-mcp/requests -maxdepth 1 -type f -name '*.json' -printf '%f\\n'",
        timeout_sec=15,
        user="root",
    )
    if result.return_code:
        raise RuntimeError("Cannot list MCP bridge requests")
    names = result.stdout.splitlines()
    if any(Path(name).name != name or not name.endswith(".json") for name in names):
        raise ValueError("Invalid bridge request filename")
    return names

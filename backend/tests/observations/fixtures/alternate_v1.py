"""A non-NexAU fixture whose behavior is observable but request ownership is not logged."""

import json
import os
import sys
from pathlib import Path

root = Path(os.environ["HARNESS_OBSERVATION_DIR"])
root.mkdir(parents=True, exist_ok=True)
(root / "READING.md").write_text(
    "v1: transitions.log records transitions, but cannot distinguish request ownership."
)
manifest = {
    "reading": "READING.md",
    "status": "partial",
    "files": [{"path": "READING.md"}, {"path": "transitions.log"}],
}
(root / "manifest.json").write_text(json.dumps(manifest))
owner = "none"
with (root / "transitions.log").open("w") as log:
    for line in sys.stdin:
        frame = json.loads(line)
        if frame["type"] == "shutdown":
            break
        message = frame.get("text", "")
        if message in {"start A", "start B"}:
            owner = message[-1]
        elif message == "cancel":
            owner = "none"
        log.write("transition\n")
        log.flush()
        print(json.dumps({"type": "reply", "text": f"active={owner}"}), flush=True)
manifest["status"] = "complete"
(root / "manifest.json").write_text(json.dumps(manifest))

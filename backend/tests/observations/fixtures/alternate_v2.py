"""The same non-NexAU behavior with ownership diagnostics and version-specific documentation."""

import json
import os
import sys
from pathlib import Path

root = Path(os.environ["HARNESS_OBSERVATION_DIR"])
root.mkdir(parents=True, exist_ok=True)
(root / "READING.md").write_text(
    "v2: ownership.tsv columns are action and affected owner. Cancel records the OLD owner; inspect records the CURRENT owner. Compare with actual replies; logs alone do not prove behavior."
)
manifest = {
    "reading": "READING.md",
    "status": "partial",
    "files": [{"path": "READING.md"}, {"path": "ownership.tsv"}],
}
(root / "manifest.json").write_text(json.dumps(manifest))
owner = "none"
with (root / "ownership.tsv").open("w") as log:
    for line in sys.stdin:
        frame = json.loads(line)
        if frame["type"] == "shutdown":
            break
        message = frame.get("text", "")
        affected = owner
        action = message.split()[0]
        if message in {"start A", "start B"}:
            owner = affected = message[-1]
        elif message == "cancel":
            owner = "none"
        log.write(f"{action}\t{affected}\n")
        log.flush()
        print(json.dumps({"type": "reply", "text": f"active={owner}"}), flush=True)
manifest["status"] = "complete"
(root / "manifest.json").write_text(json.dumps(manifest))

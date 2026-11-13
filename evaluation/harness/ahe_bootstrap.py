"""AHE-specific bootstrap: capture native HTTP before loading the pinned agent."""

import os
import runpy
from pathlib import Path


def main():
    import fulltrace

    logs = Path(os.environ.get("HARNESS_LOG_DIR", "/logs/agent"))
    fulltrace.install("actor", logs / "full-call-traces/actor")
    entry = runpy.run_path(
        str(Path(__file__).with_name("_harness_entry.py")), run_name="_frozen_ahe"
    )
    entry["main"]()


if __name__ == "__main__":
    main()

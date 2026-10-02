#!/usr/bin/env python3
"""Check the real configuration writer against a supplied OpenAgents checkout.

No model, forge, subprocess agent or container is started. Run in the controller's
locked environment so no globally installed OpenAgents can mask incompatibility.
"""

import argparse
import importlib
import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openagents", type=Path, required=True)
    args = parser.parse_args()
    checkout = args.openagents.resolve()
    if not (checkout / "openagents/utils/agent_config.py").is_file():
        parser.error("--openagents must point to an OpenAgents source checkout")
    sys.path[:0] = [str(checkout), str(Path(__file__).resolve().parents[1])]
    config_module = importlib.import_module("openagents.utils.agent_config")
    if not Path(config_module.__file__).resolve().is_relative_to(checkout):
        raise RuntimeError("configuration parser came from a different checkout")
    controller = importlib.import_module("auto_designer.experiment.controllers.ordinary")
    # Ensure local backend/.env and the caller's environment cannot change this check.
    os.environ["VIGIL_COORDINATION"] = "soft"
    os.environ.pop("VIGIL_CI_STAGE", None)
    with tempfile.TemporaryDirectory(prefix="openagents-contract-") as temp:
        path = controller.write_openagents_config(
            repo=Path(temp),
            gitea={
                "GITEA_URL": "http://127.0.0.1:3000",
                "OWNER": "demo",
                "REPO": "harness",
                "TOKEN": "synthetic-token-never-written",
            },
        )
        config = config_module.load_agent_config(path=path)
        assert config.flow == "standard", config.flow
        assert config.coordination == "soft", config.coordination
        assert config.forge == "gitea", config.forge
        for stage in ("ci", "e2e"):
            assert config.stages.owner_of(stage=stage) == "skip"
        assert config.stages.owner_of(stage="review") == "agent"
        assert "synthetic-token-never-written" not in path.read_text()
        example = Path(__file__).resolve().parents[2] / "examples/openagents-v02-nexau.yml"
        explicit = config_module.load_agent_config(path=example)
        assert explicit.flow == "v0.2"
        assert explicit.agents.backend_for(role="developer") == "nexau"
    print("PASS: generated Gitea standard/soft config and explicit v0.2/NexAU example")


if __name__ == "__main__":
    main()

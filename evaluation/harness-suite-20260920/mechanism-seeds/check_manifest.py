"""Offline integrity checks for the mechanism seed package."""

import json
from pathlib import Path


ROOT = Path(__file__).parent


def main() -> int:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    expected = {entry["id"] for entry in manifest["new"]}
    assert expected == {"M05", "M07", "M09", "M10"}
    for entry in manifest["new"]:
        package = ROOT / entry["package"]
        assert (package / "public/TASK.md").is_file()
        assert (package / "user_context.md").is_file()
        assert (package / "evaluation.json").is_file()
        assert (package / "reference").is_dir()
        public_text = "\n".join(
            path.read_text() for path in (package / "public").rglob("*") if path.is_file()
        )
        assert "user_context" not in public_text
        assert "reference/" not in public_text
    assert manifest["interaction_contract"]["trigger_engine"] is False
    assert manifest["interaction_contract"]["scripted_turns"] is False
    print("mechanism seed manifest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

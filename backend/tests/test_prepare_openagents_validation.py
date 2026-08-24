from __future__ import annotations

import pytest

from scripts.prepare_openagents_validation import validate_delivery_selection


def test_delivery_selection_preflight_rejects_unsafe_plan() -> None:
    snapshots = [{"number": 1}, {"number": 2}]
    validate_delivery_selection(
        source_repo="source", target_repo="target", snapshots=snapshots, selected={2}
    )
    with pytest.raises(SystemExit, match="must differ"):
        validate_delivery_selection(
            source_repo="same", target_repo="same", snapshots=snapshots, selected={1}
        )
    with pytest.raises(SystemExit, match="do not exist"):
        validate_delivery_selection(
            source_repo="source", target_repo="target", snapshots=snapshots, selected={3}
        )

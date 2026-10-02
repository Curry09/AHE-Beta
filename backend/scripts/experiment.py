#!/usr/bin/env python3
# Spec-0071/T3: the only public experiment CLI.
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_designer.experiment.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

"""Explicit recovery: python -m auto_designer.observations --root ROOT --receipt FILE."""

import argparse
import json
from pathlib import Path

from auto_designer.observations.publication import recover


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover one retained observation source without deleting it"
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(recover(receipt_path=args.receipt, root=args.root), ensure_ascii=False))


if __name__ == "__main__":
    main()

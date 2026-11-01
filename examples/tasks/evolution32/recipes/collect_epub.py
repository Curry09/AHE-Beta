"""Spec-0081/T5: Collect one existing task EPUB; never convert chapters or create a replacement."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

ACCEPTED_NAMES = ("Pass Through.epub", "Pass_Through.epub", "pass_through.epub")


def collect(*, source: Path, target: Path, max_bytes: int) -> dict:
    if max_bytes <= 0:
        raise ValueError("Collection limit must be positive")
    if any(path.is_symlink() for path in (source, *source.parents)):
        return {"epub_collection": "invalid_source_directory"}
    if any(path.is_symlink() for path in (target.parent, *target.parent.parents)):
        return {"epub_collection": "invalid_output_directory"}
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            return {"epub_collection": "invalid_output_target"}
    for name in ACCEPTED_NAMES:
        path = source / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= max_bytes:
            continue
        descriptor, temporary_name = tempfile.mkstemp(prefix="epub-", dir=target.parent)
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        count = 0
        try:
            with os.fdopen(descriptor, "wb") as output, path.open("rb") as incoming:
                while chunk := incoming.read(1024 * 1024):
                    count += len(chunk)
                    if count > max_bytes:
                        raise ValueError("Existing EPUB exceeds collection limit")
                    digest.update(chunk)
                    output.write(chunk)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "epub_collection": "copied_existing_actor_output",
            "source_name": name,
            "bytes": count,
            "sha256": digest.hexdigest(),
        }
    return {"epub_collection": "missing_or_invalid_actor_output"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("/home/user/Documents/Novels/Pass Through")
    )
    parser.add_argument("--target", type=Path, default=Path("/app/.collected/novel.epub"))
    parser.add_argument("--max-bytes", type=int, default=128 * 1024 * 1024)
    args = parser.parse_args()
    print(json.dumps(collect(source=args.source, target=args.target, max_bytes=args.max_bytes)))


if __name__ == "__main__":
    main()

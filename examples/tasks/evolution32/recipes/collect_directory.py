"""Spec-0081/T5: Package bounded, existing Actor files without executing or generating them."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def collect(
    *,
    source: Path,
    target: Path,
    prefix: str,
    max_bytes: int,
    exclude: list[str] | None = None,
    max_file_bytes: int = 64 * 1024 * 1024,
    max_entries: int = 20000,
) -> dict:
    if max_bytes <= 0 or not prefix or "/" in prefix or prefix in {".", ".."}:
        raise ValueError("A safe archive prefix and positive limit are required")
    exclusions = sorted(set(exclude or []))
    for value in exclusions:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or value != path.as_posix()
            or any(part in {".", ".."} for part in path.parts)
            or any(character in value for character in "\\*?[]\0")
        ):
            raise ValueError("Exclusions must name explicit relative directories")
    if max_file_bytes <= 0 or max_entries <= 0:
        raise ValueError("Positive file and entry limits are required")

    def incomplete(reason: str, **details: object) -> dict:
        return {"directory_collection": reason, "complete": False, **details}

    if any(path.is_symlink() for path in (target.parent, *target.parent.parents)):
        return incomplete("invalid_output_directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            return incomplete("invalid_output_target")
    if not source.is_dir() or any(path.is_symlink() for path in (source, *source.parents)):
        return incomplete("missing_or_invalid_actor_output")
    root = source.resolve()
    entries = []
    skipped = []
    total = 0

    def excluded(relative: str) -> bool:
        parts = PurePosixPath(relative).parts
        return any(
            value in parts
            if "/" not in value
            else relative == value or relative.startswith(value + "/")
            for value in exclusions
        )

    for directory, directories, filenames in os.walk(source, followlinks=False):
        original_directories = set(directories)
        descend = []
        for name in sorted([*directories, *filenames]):
            path = Path(directory) / name
            if path == target:
                continue
            relative = path.relative_to(source).as_posix()
            if name in original_directories and excluded(relative):
                skipped.append(relative)
                continue
            info = path.lstat()
            if len(entries) >= max_entries:
                return incomplete("actor_output_exceeds_capture_limit", limit="entries")
            if stat.S_ISDIR(info.st_mode):
                descend.append(name)
                entries.append((path, info, None))
            elif stat.S_ISLNK(info.st_mode):
                link = os.readlink(path)
                components = list(PurePosixPath(relative).parent.parts)
                for part in PurePosixPath(link).parts:
                    if part == "..":
                        if not components:
                            return incomplete("unsafe_actor_output_link", path=relative)
                        components.pop()
                    elif part != ".":
                        components.append(part)
                try:
                    resolved = path.resolve(strict=False)
                except (OSError, RuntimeError):
                    return incomplete("unsafe_actor_output_link", path=relative)
                if PurePosixPath(link).is_absolute() or not resolved.is_relative_to(root):
                    return incomplete("unsafe_actor_output_link", path=relative)
                entries.append((path, info, link))
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if info.st_size > max_file_bytes or total > max_bytes:
                    return incomplete("actor_output_exceeds_capture_limit", limit="bytes")
                entries.append((path, info, None))
            else:
                return incomplete("unsupported_actor_output_type", path=relative)
        directories[:] = descend
    if not any(stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) for _, info, _ in entries):
        return incomplete("missing_or_invalid_actor_output")
    descriptor, temporary_name = tempfile.mkstemp(prefix="actor-output-", dir=target.parent)
    temporary = Path(temporary_name)
    inventory = {}
    try:
        with (
            os.fdopen(descriptor, "wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as stream,
            tarfile.open(fileobj=stream, mode="w") as archive,
        ):
            for path, info, link in entries:
                relative = path.relative_to(source).as_posix()
                member = tarfile.TarInfo(prefix + "/" + relative)
                member.mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    member.type = tarfile.DIRTYPE
                    inventory[relative] = {"type": "directory", "mode": member.mode}
                    archive.addfile(member)
                elif link is not None:
                    member.type = tarfile.SYMTYPE
                    member.linkname = link
                    inventory[relative] = {"type": "symlink", "target": link, "mode": member.mode}
                    archive.addfile(member)
                else:
                    data = path.read_bytes()
                    if len(data) != info.st_size:
                        raise ValueError("Actor file changed during frozen collection")
                    member.size = len(data)
                    inventory[relative] = {
                        "type": "file",
                        "mode": member.mode,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                    archive.addfile(member, io.BytesIO(data))
            record = {
                "complete": True,
                "scope": "existing_actor_outputs_with_declared_exclusions",
                "excluded_directories": exclusions,
                "excluded_paths": skipped,
                "actor_outputs": inventory,
            }
            data = (json.dumps(record, indent=2) + "\n").encode()
            member = tarfile.TarInfo("collection-manifest.json")
            member.size = len(data)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "directory_collection": "packaged_existing_actor_outputs",
        "complete": True,
        "files": sum(stat.S_ISREG(info.st_mode) for _, info, _ in entries),
        "entries": len(entries),
        "uncompressed_bytes": total,
        "excluded_directories": exclusions,
        "excluded_paths": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--max-bytes", type=int, default=192 * 1024 * 1024)
    parser.add_argument("--max-file-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-entries", type=int, default=20000)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Explicit directory name at any depth, or source-relative directory subtree",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            collect(
                source=args.source,
                target=args.target,
                prefix=args.prefix,
                max_bytes=args.max_bytes,
                exclude=args.exclude,
                max_file_bytes=args.max_file_bytes,
                max_entries=args.max_entries,
            )
        )
    )


if __name__ == "__main__":
    main()

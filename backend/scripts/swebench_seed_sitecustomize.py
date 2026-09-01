"""Compatibility aliases for historical SWE-bench Python snapshots.

This file is copied into selected seed virtual environments as
``sitecustomize.py``. It adapts interpreter APIs only; benchmark source trees
remain byte-for-byte at their recorded base commits.
"""

from __future__ import annotations

import collections
import inspect
from collections import abc

for _name in (
    "Callable",
    "Iterable",
    "Iterator",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "MutableSet",
    "Sequence",
    "Set",
):
    if not hasattr(collections, _name):
        setattr(collections, _name, getattr(abc, _name))

if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec

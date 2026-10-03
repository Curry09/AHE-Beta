#!/usr/bin/env bash
# Spec-0076/T4: conversion, public CLI and production freezing, with no provider calls.
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run --locked --extra experiments --extra dev pytest -q \
  backend/tests/test_experiment_task_import.py \
  backend/tests/test_experiment_task_import_e2e.py \
  backend/tests/test_experiment_cli_v2.py \
  backend/tests/test_experiment_repository.py

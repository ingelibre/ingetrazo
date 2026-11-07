#!/usr/bin/env bash
# Build the Rust engine (rust/ingetrazo_core) and install it in ./venv,
# the same way the release workflows do. Run again after any change to rust/.
set -euo pipefail
cd "$(dirname "$0")/.."
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
./venv/bin/python -m pip install --quiet maturin
./venv/bin/maturin build --release -m rust/ingetrazo_core/Cargo.toml -o "$out"
./venv/bin/python -m pip install --quiet --force-reinstall --no-deps "$out"/ingetrazo_core-*.whl
INGETRAZO_RUST=1 ./venv/bin/python -m pytest -q tests/test_rust_engine_switch.py

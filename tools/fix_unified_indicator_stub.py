#!/usr/bin/env python3
"""Restore the no-op IndicatorDestroy implementation in unified minimal visuals.

The icon implementation is excluded from the compact unified build, but remote
cleanup code still calls IndicatorDestroy. This helper supplies an empty
unified-only implementation to keep the interface valid, without restoring
icon graphics or sprite management. It is idempotent and creates a backup.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_INDICATOR_DESTROY_STUB"
OLD = "static void IndicatorTick(void) {}"
NEW = """/* CUBHMA_UNIFIED_INDICATOR_DESTROY_STUB: indicators are not created in this build. */
static void IndicatorDestroy(struct Remote *r) { (void)r; }
static void IndicatorTick(void) {}"""


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_unified_indicator_stub.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    path = root / "payload" / "main.c"
    if not path.is_file():
        print(f"error: payload/main.c was not found: {path}", file=sys.stderr)
        return 1

    try:
        source = path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Unified IndicatorDestroy stub is already present.")
            return 0
        if "CUBHMA_UNIFIED_MINIMAL_VISUALS" not in source:
            raise ValueError("The unified minimal-visuals patch is missing; no files changed.")
        if source.count(OLD) != 1:
            raise ValueError(f"Expected one exact no-op IndicatorTick stub; found {source.count(OLD)}. No files changed.")

        backup = Path(str(path) + ".pre-indicator-destroy-stub.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(source.replace(OLD, NEW, 1), encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Added a no-op IndicatorDestroy for the unified minimal-visuals build.")
    print("The icon subsystem remains disabled; backup created.")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

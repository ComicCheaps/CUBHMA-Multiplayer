#!/usr/bin/env python3
"""Use GCC's more size-aggressive -Oz only for the unified native-SIO build.

This is a reversible, semantics-preserving compiler-optimization experiment to
fit the additional runtime Host/Join menu below HANDOFF_BASE. Existing master,
slave, adapter, and non-unified builds keep their original -Os setting.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_SIZE_OZ"

OLD = r'''& $gcc @common -Os -fno-jump-tables @sizeFlags @stackFlags @mainDefs @noInterwork -mthumb -include $symsHeader -c (Join-Path $root "payload\main.c") -o (Join-Path $build "main.o")'''

NEW = r'''# CUBHMA_UNIFIED_SIZE_OZ: retain -Os for every existing build; try -Oz for the unified lobby.
$mainOptimization = if ($NativeSioRole -eq "unified") { "-Oz" } else { "-Os" }
& $gcc @common $mainOptimization -fno-jump-tables @sizeFlags @stackFlags @mainDefs @noInterwork -mthumb -include $symsHeader -c (Join-Path $root "payload\main.c") -o (Join-Path $build "main.o")'''


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_unified_oz_size.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    build_path = root / "build.ps1"
    if not build_path.is_file():
        print(f"error: build script not found: {build_path}", file=sys.stderr)
        return 1

    try:
        source = build_path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Unified-only -Oz compiler setting is already applied.")
            return 0
        if '$NativeSioRole -eq "unified"' not in source or "PAYLOAD_NATIVE_SIO_RUNTIME" not in source:
            raise ValueError("Apply tools/patch_unified_native_roles.py first; this build does not define the unified role.")
        count = source.count(OLD)
        if count != 1:
            raise ValueError(f"Expected one exact main.c compile command, found {count}; no files changed.")

        backup = Path(str(build_path) + ".pre-unified-oz-size.bak")
        if not backup.exists():
            shutil.copy2(build_path, backup)
        build_path.write_text(source.replace(OLD, NEW, 1), encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied unified-only -Oz size optimization to main.c.")
    print("All non-unified builds retain -Os.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    print("If .text still overlaps .lateclear, keep HANDOFF_BASE unchanged and share the new linker line.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

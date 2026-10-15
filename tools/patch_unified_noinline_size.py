#!/usr/bin/env python3
"""Try disabling ordinary function inlining for the unified ROM only.

The unified-only -Oz build still ended at the same address. This reversible
experiment appends -fno-inline-functions only to the unified main.c compile.
All other roles and the existing sizeFlags remain unchanged.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_NO_INLINE_SIZE"
OPT_LINE = '$mainOptimization = if ($NativeSioRole -eq "unified") { "-Oz" } else { "-Os" }\n'
COMPILE_NEEDLE = '@noInterwork -mthumb -include $symsHeader -c (Join-Path $root "payload\\main.c") -o (Join-Path $build "main.o")'


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_unified_noinline_size.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    build_path = root / "build.ps1"
    if not build_path.is_file():
        print(f"error: build script not found: {build_path}", file=sys.stderr)
        return 1

    try:
        source = build_path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Unified-only no-inline size experiment is already applied.")
            return 0
        if OPT_LINE not in source:
            raise ValueError("Could not find the unified-only -Oz setting. Apply tools/patch_unified_oz_size.py first.")
        if source.count(COMPILE_NEEDLE) != 1:
            raise ValueError("Could not uniquely find the main.c compile command; no files changed.")

        new_opt_line = OPT_LINE + '''$unifiedOptimizationFlags = @()
if ($NativeSioRole -eq "unified") { $unifiedOptimizationFlags += "-fno-inline-functions" }
Write-Output ("main optimization: {0}; unified extra flags: {1}" -f $mainOptimization, ($unifiedOptimizationFlags -join " "))
'''
        source = source.replace(OPT_LINE, new_opt_line, 1)
        source = source.replace(
            COMPILE_NEEDLE,
            COMPILE_NEEDLE.replace('@noInterwork -mthumb', '@noInterwork @unifiedOptimizationFlags -mthumb'),
            1,
        )
        source = source.replace(new_opt_line, new_opt_line + "# " + MARKER + "\n", 1)

        backup = Path(str(build_path) + ".pre-unified-no-inline-size.bak")
        if not backup.exists():
            shutil.copy2(build_path, backup)
        build_path.write_text(source, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied unified-only -fno-inline-functions experiment.")
    print("The build will print the active optimization flags so we can verify the change.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Enable link-time optimization only for the unified native-SIO ROM build.

The compiler-only size flags did not change the linked end address. This
reversible experiment lets GCC optimize across main.c and sio.c together;
all other roles keep their existing compilation and link settings.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_LTO_SIZE"
OPT_ANCHOR = '$mainOptimization = if ($NativeSioRole -eq "unified") { "-Oz" } else { "-Os" }'
MAIN_ANCHOR = '@noInterwork @unifiedOptimizationFlags -mthumb -include $symsHeader -c (Join-Path $root "payload\\main.c") -o (Join-Path $build "main.o")'
SIO_ANCHOR = '@stackFlags @noInterwork -mthumb -c (Join-Path $root "payload\\sio.c") -o (Join-Path $build "sio.o")'
LINK_ANCHOR = '& $gcc @common -nostdlib -nostartfiles '


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_unified_lto_size.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    build_path = root / "build.ps1"
    if not build_path.is_file():
        print(f"error: build script not found: {build_path}", file=sys.stderr)
        return 1

    try:
        source = build_path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Unified-only LTO size experiment is already applied.")
            return 0
        if OPT_ANCHOR not in source:
            raise ValueError("Unified -Oz configuration not found; first pull the unified build-size helpers.")
        for needle, label in ((MAIN_ANCHOR, "main.c compile command"),
                              (SIO_ANCHOR, "sio.c compile command"),
                              (LINK_ANCHOR, "link command")):
            if source.count(needle) != 1:
                raise ValueError(f"Expected exactly one {label}; no changes applied.")

        source = source.replace(
            OPT_ANCHOR,
            OPT_ANCHOR + '\n$unifiedLtoFlags = @()\nif ($NativeSioRole -eq "unified") { $unifiedLtoFlags += "-flto" }',
            1,
        )
        source = source.replace(
            MAIN_ANCHOR,
            MAIN_ANCHOR.replace('@unifiedOptimizationFlags -mthumb', '@unifiedOptimizationFlags @unifiedLtoFlags -mthumb'),
            1,
        )
        source = source.replace(
            SIO_ANCHOR,
            SIO_ANCHOR.replace('@noInterwork -mthumb', '@noInterwork @unifiedLtoFlags -mthumb'),
            1,
        )
        source = source.replace(
            LINK_ANCHOR,
            LINK_ANCHOR.replace('@common -nostdlib', '@common @unifiedLtoFlags -nostdlib'),
            1,
        )
        source = source.replace(
            OPT_ANCHOR + '\n$unifiedLtoFlags',
            OPT_ANCHOR + '\n# ' + MARKER + '\n$unifiedLtoFlags',
            1,
        )

        backup = Path(str(build_path) + ".pre-unified-lto-size.bak")
        if not backup.exists():
            shutil.copy2(build_path, backup)
        build_path.write_text(source, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Enabled -flto for main.c, sio.c, and the final link ONLY for -NativeSioRole unified.")
    print("Other builds are unchanged; build.ps1 backup created.")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    print("If the stack-analysis guard rejects LTO or overlap persists, share the first error lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

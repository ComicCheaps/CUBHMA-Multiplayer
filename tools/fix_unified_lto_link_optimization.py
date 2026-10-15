#!/usr/bin/env python3
"""Ensure the unified LTO link pass also optimizes for size (-Oz).

The shared compiler flags include -O2. GCC's LTO optimizer runs at the final
link step, so the unified size choice must be passed there too; otherwise the
final LTO pass can expand .text even though main.c was compiled with -Oz.
Only the unified role gets this extra link-time option.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_LTO_LINK_OZ"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_unified_lto_link_optimization.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    path = root / "build.ps1"
    if not path.is_file():
        print(f"error: build script not found: {path}", file=sys.stderr)
        return 1

    try:
        source = path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Unified LTO link-time -Oz correction is already applied.")
            return 0
        if "CUBHMA_UNIFIED_LTO_SIZE" not in source:
            raise ValueError("The unified LTO helper is not applied. Apply tools/patch_unified_lto_size.py first.")
        if source.count('$unifiedGcFlags = @()') != 1:
            raise ValueError("Could not uniquely locate unified LTO flag arrays; no changes made.")
        if source.count('$unifiedGcFlags += "-Wl,--gc-sections"') != 1:
            raise ValueError("Could not uniquely locate unified GC flag; no changes made.")

        # Create a separate link-only option list; don't affect main.c or sio.c flags.
        source = source.replace(
            '$unifiedGcFlags = @()',
            '$unifiedGcFlags = @()\n$unifiedLinkOptFlags = @()',
            1,
        )
        source = source.replace(
            '$unifiedGcFlags += "-Wl,--gc-sections"',
            '$unifiedGcFlags += "-Wl,--gc-sections"\n    $unifiedLinkOptFlags += "-Oz"',
            1,
        )

        # Match the actual one-line start of the multiline link command.
        old = '& $gcc @common @unifiedLtoFlags @unifiedGcFlags -nostdlib -nostartfiles'
        new = '& $gcc @common @unifiedLtoFlags @unifiedGcFlags @unifiedLinkOptFlags -nostdlib -nostartfiles'
        if source.count(old) != 1:
            raise ValueError("Could not uniquely locate final linker command; no files changed.")
        source = source.replace(old, new, 1)

        # Mark the patch next to its new flag declaration.
        anchor = '$unifiedLinkOptFlags = @()'
        if source.count(anchor) != 1:
            raise ValueError("Link optimization marker anchor is ambiguous; no files changed.")
        source = source.replace(
            anchor,
            '# ' + MARKER + ': override common -O2 for the unified LTO link pass.\n' + anchor,
            1,
        )

        backup = Path(str(path) + ".pre-unified-lto-link-oz.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(source, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied unified-only -Oz to the final LTO link step.")
    print("Shared/legacy builds are unchanged; build.ps1 backup created.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    print("If it still fails, share the new .text/.bss overlap line and the payload.map .text/.bss sizes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

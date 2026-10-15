#!/usr/bin/env python3
"""Enable unified-only LTO and dead-section elimination.

The exact-string patch was too fragile for the checked-out build.ps1. This
version locates the main.c, sio.c and linker command lines by regex, validates
each match before writing, and applies flags only when NativeSioRole=unified.
The script backs up build.ps1 and does not change linker memory boundaries.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_LTO_SIZE"


def replace_one(source: str, pattern: str, replacement, label: str) -> str:
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.M)
    if count != 1:
        raise ValueError(f"Expected one {label} line; found {count}. No files changed.")
    return updated


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
        if not re.search(r'\$mainOptimization\s*=\s*if\s*\(\$NativeSioRole\s*-eq\s*"unified"\)', source):
            raise ValueError("Unified -Oz configuration not found. Pull the latest branch helpers first.")

        # Match whole compiler command lines without assuming an exact set of flags.
        main_pat = r'^(\s*&\s*\$gcc[^\r\n]*payload\\main\.c[^\r\n]*)$'
        sio_pat = r'^(\s*&\s*\$gcc[^\r\n]*payload\\sio\.c[^\r\n]*)$'
        link_pat = r'^(\s*&\s*\$gcc[^\r\n]*-nostdlib\s+-nostartfiles[^\r\n]*)$'

        for pat, label in ((main_pat, "main.c compile command"),
                           (sio_pat, "sio.c compile command"),
                           (link_pat, "link command")):
            if len(re.findall(pat, source, flags=re.M)) != 1:
                raise ValueError(f"Could not uniquely identify the {label}; no files changed.")

        # Add the mode-dependent flag arrays immediately after the existing unified
        # optimization selector, so legacy roles receive empty arrays.
        opt_pat = r'^(\s*\$mainOptimization\s*=\s*if\s*\(\$NativeSioRole\s*-eq\s*"unified"\)\s*\{[^\r\n]+\}\s*else\s*\{[^\r\n]+\}\s*)$'
        opt_repl = r'''\1
# CUBHMA_UNIFIED_LTO_SIZE: only the unified ROM may discard unused sections.
$unifiedLtoFlags = @()
$unifiedGcFlags = @()
if ($NativeSioRole -eq "unified") {
    $unifiedLtoFlags += @("-flto", "-ffunction-sections", "-fdata-sections")
    $unifiedGcFlags += "-Wl,--gc-sections"
}'''
        source = replace_one(source, opt_pat, opt_repl, "unified optimization selector")

        def add_compile_flags(match: re.Match) -> str:
            line = match.group(1)
            if "@unifiedLtoFlags" in line:
                raise ValueError("LTO flags already appear in a compile command; inspect build.ps1 manually.")
            if " -mthumb " not in line:
                raise ValueError("Could not locate -mthumb on a compile command; no files changed.")
            return line.replace(" -mthumb ", " @unifiedLtoFlags -mthumb ", 1)

        source = replace_one(source, main_pat, add_compile_flags, "main.c compile command")
        # The main line's extra arguments do not affect matching the sio.c line.
        source = replace_one(source, sio_pat, add_compile_flags, "sio.c compile command")

        def add_link_flags(match: re.Match) -> str:
            line = match.group(1)
            if "@unifiedGcFlags" in line:
                raise ValueError("GC flags already appear in the link command; inspect build.ps1 manually.")
            return line.replace("-nostdlib -nostartfiles", "@unifiedLtoFlags @unifiedGcFlags -nostdlib -nostartfiles", 1)

        source = replace_one(source, link_pat, add_link_flags, "link command")

        backup = Path(str(build_path) + ".pre-unified-lto-size.bak")
        if not backup.exists():
            shutil.copy2(build_path, backup)
        build_path.write_text(source, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied unified-only -flto plus function/data sections and --gc-sections.")
    print("Legacy master/slave/adapter roles receive empty extra-flag arrays.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    print("This remains an experiment; if the build fails, share the first actual error line.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

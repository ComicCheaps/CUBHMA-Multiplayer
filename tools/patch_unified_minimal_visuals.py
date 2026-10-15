#!/usr/bin/env python3
"""Reduce unified-only payload size by omitting the optional overhead icons.

The remote status icons are visual polish, not transport or movement logic. They
include compressed art and sprite management code. This helper removes that
subsystem only from the unified proof-of-concept build, retains a no-op
IndicatorTick(), and restores the pre-LTO build.ps1 backup so the linker-time
optimization experiment that increased .text is not used.

It does not change the linker script, HANDOFF_BASE, lateclear queues, or the
legacy master/slave/adapter builds.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

VISUALS_MARKER = "CUBHMA_UNIFIED_MINIMAL_VISUALS"
LTO_MARKER = "CUBHMA_UNIFIED_LTO_SIZE"
BACKUP_NAME = "build.ps1.pre-unified-lto-size.bak"

START = "/* ========================================================================== */\n/* Indicatore di stato: l'icona sopra la testa del remoto"
END = "/* ========================================================================== */\n/* Pass-through: non farsi bloccare dall'amico"


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_unified_minimal_visuals.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    main_path = root / "payload" / "main.c"
    build_path = root / "build.ps1"
    pre_lto_backup = root / BACKUP_NAME

    if not main_path.is_file() or not build_path.is_file():
        return fail("payload/main.c or build.ps1 was not found.")

    try:
        main_source = main_path.read_text(encoding="utf-8")
        build_source = build_path.read_text(encoding="utf-8")

        if VISUALS_MARKER in main_source and VISUALS_MARKER in build_source:
            print("Unified minimal-visuals configuration is already applied.")
            return 0
        if "CUBHMA_UNIFIED_COMPACT_LOBBY" not in main_source:
            raise ValueError("Compact unified lobby patch is missing; no files changed.")
        if START not in main_source or main_source.count(START) != 1:
            raise ValueError("Could not uniquely find the remote status-indicator subsystem; no files changed.")
        if END not in main_source or main_source.count(END) != 1:
            raise ValueError("Could not uniquely find the end of the indicator subsystem; no files changed.")
        if main_source.index(START) >= main_source.index(END):
            raise ValueError("Indicator subsystem boundaries are reversed; no files changed.")

        if LTO_MARKER in build_source:
            # Restore the exact build script saved immediately before the LTO
            # experiment. Require markers that identify the expected backup.
            if not pre_lto_backup.is_file():
                raise ValueError(
                    "LTO flags are active but the pre-LTO backup is missing. "
                    "No files changed; restore build.ps1.pre-unified-lto-size.bak manually."
                )
            previous_build = pre_lto_backup.read_text(encoding="utf-8")
            if (LTO_MARKER in previous_build
                    or 'PAYLOAD_NATIVE_SIO_RUNTIME' not in previous_build
                    or '-fno-inline-functions' not in previous_build
                    or '$mainOptimization' not in previous_build):
                raise ValueError("The pre-LTO backup did not pass validation; no files changed.")
            build_source = previous_build

        if 'PAYLOAD_NATIVE_SIO_RUNTIME' not in build_source:
            raise ValueError("build.ps1 does not contain the unified runtime role; no files changed.")
        runtime_line = 'if ($NativeSioRole -eq "unified") { $mainDefs += "-DPAYLOAD_NATIVE_SIO_RUNTIME" }'
        if build_source.count(runtime_line) != 1:
            raise ValueError("Could not uniquely find the unified main.c define; no files changed.")
        if VISUALS_MARKER not in build_source:
            build_source = build_source.replace(
                runtime_line,
                runtime_line + '\nif ($NativeSioRole -eq "unified") { $mainDefs += "-DPAYLOAD_UNIFIED_MINIMAL_VISUALS" } # '
                + VISUALS_MARKER,
                1,
            )

        start = main_source.index(START)
        end = main_source.index(END)
        indicator_block = main_source[start:end]
        if "static void IndicatorTick(void)" not in indicator_block:
            raise ValueError("IndicatorTick was not found inside the expected subsystem; no files changed.")
        wrapped = (
            "#ifdef PAYLOAD_UNIFIED_MINIMAL_VISUALS\n"
            "/* " + VISUALS_MARKER + ": keep the prototype's native transport inside EWRAM limits. */\n"
            "static void IndicatorTick(void) {}\n"
            "#else\n"
            + indicator_block +
            "#endif /* PAYLOAD_UNIFIED_MINIMAL_VISUALS */\n"
        )
        main_source = main_source[:start] + wrapped + main_source[end:]

        # Validate the conditional keeps the call target present, the indicator
        # data isolated, and the marker singular.
        if main_source.count(VISUALS_MARKER) != 1:
            raise ValueError("Minimal-visuals source marker validation failed; no files changed.")
        if main_source.count("#ifdef PAYLOAD_UNIFIED_MINIMAL_VISUALS") != 1:
            raise ValueError("Minimal-visuals conditional validation failed; no files changed.")

        main_backup = Path(str(main_path) + ".pre-unified-minimal-visuals.bak")
        build_backup = Path(str(build_path) + ".pre-unified-minimal-visuals.bak")
        if not main_backup.exists():
            shutil.copy2(main_path, main_backup)
        if not build_backup.exists():
            shutil.copy2(build_path, build_backup)

        main_path.write_text(main_source, encoding="utf-8", newline="\n")
        build_path.write_text(build_source, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        return fail(str(exc))

    print("Applied unified-only minimal-visuals build.")
    print("The remote overhead status icons are disabled only for the unified prototype; movement and SIO code remain enabled.")
    print("Restored build.ps1 from the validated pre-LTO backup because LTO increased .text.")
    print(f"Source backup: {main_path}.pre-unified-minimal-visuals.bak")
    print(f"Build backup:  {build_path}.pre-unified-minimal-visuals.bak")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1. This change is not yet runtime-tested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Make the linker run non-terminating in Windows PowerShell 5.1.

PowerShell 5.1 can convert gcc/ld stderr (including the harmless RWX segment
warning) into a NativeCommandError record. With ErrorActionPreference=Stop,
the build script terminates before checking the native process exit code even
if ld successfully wrote payload.elf. Scope ErrorActionPreference=Continue to
the final linker invocation only, capture $LASTEXITCODE immediately, restore
the prior preference, and preserve the explicit failure check.

This does not suppress real failures, change compiler flags, edit code, or move
any linker memory boundaries.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_POWERSHELL_LINK_ACTION_SCOPE"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_powershell_native_stderr.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    path = root / "build.ps1"
    if not path.is_file():
        print(f"error: build script not found: {path}", file=sys.stderr)
        return 1

    try:
        source = path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Scoped PowerShell linker-error handling is already applied.")
            return 0

        lines = source.splitlines()
        starts = [
            i for i, line in enumerate(lines)
            if line.lstrip().startswith("& $gcc @common")
            and "-nostdlib" in line
            and "-nostartfiles" in line
        ]
        if len(starts) != 1:
            raise ValueError(f"Expected one final linker invocation, found {len(starts)}. No files changed.")

        start = starts[0]
        end_candidates = [
            i for i in range(start, len(lines))
            if lines[i].strip() == "@objs"
        ]
        if not end_candidates:
            raise ValueError("Could not locate @objs ending the final linker invocation. No files changed.")
        end = end_candidates[0]
        if end - start > 20:
            raise ValueError("Final linker command span looks unexpected; no files changed.")

        # Ensure the following code still checks the process's exit status.
        following = "\n".join(lines[end + 1:end + 4])
        if 'throw "link fallito"' not in following or "$LASTEXITCODE" not in following:
            raise ValueError("The expected post-link $LASTEXITCODE guard is missing; no files changed.")

        command_lines = lines[start:end + 1]
        # Remove the earlier attempt to redirect PowerShell's error records:
        # it did not prevent ErrorActionPreference=Stop from terminating.
        command_lines[0] = command_lines[0].replace(" 2>&1", "")
        indented = ["    " + line for line in command_lines]

        replacement = [
            "# " + MARKER + ": let ld finish and decide success by its exit code.",
            "$linkPreviousErrorActionPreference = $ErrorActionPreference",
            '$ErrorActionPreference = "Continue"',
            "try {",
            *indented,
            "    $linkExitCode = $LASTEXITCODE",
            "}",
            "finally {",
            "    $ErrorActionPreference = $linkPreviousErrorActionPreference",
            "}",
            'if ($linkExitCode -ne 0) { throw "link fallito (exit $linkExitCode)" }',
        ]
        # Replace the old command and its following one-line exit guard.
        guard_index = end + 1
        while guard_index < len(lines) and not lines[guard_index].strip():
            guard_index += 1
        if guard_index >= len(lines) or 'throw "link fallito"' not in lines[guard_index]:
            raise ValueError("Could not locate the old link failure guard; no files changed.")
        output = lines[:start] + replacement + lines[guard_index + 1:]

        backup = Path(str(path) + ".pre-scoped-link-error-action.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text("\n".join(output) + "\n", encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied scoped PowerShell error handling to final linker invocation.")
    print("The previous ErrorActionPreference is restored immediately after ld exits.")
    print("The real linker exit code is still checked; no memory layout was changed.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

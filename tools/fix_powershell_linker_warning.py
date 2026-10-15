#!/usr/bin/env python3
"""Temporarily relax PowerShell error handling around the native linker.

Windows PowerShell 5.1 turns native-program stderr into NativeCommandError
records. With build.ps1's global $ErrorActionPreference='Stop', even ld's
non-fatal RWX LOAD-segment warning aborts the script before objcopy. Redirecting
stderr alone did not solve this in the user's environment.

This patch wraps only the final linker invocation in try/finally, temporarily
sets ErrorActionPreference to Continue, captures LASTEXITCODE immediately, then
restores the original preference and explicitly fails on a nonzero exit code.
It does not alter linker flags, regions, object files, or ROM contents.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_LINKER_EAP_GUARD"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_powershell_linker_warning.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    path = root / "build.ps1"
    if not path.is_file():
        print(f"error: build script not found: {path}", file=sys.stderr)
        return 1

    try:
        source = path.read_text(encoding="utf-8")
        if MARKER in source:
            print("PowerShell linker error-handling guard is already applied.")
            return 0

        lines = source.splitlines()
        start_matches = [
            i for i, line in enumerate(lines)
            if "& $gcc" in line and "-nostdlib" in line and "-nostartfiles" in line
        ]
        if len(start_matches) != 1:
            raise ValueError(f"Expected one final linker command start line; found {len(start_matches)}. No files changed.")
        start = start_matches[0]

        end_matches = [
            i for i in range(start + 1, len(lines))
            if 'throw "link fallito"' in lines[i]
        ]
        if len(end_matches) != 1:
            raise ValueError(f"Expected one immediate link-failure check; found {len(end_matches)}. No files changed.")
        check = end_matches[0]
        command_lines = lines[start:check]
        if not any(relevant.endswith("@objs") or "@objs" in relevant for relevant in command_lines):
            raise ValueError("The final linker invocation does not end with @objs; no files changed.")
        if any("try {" in line or MARKER in line for line in command_lines):
            raise ValueError("The linker command appears partially wrapped; inspect build.ps1 manually.")

        # Drop the ineffective redirection added by the earlier version.
        first = command_lines[0]
        first = first.replace(" 2>&1", "")
        command_lines[0] = first

        indented_command = ["    " + line for line in command_lines]
        replacement = [
            "# " + MARKER + ": non-fatal linker warnings must not bypass the exit-code check.",
            "$previousLinkErrorActionPreference = $ErrorActionPreference",
            "$ErrorActionPreference = 'Continue'",
            "$linkExitCode = -1",
            "try {",
            *indented_command,
            "    $linkExitCode = $LASTEXITCODE",
            "} finally {",
            "    $ErrorActionPreference = $previousLinkErrorActionPreference",
            "}",
            'if ($linkExitCode -ne 0) { throw "link fallito (exit $linkExitCode)" }',
        ]

        updated_lines = lines[:start] + replacement + lines[check + 1:]
        backup = Path(str(path) + ".pre-linker-eap-guard.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied scoped PowerShell error-handling guard around the final linker command.")
    print("Non-fatal stderr warnings can no longer abort the build; a nonzero linker exit still fails explicitly.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

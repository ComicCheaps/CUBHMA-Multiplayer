#!/usr/bin/env python3
"""Prevent benign native-linker stderr warnings from aborting PowerShell 5.1.

build.ps1 uses $ErrorActionPreference = Stop. In Windows PowerShell 5.1,
stderr from a native executable may surface as a NativeCommandError even when
ld exits successfully. The known RWX LOAD-segment warning triggers this path,
so build.ps1 exits before objcopy and its explicit $LASTEXITCODE check.

This helper redirects only the final linker command's stderr to stdout. A real
nonzero linker exit is still caught by the immediately following exit-code
check. It does not change compiler options, code, linker regions, or ROM data.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_LINKER_STDERR_REDIRECT"


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
            print("PowerShell linker-stderr redirect is already applied.")
            return 0

        lines = source.splitlines(keepends=True)
        matches = [
            i for i, line in enumerate(lines)
            if "& $gcc" in line and "-nostdlib" in line and "-nostartfiles" in line
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one final linker command start line; found {len(matches)}. No files changed.")

        index = matches[0]
        line = lines[index]
        if "2>&1" in line:
            raise ValueError("The linker command already has stderr redirection but lacks this helper's marker. Inspect build.ps1 manually.")

        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        body = line[:-len(newline)] if newline else line
        stripped = body.rstrip()
        trailing_ws = body[len(stripped):]
        if stripped.endswith("`"):
            command = stripped[:-1].rstrip()
            lines[index] = command + " 2>&1 `" + newline
        else:
            lines[index] = stripped + " 2>&1" + trailing_ws + newline

        # Store the marker as a comment directly above the command's existing
        # context without breaking PowerShell's backtick continuation.
        lines.insert(index, "# " + MARKER + ": preserve harmless ld warnings without terminating PowerShell.\n")

        backup = Path(str(path) + ".pre-linker-stderr-redirect.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text("".join(lines), encoding="utf-8", newline="")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied stderr-to-stdout redirection for the final linker command.")
    print("Real link failures are still checked via $LASTEXITCODE.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

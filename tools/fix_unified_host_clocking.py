#!/usr/bin/env python3
"""Make the selected Host initiate native multiplayer SIO reliably.

Run after compact_unified_3p4p_memory.py:
  python tools/fix_unified_host_clocking.py

The host role starts the first transfer; hardware device ID 0 then clocks each
subsequent transfer, including after a host disconnects. Backups are preserved.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIO_PATH = ROOT / "third_party" / "gen3-poke-multiplayer" / "payload" / "sio.c"
MARKER = "CUBHMA_UNIFIED_HOST_MASTER_ROLE_CLOCK"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected one {label} anchor; found {count}.")
    return source.replace(old, new, 1)


def main() -> int:
    if not SIO_PATH.is_file():
        print(f"error: required source not found: {SIO_PATH}", file=sys.stderr)
        return 1

    source = SIO_PATH.read_text(encoding="utf-8")
    if MARKER in source:
        print("Host-clock fix is already applied.")
        return 0
    if "CUBHMA_UNIFIED_3P4P_MEMORY_COMPACT" not in source:
        print(
            "error: memory-compacted unified SIO source was not found. "
            "Apply tools/compact_unified_3p4p_memory.py first.",
            file=sys.stderr,
        )
        return 1

    # The transport latch is one byte of persistent state. It records that the
    # selected Host initiated the session, so physical ID 0 continues clocking
    # after the local player chooses Disconnect.
    source = replace_once(
        source,
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n",
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n"
        "/* The selected Host starts the link; device 0 keeps clocking it. */\n"
        "static volatile u8 sNativeTransportStarted;\n",
        "runtime role state",
    )

    source = replace_once(
        source,
        "void SioSetNativeRole(u8 role)\n"
        "{\n"
        "    if (role <= CUBHMA_NATIVE_ROLE_JOIN)\n"
        "        sNativeRole = role;\n"
        "}",
        "void SioSetNativeRole(u8 role)\n"
        "{\n"
        "    if (role <= CUBHMA_NATIVE_ROLE_JOIN)\n"
        "    {\n"
        "        sNativeRole = role;\n"
        "        if (role == CUBHMA_NATIVE_ROLE_HOST)\n"
        "        {\n"
        "            sNativeTransportStarted = 1;\n"
        "            if (sSio.active)\n"
        "                REG_SIOCNT |= SIOCNT_START;\n"
        "        }\n"
        "    }\n"
        "}",
        "runtime role setter",
    )

    # Before a session starts, only the console explicitly set to Host can
    # initiate the first transfer. A joining console must wait for its clock.
    source = replace_once(
        source,
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (SioGetDeviceId() == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)",
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)\n"
        "    {\n"
        "        sNativeTransportStarted = 1;\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "    }\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)",
        "runtime SioArm startup gate",
    )

    # Once hardware has assigned device IDs, ID 0 clocks every transfer even if
    # its local role is later set to OFF (Disconnect).
    source = replace_once(
        source,
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (localId == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)",
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (sNativeTransportStarted && localId == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)",
        "runtime serial IRQ clock gate",
    )

    source = replace_once(
        source,
        "/* CUBHMA_UNIFIED_3P4P_MEMORY_COMPACT */",
        "/* CUBHMA_UNIFIED_3P4P_MEMORY_COMPACT */\n"
        "/* " + MARKER + ": role starts link, hardware ID 0 clocks it. */",
        "host-clock fix marker",
    )

    if (
        "sNativeTransportStarted" not in source
        or "if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)" not in source
        or "if (sNativeTransportStarted && localId == 0u)" not in source
    ):
        print("error: post-patch validation failed; no source was written.", file=sys.stderr)
        return 1

    backup = Path(str(SIO_PATH) + ".pre-unified-host-clock.bak")
    if not backup.exists():
        shutil.copy2(SIO_PATH, backup)
    SIO_PATH.write_text(source, encoding="utf-8", newline="\n")

    print("Applied host-controlled startup and device-0 continuous clocking.")
    print(f"Backup: {backup.name}")
    print("Rebuild with:")
    print('  .\\tools\\prepare_unified_native_link_rom.ps1')
    print("Then test both host directions with two emulator instances.")
    print("This source change still needs compile and in-emulator validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

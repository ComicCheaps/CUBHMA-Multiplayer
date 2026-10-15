#!/usr/bin/env python3
"""Fix native SIO startup and shrink verified per-remote state for the unified ROM.

Run from the CUBHMA-Multiplayer repository root:
  python tools/fix_unified_sio_ready_and_memory.py

This patch is guarded and writes backups inside the payload submodule. It:
  * uses the GBA SIOCNT SI/SD terminal bits for parent/readiness decisions;
  * waits until all SIO devices are ready before starting the first transfer;
  * polls readiness each VBlank so a late joiner can still start the session;
  * stores bounded flags, IDs, coordinates, and queue indices at their actual widths.

The source still must pass the project's linker guard and mGBA tests.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBMODULE = ROOT / "third_party" / "gen3-poke-multiplayer"
MAIN_PATH = SUBMODULE / "payload" / "main.c"
SIO_PATH = SUBMODULE / "payload" / "sio.c"
MAIN_MARKER = "CUBHMA_REMOTE_STATE_COMPACT"
SIO_MARKER = "CUBHMA_NATIVE_PARENT_READY_START"


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {count}.")
    return source.replace(old, new, 1)


def patch_remote_state(source: str) -> tuple[str, bool]:
    if MAIN_MARKER in source:
        return source, False

    match = re.search(r"(?m)^struct Remote\s*\{.*?^\};", source, re.S)
    if not match:
        raise ValueError("Could not find the complete struct Remote definition.")

    block = match.group(0)
    # Each narrowed field has a range justified by how it is assigned and read:
    # mapKey comes from two 8-bit map identifiers; x/y are signed 16-bit wire
    # coordinates; qHead/qTail are indices in a six-entry ring.
    fields = {
        "state": ("u32", "u8"),
        "objectId": ("u32", "u8"),
        "known": ("u32", "u8"),
        "mapKey": ("u32", "u16"),
        "targetX": ("s32", "s16"),
        "targetY": ("s32", "s16"),
        "gender": ("u32", "u8"),
        "avatarState": ("u32", "u8"),
        "status": ("u32", "u8"),
        "statusAge": ("u32", "u16"),
        "settled": ("u32", "u8"),
        "driftRun": ("u32", "u8"),
        "lastEnqSeq": ("u32", "u16"),
        "forceResync": ("u32", "u8"),
        "outOfView": ("u32", "u8"),
        "stripOut": ("u32", "u8"),
        "carryCheck": ("u32", "u8"),
        "spawnCooldown": ("u32", "u8"),
        "cardRxBitmap": ("u32", "u16"),
        "indSpriteId": ("u32", "u8"),
        "indIcon": ("u32", "u8"),
        "indTileStart": ("u32", "u16"),
        "indFailed": ("u32", "u8"),
        "slot": ("u32", "u8"),
        "qHead": ("u32", "u8"),
        "qTail": ("u32", "u8"),
    }

    for field, (old_type, new_type) in fields.items():
        pattern = rf"(?m)^(\s*){old_type}\s+{field}\s*;"
        block, count = re.subn(
            pattern,
            lambda m, t=new_type, f=field: f"{m.group(1)}{t} {f};",
            block,
            count=1,
        )
        if count != 1:
            raise ValueError(
                f"Could not uniquely narrow struct Remote field {field} "
                f"from {old_type}; found {count} declarations."
            )

    old_comment = (
        " * I campi restano u32/s32 per la lezione Thumb-1 del 2026-08-23 (i tipi\n"
        " * stretti costano istruzioni); i campi di g_state con lo stesso nome restano\n"
    )
    new_comment = (
        " * I flag, gli ID, le coordinate sul filo e gli indici degli anelli usano\n"
        " * u8/u16 dopo averne verificato l'intervallo; spawnMapKey e il puntatore\n"
        " * callback restano a 32 bit. I campi di g_state con lo stesso nome restano\n"
    )
    source = once(source, old_comment, new_comment, "Remote-width documentation")

    # Insert the marker immediately before the modified definition. Use the
    # definition's current start, since the comment replacement above changes
    # the absolute source offset.
    match = re.search(r"(?m)^struct Remote\s*\{.*?^\};", source, re.S)
    if not match:
        raise ValueError("struct Remote disappeared after field-width changes.")
    marked_block = "/* " + MAIN_MARKER + ": compact per-peer state after range audit. */\n" + match.group(0)
    source = source[:match.start()] + marked_block + source[match.end():]

    # Guards catch accidental edits that would silently leave the largest fields
    # wide or accidentally target a different structure.
    checked = re.search(r"(?m)^struct Remote\s*\{.*?^\};", source, re.S)
    if not checked:
        raise ValueError("Could not re-read compact struct Remote.")
    for field, (_, new_type) in fields.items():
        if not re.search(rf"(?m)^\s*{new_type}\s+{field}\s*;", checked.group(0)):
            raise ValueError(f"Post-patch validation failed for Remote.{field}.")

    return source, True


def patch_sio(source: str) -> tuple[str, bool]:
    if SIO_MARKER in source:
        return source, False
    if "CUBHMA_UNIFIED_3P4P_MEMORY_COMPACT" not in source:
        raise ValueError("Expected the compact unified 3P/4P SIO source first.")
    if "PAYLOAD_NATIVE_SIO_RUNTIME" not in source:
        raise ValueError("The unified runtime SIO build option is missing.")

    # These status bits exist before the first transfer; multiplayer ID bits do
    # not become valid until that first transfer has completed.
    id_line = re.compile(r"(?m)^#define SIOCNT_ID_MASK[^\n]*\n")
    source, count = id_line.subn(
        lambda m: m.group(0)
        + "#define SIOCNT_SI_TERMINAL  0x0004u  /* 0=physical parent */\n"
        + "#define SIOCNT_SD_TERMINAL  0x0008u  /* 1=all linked devices ready */\n",
        source,
        count=1,
    )
    if count != 1:
        raise ValueError("Could not add SIOCNT SI/SD terminal definitions.")

    # Parent detection and readiness are deliberately independent of the
    # user-facing Host/Join role and of the not-yet-valid device-ID bits.
    arm_anchor = "static __attribute__((noinline)) void SioArm(void)\n{"
    start_helper = (
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "/* CUBHMA_NATIVE_PARENT_READY_START: never read device ID before transfer 1. */\n"
        "static void SioTryStartTransfer(void)\n"
        "{\n"
        "    u16 cnt = REG_SIOCNT;\n"
        "    if ((cnt & (SIOCNT_SI_TERMINAL | SIOCNT_SD_TERMINAL | SIOCNT_START))\n"
        "        == SIOCNT_SD_TERMINAL)\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "}\n"
        "#endif\n\n"
    )
    source = once(source, arm_anchor, start_helper + arm_anchor, "SioArm insertion")

    old_arm_start = (
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (SioGetDeviceId() == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)"
    )
    new_arm_start = (
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    SioTryStartTransfer();\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)"
    )
    source = once(source, old_arm_start, new_arm_start, "SioArm initial-start check")

    source = once(
        source,
        "if (localId == 0u)\n        REG_SIOCNT |= SIOCNT_START;",
        "SioTryStartTransfer();",
        "post-transfer parent-start check",
    )

    # SioArm's first attempt can happen before another emulator window has put
    # its serial port into multiplayer mode. Poll once per VBlank as a fallback.
    tick_anchor = (
        "    if (!sSio.active)\n"
        "        return;\n\n"
        "    if (g_sio.irqs != lastIrqs) {"
    )
    tick_replacement = (
        "    if (!sSio.active)\n"
        "        return;\n"
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    SioTryStartTransfer();\n"
        "#endif\n\n"
        "    if (g_sio.irqs != lastIrqs) {"
    )
    source = once(source, tick_anchor, tick_replacement, "SioTick readiness poll")

    source = once(
        source,
        "/* " + SIO_MARKER + ": never use the device-ID field before transfer one. */\n",
        "",
        "placeholder marker",
    ) if ("/* " + SIO_MARKER + ": never use the device-ID field before transfer one. */\n") in source else source

    if source.count("SioTryStartTransfer();") != 3:
        raise ValueError(
            "Post-patch validation failed: expected SioArm, SioTick and IRQ call sites."
        )
    if "if (SioGetDeviceId() == 0u)\n        REG_SIOCNT |= SIOCNT_START;" in source:
        raise ValueError("Unsafe pre-transfer device-ID check remains in SioArm.")
    return source, True


def backup_and_write(path: Path, text: str, suffix: str) -> None:
    backup = Path(str(path) + suffix)
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    for path in (MAIN_PATH, SIO_PATH):
        if not path.is_file():
            print(f"error: required source not found: {path}", file=sys.stderr)
            return 1

    try:
        old_main = MAIN_PATH.read_text(encoding="utf-8")
        old_sio = SIO_PATH.read_text(encoding="utf-8")
        new_main, main_changed = patch_remote_state(old_main)
        new_sio, sio_changed = patch_sio(old_sio)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Validate both files before writing either one.
    if main_changed:
        backup_and_write(MAIN_PATH, new_main, ".pre-sio-ready-memory.bak")
    if sio_changed:
        backup_and_write(SIO_PATH, new_sio, ".pre-sio-ready-memory.bak")

    print("Applied guarded unified SIO startup + per-peer memory patch:")
    print(f"  payload/main.c: {'updated' if main_changed else 'already compacted'}")
    print(f"  payload/sio.c:  {'updated' if sio_changed else 'already patched'}")
    print("  Parent check uses SIOCNT SI terminal; transfer starts only when SD reports ready.")
    print("  Readiness is retried each VBlank; post-transfer IDs remain in use for peer routing.")
    print("  struct Remote stores bounded fields at u8/u16 width to reclaim EWRAM.")
    print("  Backups end in .pre-sio-ready-memory.bak.")
    print("")
    print("Next build:")
    print('  .\\tools\\prepare_unified_native_link_rom.ps1')
    print("Do not bypass the linker memory guard. Test two players first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

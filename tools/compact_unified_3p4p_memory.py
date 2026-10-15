#!/usr/bin/env python3
"""Reduce unified 3P/4P payload memory and keep hardware ID 0 clocking.

Run after patch_unified_3p4p_leave.py has been applied:
  python tools/compact_unified_3p4p_memory.py

This is unified-runtime-only. Legacy native master/slave builds retain SIO
telemetry and counter behavior. Backups are created before any source is written.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBMODULE = ROOT / "third_party" / "gen3-poke-multiplayer"
MARKER = "CUBHMA_UNIFIED_3P4P_MEMORY_COMPACT"


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {count}.")
    return source.replace(old, new, 1)


def patch_sio(source: str) -> tuple[str, bool]:
    if MARKER in source and "SioRxState rx[3]" in source:
        return source, False
    if "CUBHMA_UNIFIED_3P4P_PER_PEER_RX_SIO" not in source:
        raise ValueError("The per-peer 3P/4P SIO patch has not been applied.")
    if "sNativeTransportStarted" not in source:
        raise ValueError("Expected the current runtime SIO role patch; source state differs.")

    # Three parsers are enough: each console receives from three peers, never
    # from itself. Event payloads are 6 words. Eight-word diagnostic frames are
    # validated and dropped without storing their words.
    source = once(
        source,
        "    u16 rxBuf[SIO_MAX_WORDS];\n};\n\nstruct SioState {\n"
        "    u8 active;\n"
        "    /* One framing state per remote GBA ID. The peers transmit independent\n"
        "     * word streams during the same multiplayer transfers. */\n"
        "    struct SioRxState rx[4];",
        "    u16 rxBuf[6];\n};\n\nstruct SioState {\n"
        "    u8 active;\n"
        "    /* One compact framing state per remote peer; local ID is mapped out. */\n"
        "    struct SioRxState rx[3];",
        "compact per-peer receive state",
    )

    source = once(
        source,
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n"
        "/* Once a session starts, ID 0 keeps clocking even if that player leaves;\n"
        " * otherwise the remaining child windows would lose their clock source. */\n"
        "static volatile u8 sNativeTransportStarted;\n"
        "u8 SioGetDeviceId(void);\n",
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n"
        "u8 SioGetDeviceId(void);\n",
        "remove redundant clock latch",
    )

    old_set_role = r'''void SioSetNativeRole(u8 role)
{
    if (role <= CUBHMA_NATIVE_ROLE_JOIN)
    {
        sNativeRole = role;
        if (role != CUBHMA_NATIVE_ROLE_OFF)
        {
            sNativeTransportStarted = 1;
            if (sSio.active && SioGetDeviceId() == 0u)
                REG_SIOCNT |= SIOCNT_START;
        }
    }
}'''
    new_set_role = r'''void SioSetNativeRole(u8 role)
{
    if (role <= CUBHMA_NATIVE_ROLE_JOIN)
        sNativeRole = role;
}'''
    source = once(source, old_set_role, new_set_role, "runtime role setter")

    source = once(
        source,
        "for (i = 0; i < 4; i++)\n        sSio.rx[i].rxPhase = RX_WAIT_SYNC;",
        "for (i = 0; i < 3; i++)\n        sSio.rx[i].rxPhase = RX_WAIT_SYNC;",
        "three-parser reset loop",
    )
    source = once(
        source,
        "if (sNativeTransportStarted && SioGetDeviceId() == 0u)\n        REG_SIOCNT |= SIOCNT_START;",
        "if (SioGetDeviceId() == 0u)\n        REG_SIOCNT |= SIOCNT_START;",
        "always-clock-capable device zero in SioArm",
    )
    source = once(
        source,
        "static void SioRxWord(u8 sourceId, u16 w)\n{\n"
        "    struct SioRxState *rx;\n"
        "    if (sourceId >= 4u)\n        return;\n"
        "    rx = &sSio.rx[sourceId];",
        "static void SioRxWord(u8 peerSlot, u8 sourceId, u16 w)\n{\n"
        "    struct SioRxState *rx;\n"
        "    if (peerSlot >= 3u)\n        return;\n"
        "    rx = &sSio.rx[peerSlot];",
        "compact parser slot mapping",
    )
    source = once(
        source,
        "    case RX_DATA:\n"
        "        rx->rxBuf[rx->rxGot++] = w;\n"
        "        rx->rxSum = (u16)(rx->rxSum + w);",
        "    case RX_DATA:\n"
        "        /* Only movement/event frames need buffering. Diagnostic state\n"
        "         * frames can be checksummed and dropped without an 8-word buffer. */\n"
        "        if (rx->rxType == SIO_T_EVENT && rx->rxGot < 6u)\n"
        "            rx->rxBuf[rx->rxGot] = w;\n"
        "        rx->rxGot++;\n"
        "        rx->rxSum = (u16)(rx->rxSum + w);",
        "bounded receive payload buffer",
    )

    source = once(
        source,
        "    u8 localId;\n    u8 peer;\n",
        "    u8 localId;\n    u8 peer;\n    u8 peerSlot;\n",
        "peer slot local variable",
    )
    source = once(
        source,
        "    localId = SioGetDeviceId();\n"
        "    /* Every transfer carries one word from each of the four devices. Keep\n"
        "     * the receive phase independently aligned for every other device. */\n"
        "    for (peer = 0; peer < 4u; peer++)\n"
        "        if (peer != localId)\n"
        "            SioRxWord(peer, REG_SIOMULTI(peer));",
        "    localId = SioGetDeviceId();\n"
        "    /* One parser per remote source; skip the local hardware ID. */\n"
        "    for (peer = 0; peer < 4u; peer++)\n"
        "    {\n"
        "        if (peer == localId)\n"
        "            continue;\n"
        "        peerSlot = (peer < localId) ? peer : (u8)(peer - 1u);\n"
        "        SioRxWord(peerSlot, peer, REG_SIOMULTI(peer));\n"
        "    }",
        "remote device to compact parser mapping",
    )
    source = once(
        source,
        "if (sNativeTransportStarted && localId == 0u)\n        REG_SIOCNT |= SIOCNT_START;",
        "if (localId == 0u)\n        REG_SIOCNT |= SIOCNT_START;",
        "always-clock-capable device zero after each transfer",
    )
    source = once(
        source,
        "/* CUBHMA_UNIFIED_LINK_ID_MASTER: physical SIO master follows hardware device ID, not menu role. */\n"
        "/* CUBHMA_UNIFIED_3P4P_PER_PEER_RX_SIO: maintain an independent RX parser for each peer. */",
        "/* CUBHMA_UNIFIED_LINK_ID_MASTER: physical SIO master follows hardware device ID, not menu role. */\n"
        "/* CUBHMA_UNIFIED_3P4P_PER_PEER_RX_SIO: maintain an independent RX parser for each peer. */\n"
        "/* " + MARKER + " */",
        "memory compaction marker",
    )
    if "sNativeTransportStarted" in source or "SioRxState rx[4]" in source:
        raise ValueError("SIO memory validation failed.")
    return source, True


def patch_main(source: str) -> tuple[str, bool]:
    if MARKER in source:
        return source, False
    if "CUBHMA_UNIFIED_3P4P_PER_PEER_RX" not in source:
        raise ValueError("The per-peer native 3P/4P payload patch has not been applied.")

    changed = False

    # Disable payload counter increments only for unified runtime builds. Those
    # counters were used solely by SioSendSonda, which is disabled below.
    bump_func = (
        "static void __attribute__((noinline)) Bump(u32 idx)\n"
        "{\n"
        "    ((volatile u32 *)&g_state)[idx]++;\n"
        "}\n"
    )
    source = once(
        source,
        bump_func,
        "#if !defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n" + bump_func + "#endif\n",
        "counter helper compile-out",
    )
    source = once(
        source,
        "#define BUMP_OFF(f)  __builtin_offsetof(struct PayloadState, f)\n",
        "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n"
        "#define BUMPF(f) ((void)0)\n"
        "#else\n"
        "#define BUMP_OFF(f)  __builtin_offsetof(struct PayloadState, f)\n",
        "unified no-op counters",
    )
    source = once(
        source,
        "#define BUMPF(f) do { if (BUMP_SONDA(BUMP_OFF(f))) Bump(BUMP_HW(BUMP_OFF(f)) / 4u); } while (0)\n",
        "#define BUMPF(f) do { if (BUMP_SONDA(BUMP_OFF(f))) Bump(BUMP_HW(BUMP_OFF(f)) / 4u); } while (0)\n"
        "#endif /* !PAYLOAD_NATIVE_SIO_RUNTIME */\n",
        "close counter conditional",
    )

    # The serial telemetry frame is not part of game traffic. Omitting it from
    # the unified ROM saves code and lets the receive parser store only 6 words.
    source = once(
        source,
        "static u32 sStateTimer;\n",
        "#if !defined(PAYLOAD_NATIVE_SIO_RUNTIME)\nstatic u32 sStateTimer;\n#endif\n",
        "telemetry timer conditional",
    )
    source = once(
        source,
        "static int SioSendSonda(u32 cb2)\n{",
        "#if !defined(PAYLOAD_NATIVE_SIO_RUNTIME)\nstatic int SioSendSonda(u32 cb2)\n{",
        "telemetry function conditional start",
    )
    source = once(
        source,
        "    return SioSendFrame(SIO_T_STATE, w, 8);\n}\n",
        "    return SioSendFrame(SIO_T_STATE, w, 8);\n}\n#endif /* !PAYLOAD_NATIVE_SIO_RUNTIME */\n",
        "telemetry function conditional end",
    )
    source = once(
        source,
        "            SioSendSonda(cb2);\n            sStateTimer = 0;\n",
        "#if !defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "            SioSendSonda(cb2);\n            sStateTimer = 0;\n"
        "#endif\n",
        "initial telemetry send conditional",
    )
    source = once(
        source,
        "        if (++sStateTimer >= 60)\n"
        "        {\n"
        "            if (SioSendSonda(cb2))\n"
        "                sStateTimer = 0;\n"
        "        }\n",
        "#if !defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "        if (++sStateTimer >= 60)\n"
        "        {\n"
        "            if (SioSendSonda(cb2))\n"
        "                sStateTimer = 0;\n"
        "        }\n"
        "#endif\n",
        "periodic telemetry conditional",
    )

    # Preserve the IRQ heartbeat used by SioTick, but discard its diagnostic-only
    # counters in the unified build to reclaim EWRAM. The legacy builds retain
    # every counter exactly as before.
    counter_match = re.search(r"struct SioCounters\s*\{.*?^\};\s*\n\s*struct SioCounters g_sio;", source, re.S | re.M)
    if not counter_match:
        raise ValueError("Could not find native SIO diagnostic counter structure.")
    full_counter_block = counter_match.group(0)
    struct_start = full_counter_block.index("struct SioCounters")
    struct_end = full_counter_block.index(";\n\n", full_counter_block.index("struct SioCounters g_sio;")) + 1
    full_decl = full_counter_block[:full_counter_block.index("struct SioCounters g_sio;")]
    compact_block = (
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "struct SioCounters { u32 irqs; };\n"
        "#else\n"
        + full_decl
        + "#endif\n"
        "struct SioCounters g_sio;\n"
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "#define SIO_COUNT_INC(field) ((void)0)\n"
        "#else\n"
        "#define SIO_COUNT_INC(field) (g_sio.field++)\n"
        "#endif"
    )
    source = source[:counter_match.start()] + compact_block + source[counter_match.end():]

    # Replace diagnostic-only increment expressions (irqs stays live for SioTick).
    source, count = re.subn(
        r"g_sio\.(ieScrubs|framesTx|wordsTx|zeroWords|txFull|wordsRx|frameErr|resync|framesRx|rxFull|errFlag|repairs|drained)\+\+;",
        lambda m: f"SIO_COUNT_INC({m.group(1)});",
        source,
    )
    if count < 10:
        raise ValueError(f"Only {count} diagnostic counter increments were converted; expected at least 10.")

    # Counters are not read by anything except the optional serial probe.
    source = once(
        source,
        "u32 SioRepairCount(void)\n{\n    return g_sio.repairs;\n}",
        "u32 SioRepairCount(void)\n{\n#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n    return 0;\n#else\n    return g_sio.repairs;\n#endif\n}",
        "repair counter accessor",
    )
    source = once(
        source,
        "u32 SioScrubCount(void)\n{\n    return g_sio.ieScrubs;\n}",
        "u32 SioScrubCount(void)\n{\n#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n    return 0;\n#else\n    return g_sio.ieScrubs;\n#endif\n}",
        "scrub counter accessor",
    )

    source = once(
        source,
        "/* CUBHMA_UNIFIED_3P4P_PER_PEER_RX: receive independent streams from all three remote slots. */",
        "/* CUBHMA_UNIFIED_3P4P_PER_PEER_RX: receive independent streams from all three remote slots. */\n"
        "/* " + MARKER + ": remove serial diagnostics from the unified ROM to fit EWRAM. */",
        "main memory compaction marker",
    )

    return source, True


def backup_write(path: Path, content: str) -> None:
    backup = Path(str(path) + ".pre-unified-3p4p-memory-compact.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    sio_path = SUBMODULE / "payload" / "sio.c"
    main_path = SUBMODULE / "payload" / "main.c"
    for path in (sio_path, main_path):
        if not path.is_file():
            print(f"error: required source file not found: {path}", file=sys.stderr)
            return 1

    try:
        sio_new, sio_changed = patch_sio(sio_path.read_text(encoding="utf-8"))
        main_new, main_changed = patch_main(main_path.read_text(encoding="utf-8"))

        for path, content, changed in (
            (sio_path, sio_new, sio_changed),
            (main_path, main_new, main_changed),
        ):
            if changed:
                backup_write(path, content)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied unified-only memory compaction:")
    print(f"  payload/sio.c:  {'updated' if sio_changed else 'already compacted'}")
    print(f"  payload/main.c: {'updated' if main_changed else 'already compacted'}")
    print("  Three compact receive parsers remain; serial telemetry/counters are disabled only for the unified ROM.")
    print("  Device ID 0 continues clocking after its player disconnects.")
    print("")
    print("Rebuild with:")
    print('  wsl -e bash -lc "cd /mnt/c/src/pokeemerald && make -j2"')
    print("  .\\tools\\prepare_unified_native_link_rom.ps1")
    print("The linker memory guard remains enabled; if it still fails, send the full output.")
    print("Backups use .pre-unified-3p4p-memory-compact.bak.")
    print("This change needs compilation and mGBA testing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

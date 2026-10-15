#!/usr/bin/env python3
"""Restore ID-0 SIO clocking and gate gameplay behind a peer-detection lobby.

Run after the compact unified 3P/4P patch:
  python tools/patch_unified_loading_gate.py

Host chooses 2, 3, or 4 players. Joiners wait in a blocking menu; the host's
Start option appears only after the expected number of peers has sent valid
native-SIO event frames. Start is sent as EVENT_START to release joiners.
This is a source transformation and still requires compilation/mGBA testing.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBMODULE = ROOT / "third_party" / "gen3-poke-multiplayer"
SIO_PATH = SUBMODULE / "payload" / "sio.c"
MAIN_PATH = SUBMODULE / "payload" / "main.c"
MARKER = "CUBHMA_UNIFIED_LOADING_GATE"


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {count}.")
    return source.replace(old, new, 1)


def replace_function(source: str, name: str, replacement: str, label: str) -> str:
    pattern = rf"(?:static )?[^\n]+\b{name}\(void\)\s*\{{.*?^\}}"
    updated, count = re.subn(
        pattern, lambda _: replacement, source, count=1, flags=re.S | re.M
    )
    if count != 1:
        raise ValueError(f"Could not uniquely replace {label} (matches={count}).")
    return updated


def patch_sio(source: str) -> tuple[str, bool]:
    if "CUBHMA_UNIFIED_3P4P_MEMORY_COMPACT" not in source:
        raise ValueError("Expected the compact unified 3P/4P SIO patch first.")
    if "CUBHMA_UNIFIED_HOST_MASTER_ROLE_CLOCK" not in source:
        if "sNativeTransportStarted" not in source:
            return source, False
        raise ValueError("Unexpected SIO role-latch source; refusing unsafe edits.")

    # Only hardware device ID 0 clocks serial transfers. The lobby role is an
    # application choice and must not let two windows both force SIOCNT.START.
    source = once(
        source,
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n"
        "/* The selected Host starts the link; device 0 keeps clocking it. */\n"
        "static volatile u8 sNativeTransportStarted;\n",
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n",
        "bad host-clock latch declaration",
    )
    setter = r'''void SioSetNativeRole(u8 role)
{
    if (role <= CUBHMA_NATIVE_ROLE_JOIN)
    {
        sNativeRole = role;
        if (role == CUBHMA_NATIVE_ROLE_HOST)
        {
            sNativeTransportStarted = 1;
            if (sSio.active)
                REG_SIOCNT |= SIOCNT_START;
        }
    }
}'''
    source = once(
        source,
        setter,
        "void SioSetNativeRole(u8 role)\n"
        "{\n"
        "    if (role <= CUBHMA_NATIVE_ROLE_JOIN)\n"
        "        sNativeRole = role;\n"
        "}",
        "host role setter",
    )
    source = once(
        source,
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)\n"
        "    {\n"
        "        sNativeTransportStarted = 1;\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "    }\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)",
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (SioGetDeviceId() == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;\n"
        "#elif defined(PAYLOAD_NATIVE_SIO_MASTER)",
        "bad SioArm host-start block",
    )
    source = once(
        source,
        "if (sNativeTransportStarted && localId == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;",
        "if (localId == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;",
        "bad serial IRQ clock gate",
    )
    source = once(
        source,
        "/* CUBHMA_UNIFIED_HOST_MASTER_ROLE_CLOCK: role starts link, hardware ID 0 clocks it. */\n",
        "",
        "host clock marker",
    )
    if "sNativeTransportStarted" in source:
        raise ValueError("The host-driven clock latch still remains after patching.")
    return source, True


def replace_block_between(source: str, start_token: str, end_token: str,
                          replacement: str, label: str) -> str:
    start = source.find(start_token)
    if start < 0:
        raise ValueError(f"Could not find start of {label}.")
    end = source.find(end_token, start)
    if end < 0:
        raise ValueError(f"Could not find end of {label}.")
    return source[:start] + replacement + source[end:]


def patch_main(source: str) -> tuple[str, bool]:
    if MARKER in source:
        return source, False
    if "CUBHMA_UNIFIED_3P4P_PER_PEER_RX" not in source:
        raise ValueError("Apply the unified 3P/4P patch before the loading gate.")

    # EVENT_START is a NetEvent kind; its presence is inspected by the native
    # SIO receive callback before the normal mailbox consumer runs.
    source = once(
        source,
        "#define EVENT_CLUB      7u",
        "#define EVENT_CLUB      7u\n"
        "/* Host releases joiners after every requested peer has been detected. */\n"
        "#define EVENT_START     8u",
        "EVENT_START kind",
    )

    # These flags are written from the serial IRQ callback and read by the
    # lobby tick, so byte-sized volatile state avoids a torn shared update.
    source = once(
        source,
        "u8 SioGetDeviceId(void);\n\nint SioDeliverFrame(u8 sourceId",
        "u8 SioGetDeviceId(void);\n"
        "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n"
        "static volatile u8 sNativeDetectedMask;\n"
        "static volatile u8 sNativeGameStarted;\n"
        "#endif\n\n"
        "int SioDeliverFrame(u8 sourceId",
        "native SIO lobby flags",
    )

    source = once(
        source,
        "    if (remoteSlot >= N_REMOTES)\n"
        "        return 1;\n\n"
        "    head = g_mailbox.rxHead;",
        "    if (remoteSlot >= N_REMOTES)\n"
        "        return 1;\n"
        "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n"
        "    sNativeDetectedMask |= (u8)(1u << remoteSlot);\n"
        "    if (SioGetNativeRole() == CUBHMA_NATIVE_ROLE_JOIN\n"
        "        && (u8)words[0] == EVENT_START)\n"
        "        sNativeGameStarted = 1;\n"
        "#endif\n\n"
        "    head = g_mailbox.rxHead;",
        "valid-peer detection and host start receive",
    )

    # Replace the local lobby's label/action block without relying on whether a
    # prior revision still carries a Close label.
    label_start = "static const u8 sNativeLobbyTextHost[] ="
    label_end = "static u8 sNativeLobbyMenuOpen;"
    labels = (
        "static const u8 sNativeLobbyTextHost2[] =\n"
        "    {0xC2, 0xE3, 0xE7, 0xE8, 0x00, 0x5C, 0xA3, 0xCA, 0x5D, 0xFF}; /* Host (2P) */\n"
        "static const u8 sNativeLobbyTextHost3[] =\n"
        "    {0xC2, 0xE3, 0xE7, 0xE8, 0x00, 0x5C, 0xA4, 0xCA, 0x5D, 0xFF}; /* Host (3P) */\n"
        "static const u8 sNativeLobbyTextHost4[] =\n"
        "    {0xC2, 0xE3, 0xE7, 0xE8, 0x00, 0x5C, 0xA5, 0xCA, 0x5D, 0xFF}; /* Host (4P) */\n"
        "static const u8 sNativeLobbyTextJoin[] =\n"
        "    {0xC4, 0xE3, 0xDD, 0xE2, 0xFF}; /* Join */\n"
        "static const u8 sNativeLobbyTextDisconnect[] =\n"
        "    {0xBE, 0xDD, 0xE7, 0xD7, 0xE3, 0xE2, 0xE2, 0xD9, 0xD7, 0xE8, 0xFF}; /* Disconnect */\n"
        "static const u8 sNativeLobbyTextWaiting[] =\n"
        "    {0xD1, 0xD5, 0xDD, 0xE8, 0xDD, 0xE2, 0xDB, 0xFF}; /* Waiting */\n"
        "static const u8 sNativeLobbyTextStart[] =\n"
        "    {0xCA, 0xE8, 0xD5, 0xE6, 0xE8, 0xFF}; /* Start */\n\n"
        "static struct PayloadMenuAction sNativeLobbyActions[4] =\n"
        "{\n"
        "    {sNativeLobbyTextHost2, {.void_u8 = 0}},\n"
        "    {sNativeLobbyTextHost3, {.void_u8 = 0}},\n"
        "    {sNativeLobbyTextHost4, {.void_u8 = 0}},\n"
        "    {sNativeLobbyTextJoin,  {.void_u8 = 0}},\n"
        "};\n\n"
    )
    source = replace_block_between(
        source, label_start, label_end, labels, "lobby labels/actions"
    )

    source = once(
        source,
        "static u8 sNativeLobbyMenuOpen;\n"
        "static u8 sNativeLobbyCursor;\n"
        "static u8 sNativeLobbyCount;\n"
        "static u8 sNativeLeavePending;\n"
        "static u16 sNativeLeaveWait;",
        "static u8 sNativeLobbyMenuOpen;\n"
        "static u8 sNativeLobbyCursor;\n"
        "static u8 sNativeLobbyCount;\n"
        "static u8 sNativeLeavePending;\n"
        "static u16 sNativeLeaveWait;\n"
        "static u8 sNativeExpectedPlayers;\n"
        "static u8 sNativeWaitScreen;\n"
        "static u8 sNativeWaitReadyShown;\n"
        "static u8 sNativeWaitTicker;",
        "loading lobby state",
    )

    # Host chooses the exact expected player count. The same window is
    # repurposed as the loading screen, so the controls remain locked.
    open_fn = r'''static void NativeLobbyOpen(void)
{
    u8 windowId;
    u8 role = SioGetNativeRole();

    if (role == CUBHMA_NATIVE_ROLE_OFF)
    {
        sNativeLobbyActions[0].text = sNativeLobbyTextHost2;
        sNativeLobbyActions[1].text = sNativeLobbyTextHost3;
        sNativeLobbyActions[2].text = sNativeLobbyTextHost4;
        sNativeLobbyActions[3].text = sNativeLobbyTextJoin;
        sNativeLobbyCount = 4u;
    }
    else
    {
        sNativeLobbyActions[0].text = sNativeLobbyTextDisconnect;
        sNativeLobbyCount = 1u;
    }

    sNativeLobbyCursor = 0;
    ((void (*)(void))LoadMessageBoxAndBorderGfx)();
    windowId = ((u8 (*)(u8))AddStartMenuWindow)(sNativeLobbyCount);
    if (windowId == 0xFFu)
        return;

    sNativeLobbyMenuOpen = 1;
    LockPlayerFieldControls();
    FreezeObjectEvents();
    PlayerFreeze();
    StopPlayerAvatar();
    gMain_newKeys = 0;
    gMain_heldKeys = 0;
    NativeLobbyDraw(sNativeLobbyCursor);
}'''
    source = replace_function(source, "NativeLobbyOpen", open_fn, "NativeLobbyOpen")

    # Insert peer counting/loading-window helpers before the existing session
    # reset function.
    helpers = r'''static u8 NativeDetectedCount(void)
{
    u8 mask = sNativeDetectedMask;
    u8 count = 0;
    if (mask & 1u) count++;
    if (mask & 2u) count++;
    if (mask & 4u) count++;
    return count;
}

static void NativeLobbyWaitOpen(void)
{
    sNativeLobbyActions[0].text = sNativeLobbyTextWaiting;
    sNativeLobbyCount = 1u;
    sNativeLobbyCursor = 0;
    sNativeWaitScreen = 1;
    sNativeWaitReadyShown = 0;
    sNativeWaitTicker = 0;
    NativeLobbyDraw(0);
}

'''
    if "static u8 NativeDetectedCount(void)" not in source:
        source = once(
            source,
            "static void NativeLobbyResetSession(u8 role)\n{",
            helpers + "static void NativeLobbyResetSession(u8 role)\n{",
            "loading-screen helper insertion",
        )

    # Reset volatile peer/start state whenever the user enters or leaves a room.
    source = once(
        source,
        "    SioSetNativeRole(role);\n}",
        "    sNativeDetectedMask = 0;\n"
        "    sNativeGameStarted = 0;\n"
        "    sNativeWaitScreen = 0;\n"
        "    sNativeWaitReadyShown = 0;\n"
        "    sNativeWaitTicker = 0;\n"
        "    SioSetNativeRole(role);\n}",
        "session reset state",
    )

    tick_fn = r'''static void EmitEvent(u8 type, u8 dir, u8 speed, s16 x, s16 y);

static int NativeLobbyMenuTick(void)
{
    s8 choice;
    u8 i;

    if (sNativeLeavePending)
    {
        if ((g_mailbox.txHead == g_mailbox.txTail && SioTxIdle())
            || sNativeLeaveWait >= 120u)
        {
            NativeLobbyResetSession(CUBHMA_NATIVE_ROLE_OFF);
            sNativeLeavePending = 0;
            sNativeLeaveWait = 0;
        }
        else
        {
            sNativeLeaveWait++;
        }
        return 0;
    }

    if (sNativeLobbyMenuOpen)
    {
        choice = ((s8 (*)(void))Menu_ProcessInputNoWrap)();
        gMain_newKeys = 0;
        gMain_heldKeys = 0;

        if (sNativeWaitScreen)
        {
            /* A small heartbeat lets every console prove it is present while
             * the normal overworld tick is paused by this blocking screen. */
            if (++sNativeWaitTicker >= 20u)
            {
                sNativeWaitTicker = 0;
                EmitEvent(EVENT_STATUS, ST_OVERWORLD, 0, 0, 0);
            }

            if (SioGetNativeRole() == CUBHMA_NATIVE_ROLE_HOST)
            {
                if (!sNativeWaitReadyShown
                    && sNativeExpectedPlayers >= 2u
                    && NativeDetectedCount() >= (u8)(sNativeExpectedPlayers - 1u))
                {
                    sNativeLobbyActions[0].text = sNativeLobbyTextStart;
                    sNativeWaitReadyShown = 1;
                    NativeLobbyDraw(0);
                    return 1;
                }

                if (sNativeWaitReadyShown && choice == 0)
                {
                    /* Repeated starts tolerate a lost frame or a late joiner's
                     * next serial transfer without changing movement traffic. */
                    for (i = 0; i < 3u; i++)
                        EmitEvent(EVENT_START, sNativeExpectedPlayers, 0, 0, 0);
                    sNativeGameStarted = 1;
                    sNativeWaitScreen = 0;
                    NativeLobbyClose();
                    return 1;
                }
            }
            else if (sNativeGameStarted)
            {
                sNativeWaitScreen = 0;
                NativeLobbyClose();
                return 1;
            }

            /* B leaves the room while still on the loading screen. */
            if (choice == -1)
            {
                NativeLobbyBeginLeave();
                sNativeWaitScreen = 0;
                NativeLobbyClose();
                return 1;
            }
            return 1;
        }

        if (choice == -1)
        {
            NativeLobbyClose();
            return 1;
        }

        if (choice >= 0 && choice < sNativeLobbyCount)
        {
            if (SioGetNativeRole() == CUBHMA_NATIVE_ROLE_OFF)
            {
                u8 role = (choice < 3)
                    ? CUBHMA_NATIVE_ROLE_HOST
                    : CUBHMA_NATIVE_ROLE_JOIN;
                NativeLobbyResetSession(role);
                sNativeExpectedPlayers = (choice < 3) ? (u8)(choice + 2) : 0u;
                NativeLobbyWaitOpen();
            }
            else
            {
                NativeLobbyBeginLeave();
                NativeLobbyClose();
            }
        }
        return 1;
    }

    if (g_lobbyRequest == CUBHMA_LOBBY_REQUEST_MAGIC
        && g_state.inOverworld
        && !ArePlayerFieldControlsLocked())
    {
        g_lobbyRequest = 0;
        NativeLobbyOpen();
        return 1;
    }

    return 0;
}'''
    pattern = r"static int NativeLobbyMenuTick\(void\)\s*\{.*?^\}"
    source, count = re.subn(
        pattern, lambda _: tick_fn, source, count=1, flags=re.S | re.M
    )
    if count != 1:
        raise ValueError("Could not uniquely replace NativeLobbyMenuTick.")

    source = once(
        source,
        "/* CUBHMA_UNIFIED_3P4P_PER_PEER_RX: receive independent streams from all three remote slots. */",
        "/* CUBHMA_UNIFIED_3P4P_PER_PEER_RX: receive independent streams from all three remote slots. */\n"
        "/* " + MARKER + ": host waits for every requested peer before Start. */",
        "loading gate marker",
    )

    return source, True


def write_backup(path: Path, new_source: str, suffix: str) -> None:
    backup = Path(str(path) + suffix)
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(new_source, encoding="utf-8", newline="\n")


def main() -> int:
    for path in (SIO_PATH, MAIN_PATH):
        if not path.is_file():
            print(f"error: required source file not found: {path}", file=sys.stderr)
            return 1

    try:
        old_sio = SIO_PATH.read_text(encoding="utf-8")
        old_main = MAIN_PATH.read_text(encoding="utf-8")
        new_sio, sio_changed = patch_sio(old_sio)
        new_main, main_changed = patch_main(old_main)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # All anchors are validated before either source file is written.
    if sio_changed:
        write_backup(SIO_PATH, new_sio, ".pre-unified-loading-gate.bak")
    if main_changed:
        write_backup(MAIN_PATH, new_main, ".pre-unified-loading-gate.bak")

    print("Applied unified native multiplayer loading gate:")
    print(f"  payload/sio.c:  {'updated' if sio_changed else 'already using ID-0 clocking'}")
    print(f"  payload/main.c: {'updated' if main_changed else 'already patched'}")
    print("  Host options: 2P, 3P, 4P. Joiners wait for the Host.")
    print("  Start is enabled only after the host detects the requested number of peers.")
    print("  SIO remains clocked by hardware device ID 0, not by the Host/Join menu choice.")
    print("")
    print("Build/package:")
    print('  .\\tools\\prepare_unified_native_link_rom.ps1')
    print("The patch needs compilation and mGBA testing; do not bypass any linker guard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

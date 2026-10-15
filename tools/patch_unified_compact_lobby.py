#!/usr/bin/env python3
"""Compact the unified two-player lobby to fit the fixed payload memory window.

This first-milestone trade-off keeps the in-game Host/Join choice and normal
single-player mode, but omits mid-session Disconnect from the prototype menu.
Once Host or Join is selected, return to single-player by restarting the game.
The legacy master/slave and adapter builds are not changed by this script.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_COMPACT_LOBBY"

ACTIONS = '''static struct PayloadMenuAction sNativeLobbyActions[2] =
{
    {sNativeLobbyTextHost, {.void_u8 = 0}},
    {sNativeLobbyTextJoin, {.void_u8 = 0}},
};'''

NEW_OPEN = '''static void NativeLobbyOpen(void)
{
    u8 windowId;

    /* This compact prototype chooses a role once per game launch. */
    if (SioGetNativeRole() != CUBHMA_NATIVE_ROLE_OFF)
        return;

    sNativeLobbyActions[0].text = sNativeLobbyTextHost;
    sNativeLobbyActions[1].text = sNativeLobbyTextJoin;
    sNativeLobbyCount = 2u;

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

NEW_RESET = '''static void NativeLobbyResetSession(u8 role)
{
    /* Clear events accumulated before Host/Join was selected. */
    g_mailbox.txHead = g_mailbox.txTail = 0;
    g_mailbox.rxHead = g_mailbox.rxTail = 0;
    g_mailbox.rxApplied = 0;

    sHavePlayerPos = 0;
    sFramesSinceSync = 0;
    sSeq = 0;
    sEntrySyncsLeft = 0;
    sEntrySyncTimer = 0;
    sCardTxIdx = 0;
    sCardTxTimer = 0;
    sCardReady = 0;

#ifdef PAYLOAD_NATIVE_SIO
    sSioSnapshotTxPending = 0;
    sSioSnapshotHaveLastSample = 0;
    sSioSnapshotHaveActive = 0;
    sSioSnapshotRxVersion = 0;
    sSioSnapshotAppliedVersion = 0;
    sSioSnapshotHeartbeatFrames = 0;
#endif

    SioSetNativeRole(role);
}'''

NEW_TICK = '''static int NativeLobbyMenuTick(void)
{
    s8 choice;

    if (sNativeLobbyMenuOpen)
    {
        choice = ((s8 (*)(void))Menu_ProcessInputNoWrap)();
        gMain_newKeys = 0;
        gMain_heldKeys = 0;

        if (choice == -1)
        {
            NativeLobbyClose();
            return 1;
        }
        if (choice >= 0 && choice < 2)
        {
            NativeLobbyResetSession(choice == 0
                ? CUBHMA_NATIVE_ROLE_HOST
                : CUBHMA_NATIVE_ROLE_JOIN);
            NativeLobbyClose();
        }
        return 1;
    }

    if (g_state.inOverworld
        && !ArePlayerFieldControlsLocked()
        && SioGetNativeRole() == CUBHMA_NATIVE_ROLE_OFF
        && (gMain_newKeys & SELECT_BUTTON))
    {
        gMain_newKeys = (u16)(gMain_newKeys & ~SELECT_BUTTON);
        gMain_heldKeys = (u16)(gMain_heldKeys & ~SELECT_BUTTON);
        NativeLobbyOpen();
        return 1;
    }

    return 0;
}'''


def replace_region(source: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _: replacement, source, count=1, flags=re.S)
    if count != 1:
        raise ValueError(f"Could not uniquely replace {label} (matches={count}); no files changed.")
    return updated


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_unified_compact_lobby.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    path = root / "payload" / "main.c"
    if not path.is_file():
        print(f"error: payload source not found: {path}", file=sys.stderr)
        return 1

    try:
        source = path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Compact unified lobby is already applied.")
            return 0
        if "CUBHMA_UNIFIED_LOBBY_MENU" not in source or "CUBHMA_UNIFIED_PAYLOAD_SIZE_FIX" not in source:
            raise ValueError("Expected unified lobby and payload-size patches first; no files changed.")

        source = replace_region(
            source,
            r"static const u8 sNativeLobbyTextDisconnect\[\]\s*=.*?;\s*static const u8 sNativeLobbyTextClose\[\]\s*=.*?;\s*",
            "",
            "unused Disconnect/Close text constants",
        )
        source = replace_region(
            source,
            r"static struct PayloadMenuAction sNativeLobbyActions\[3\]\s*=\s*\{.*?\};",
            ACTIONS,
            "lobby action table",
        )
        source = replace_region(
            source,
            r"static void NativeLobbyOpen\(void\)\s*\{.*?\n\}\s*\n\s*static void NativeLobbyResetSession",
            NEW_OPEN + "\n\nstatic void NativeLobbyResetSession",
            "lobby open function",
        )
        source = replace_region(
            source,
            r"static void NativeLobbyResetSession\(u8 role\)\s*\{.*?\n\}\s*\n\s*static int NativeLobbyMenuTick",
            NEW_RESET + "\n\nstatic int NativeLobbyMenuTick",
            "session reset function",
        )
        source = replace_region(
            source,
            r"static int NativeLobbyMenuTick\(void\)\s*\{.*?\n\}\s*\n#endif /\* PAYLOAD_NATIVE_SIO_RUNTIME \*/",
            NEW_TICK + "\n#endif /* PAYLOAD_NATIVE_SIO_RUNTIME */",
            "lobby input function",
        )

        marker = "/* " + MARKER + ": Host/Join once per launch; restart to disconnect. */\n"
        anchor = "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n/* CUBHMA_UNIFIED_LOBBY_MENU"
        if source.count(anchor) != 1:
            raise ValueError("Could not insert compact-lobby marker; no files changed.")
        source = source.replace(anchor, anchor.replace("#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n", "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n" + marker), 1)

        # The removed disconnect branch is intentionally not available in this prototype.
        if "sNativeLobbyTextClose" in source or "sNativeLobbyTextDisconnect" in source:
            raise ValueError("Old lobby action strings remain after compaction; no files changed.")
        if source.count("CUBHMA_UNIFIED_COMPACT_LOBBY") != 1:
            raise ValueError("Compact lobby marker validation failed; no files changed.")

        backup = Path(str(path) + ".pre-compact-lobby.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(source, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied compact unified Host/Join lobby to payload/main.c.")
    print("Trade-off: disconnect by restarting the game; the legacy master/slave paths are untouched.")
    print(f"Backup: {backup}")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1 and inspect the linker result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

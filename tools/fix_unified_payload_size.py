#!/usr/bin/env python3
"""Reclaim unified payload space while preserving the runtime Host/Join prototype.

The first unified build crossed HANDOFF_BASE because its session reset clears
many per-remote fields that are overwritten before a peer is used. Reset only
the state that matters on disconnect; clean queue heads/tails for both roles.
Also make the hard-resync signed comparison explicit.
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_PAYLOAD_SIZE_FIX"

OLD_RESET = r'''static void NativeLobbyResetSession(u8 role)
{
    u32 i;

    /* A new session starts from fresh queues and fresh peer state, not from
     * stale steps collected during single-player or from a previous lobby. */
    g_mailbox.txHead = 0;
    g_mailbox.txTail = 0;
    g_mailbox.rxHead = 0;
    g_mailbox.rxTail = 0;
    g_mailbox.rxApplied = 0;

    if (sDoorState != DOOR_ST_NONE)
        DoorAbort();

    for (i = 0; i < N_REMOTES; i++)
    {
        struct Remote *r = &g_remotes[i];
        if (r->state == STATE_SPAWNED || r->objectId < OBJECT_EVENTS_COUNT)
            ForgetRemote(r);
        r->state = STATE_IDLE;
        r->objectId = OBJECT_EVENTS_COUNT;
        r->known = 0;
        r->mapKey = 0;
        r->targetX = 0;
        r->targetY = 0;
        r->gender = 0;
        r->avatarState = 0;
        r->status = ST_OVERWORLD;
        r->statusAge = 0;
        r->qHead = 0;
        r->qTail = 0;
        r->lastEnqSeq = 0;
        r->forceResync = 1;
        r->cardRxBitmap = 0;
        r->settled = 0;
        r->driftRun = 0;
        r->spawnCooldown = 0;
    }

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

NEW_RESET = r'''static void NativeLobbyResetSession(u8 role)
{
    u32 i;

    g_mailbox.txHead = g_mailbox.txTail = 0;
    g_mailbox.rxHead = g_mailbox.rxTail = 0;
    g_mailbox.rxApplied = 0;
    sHavePlayerPos = 0;

    /* Only disconnect needs object cleanup. On first Host/Join selection the
     * remote slots are already idle; don't spend payload bytes re-zeroing every
     * field that the next received peer event overwrites before use. */
    if (role == CUBHMA_NATIVE_ROLE_OFF)
    {
        if (sDoorState != DOOR_ST_NONE)
            DoorAbort();

        for (i = 0; i < N_REMOTES; i++)
        {
            struct Remote *r = &g_remotes[i];
            if (r->objectId < OBJECT_EVENTS_COUNT)
                ForgetRemote(r);
            r->state = STATE_IDLE;
            r->objectId = OBJECT_EVENTS_COUNT;
            r->known = 0;
            r->status = ST_OVERWORLD;
            r->qHead = 0;
            r->qTail = 0;
            r->cardRxBitmap = 0;
            r->forceResync = 1;
            r->settled = 0;
        }
        sCardReady = 0;
    }

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

def write_backup(path: Path, data: str) -> None:
    backup = Path(str(path) + ".pre-unified-size-fix.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(data, encoding="utf-8", newline="\n")

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_unified_payload_size.py <path-to-third_party/gen3-poke-multiplayer>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    main_path = root / "payload" / "main.c"
    if not main_path.is_file():
        print(f"error: payload source not found: {main_path}", file=sys.stderr)
        return 1
    try:
        source = main_path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Unified payload-size fix is already applied.")
            return 0
        if "CUBHMA_UNIFIED_LOBBY_MENU" not in source:
            raise ValueError("The unified runtime lobby patch is missing.")
        if source.count(OLD_RESET) != 1:
            raise ValueError("Cannot locate the expected NativeLobbyResetSession function exactly once.")
        source = source.replace(OLD_RESET, NEW_RESET, 1)
        source = source.replace(
            "gap > NATIVE_SNAPSHOT_HARD_RESYNC_GAP",
            "gap > (s32)NATIVE_SNAPSHOT_HARD_RESYNC_GAP",
            1,
        )
        marker_anchor = "static void NativeLobbyResetSession(u8 role)\n{"
        if source.count(marker_anchor) != 1:
            raise ValueError("Cannot insert the unified payload-size marker.")
        source = source.replace(
            marker_anchor,
            marker_anchor + "\n    /* " + MARKER + " */",
            1,
        )
        if "gap > (s32)NATIVE_SNAPSHOT_HARD_RESYNC_GAP" not in source:
            raise ValueError("Failed to validate signed resync comparison.")
        write_backup(main_path, source)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("Unified payload-size fix applied to payload/main.c.")
    print("The session reset no longer clears unused peer fields when first starting Host/Join.")
    print("Backup: payload/main.c.pre-unified-size-fix.bak")
    print("Rebuild with tools/prepare_unified_native_link_rom.ps1.")
    print("If the linker still reports overlap, do not move HANDOFF_BASE; more code-size reduction is required.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

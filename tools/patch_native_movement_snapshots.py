#!/usr/bin/env python3
"""Add symmetric 20 Hz compact movement snapshots to the native-SIO payload.

Samples each local player every three VBlanks (20 Hz at 60 FPS), sends a compact
four-word snapshot only when state changes, and reconciles the remote avatar
from the newest snapshot instead of queueing every predicted step. Reliable
events remain enabled for entry/map transitions, trainer cards, and statuses.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_NATIVE_MOVEMENT_SNAPSHOTS"
SNAPSHOT_TAG = "CUBHMA_NATIVE_SNAPSHOT_RX_TX"
SAMPLE_FUNCTION = r'''#ifdef PAYLOAD_WITH_SIO
/* CUBHMA_NATIVE_MOVEMENT_SNAPSHOTS
 * Sample every 3 frames = 20 Hz, but only transmit changed snapshots. This
 * keeps the native cable below its limited word-rate while checking movement
 * at the requested cadence. Each packet is 4 words instead of a 6-word event.
 */
static void SampleNativeSnapshot(s16 x, s16 y, u8 dir, u8 speed, u32 mapKey)
{
    u16 words[4];
    u32 i;
    int changed = 0;

    if (++sSioSnapshotSampleFrames < 3u)
        return;
    sSioSnapshotSampleFrames = 0;

    words[0] = (u16)x;
    words[1] = (u16)y;
    words[2] = (u16)mapKey; /* mapGroup in high byte, mapNum in low byte */
    words[3] = (u16)((dir & 7u)
                   | ((speed & 7u) << 3)
                   | ((PlayerGender() & 1u) << 6)
                   | ((PlayerAvatarState() & 0xFFu) << 7));

    if (!sSioSnapshotHaveLastSample)
        changed = 1;
    else
        for (i = 0; i < 4u; i++)
            if (words[i] != sSioSnapshotLastSampleWords[i])
                changed = 1;

    if (!changed)
        return;

    for (i = 0; i < 4u; i++)
    {
        sSioSnapshotTxWords[i] = words[i];
        sSioSnapshotLastSampleWords[i] = words[i];
    }
    sSioSnapshotHaveLastSample = 1;
    sSioSnapshotTxPending = 1;
}
#endif

'''

CONSUME_FUNCTION = r'''#ifdef PAYLOAD_WITH_SIO
/* Apply the latest compact snapshot independently of the reliable-event queue.
 * A newer snapshot replaces an older one, so missed frames cannot build a
 * backlog. The avatar animates one tile at a time toward the latest authority.
 */
static void ConsumeNativeSnapshot(void)
{
    u32 before, after;
    u16 words[4];
    u32 i;
    u32 slot;
    struct Remote *r;
    u32 mapKey, meta, via;
    s16 x, y, lx, ly;
    u8 dir, speed, gender, avatarState;
    u32 oe;
    s32 dx, dy, gap;
    u8 stepDir;
    s16 stepX, stepY;

    before = sSioSnapshotRxVersion;
    if (!(before & 1u) && before != 0u && before != sSioSnapshotAppliedVersion)
    {
        for (i = 0; i < 4u; i++)
            words[i] = sSioSnapshotRxWords[i];
        after = sSioSnapshotRxVersion;
        if (before == after && !(after & 1u))
        {
            for (i = 0; i < 4u; i++)
                sSioSnapshotActiveWords[i] = words[i];
            sSioSnapshotAppliedVersion = after;
            sSioSnapshotHaveActive = 1;
        }
    }

    if (!sSioSnapshotHaveActive || !g_state.inOverworld)
        return;

    mapKey = sSioSnapshotActiveWords[2];
    x = (s16)sSioSnapshotActiveWords[0];
    y = (s16)sSioSnapshotActiveWords[1];
    meta = sSioSnapshotActiveWords[3];
    dir = (u8)(meta & 7u);
    speed = (u8)((meta >> 3) & 7u);
    gender = (u8)((meta >> 6) & 1u);
    avatarState = (u8)((meta >> 7) & 0xFFu);

    /* Native cable mode has one remote peer. Wait for its reliable entry event
     * to create the avatar; the most recent snapshot stays available meanwhile.
     */
    for (slot = 0; slot < N_REMOTES; slot++)
        if (g_remotes[slot].known && g_remotes[slot].state == STATE_SPAWNED)
            break;
    if (slot >= N_REMOTES)
        return;

    r = &g_remotes[slot];
    if (!MapRemoteToLocal(r, mapKey, x, y, &lx, &ly, &via))
        return;

    r->known = 1;
    r->mapKey = mapKey;
    r->targetX = x;
    r->targetY = y;
    r->gender = gender;
    r->avatarState = avatarState;

    oe = ObjectEvent(r->objectId);
    SyncRemoteGraphics(r, oe);
    if (r->state != STATE_SPAWNED)
        return;
    oe = ObjectEvent(r->objectId);

    dx = (s32)lx - (s32)oe_currentX(oe);
    dy = (s32)ly - (s32)oe_currentY(oe);
    gap = AbsDiff(dx, 0) + AbsDiff(dy, 0);

    /* Large errors cannot be repaired by queued movement. Drop obsolete
     * per-peer moves and snap to the latest confirmed position. */
    if (r->forceResync || gap > DRIFT_TOLERANCE)
    {
        if (gap != 0)
            TeleportRemote(oe, lx, ly);
        r->forceResync = 0;
        r->settled = 0;
        r->driftRun = 0;
        if (gap > DRIFT_TOLERANCE)
            r->qTail = r->qHead;
        return;
    }

    if (gap == 0)
    {
        if (RemoteReadyForMovement(oe))
        {
            if (oe_facingDirection(oe) != dir)
                ObjectEventSetHeldMovement((void *)oe, FaceActionFor(dir));
            else
                r->settled = 1;
        }
        return;
    }

    /* Never interrupt an animation already in progress. As soon as it ends,
     * use the newest snapshot to choose the next step, not a stale queued step.
     */
    if (!RemoteReadyForMovement(oe))
        return;

    /* Prefer the direction reported by the sender where it agrees with the
     * remaining delta. If samples skipped a turn, the next snapshot will update
     * the target again; movement remains cardinal and deterministic. */
    if (dir == DIR_EAST && dx > 0)
        stepDir = DIR_EAST;
    else if (dir == DIR_WEST && dx < 0)
        stepDir = DIR_WEST;
    else if (dir == DIR_NORTH && dy < 0)
        stepDir = DIR_NORTH;
    else if (dir == DIR_SOUTH && dy > 0)
        stepDir = DIR_SOUTH;
    else if (dx != 0)
        stepDir = (dx > 0) ? DIR_EAST : DIR_WEST;
    else
        stepDir = (dy > 0) ? DIR_SOUTH : DIR_NORTH;

    stepX = oe_currentX(oe);
    stepY = oe_currentY(oe);
    if (stepDir == DIR_EAST) stepX++;
    else if (stepDir == DIR_WEST) stepX--;
    else if (stepDir == DIR_SOUTH) stepY++;
    else stepY--;

    if (!DoorGateStep(slot, stepDir, via, stepX, stepY))
        return;

    QueueRemoteStep(oe, stepDir, speed, gap > 1);
    r->settled = 0;
    r->driftRun = 0;
}
#endif

'''

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Expected one {label} anchor, found {count}.")
    return text.replace(old, new, 1)

def backup_and_write(path: Path, content: str) -> None:
    backup = Path(str(path) + ".pre-native-movement-snapshots.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8", newline="\n")

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_native_movement_snapshots.py <path-to-third_party/gen3-poke-multiplayer>",
              file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    main_path = root / "payload" / "main.c"
    if not main_path.is_file():
        print(f"error: source file not found: {main_path}", file=sys.stderr)
        return 1

    try:
        source = main_path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Native movement snapshots are already patched; no changes made.")
            return 0

        # These symbols are in the native-SIO section, immediately before the
        # receive dispatcher. The receive handler only copies four words; it
        # never calls game routines from the serial interrupt.
        state = r'''#define SIO_T_SNAPSHOT 0x05u
#define SIO_SNAPSHOT_WORDS 4u
static volatile u32 sSioSnapshotRxVersion;
static volatile u16 sSioSnapshotRxWords[SIO_SNAPSHOT_WORDS];
static u32 sSioSnapshotAppliedVersion;
static u16 sSioSnapshotActiveWords[SIO_SNAPSHOT_WORDS];
static u16 sSioSnapshotTxWords[SIO_SNAPSHOT_WORDS];
static u16 sSioSnapshotLastSampleWords[SIO_SNAPSHOT_WORDS];
static u8 sSioSnapshotHaveActive;
static u8 sSioSnapshotTxPending;
static u8 sSioSnapshotPreferSnapshot = 1u;
static u8 sSioSnapshotSampleFrames;
static u8 sSioSnapshotHaveLastSample;

/* CUBHMA_NATIVE_SNAPSHOT_RX_TX */
'''
        source = replace_once(source, "int SioDeliverFrame(u8 type, const u16 *words, u8 count)\n{", state + "\nint SioDeliverFrame(u8 type, const u16 *words, u8 count)\n{", "SIO snapshot state block")

        source = replace_once(
            source,
            '''    if (type != SIO_T_EVENT || count != (u8)(sizeof(struct NetEvent) / 2))
        return 1;
''',
            '''    if (type == SIO_T_SNAPSHOT)
    {
        if (count != SIO_SNAPSHOT_WORDS)
            return 1;

        /* Seqlock: the main loop never sees half of an IRQ-written snapshot. */
        sSioSnapshotRxVersion++;
        for (i = 0; i < SIO_SNAPSHOT_WORDS; i++)
            sSioSnapshotRxWords[i] = words[i];
        sSioSnapshotRxVersion++;
        return 1;
    }

    if (type != SIO_T_EVENT || count != (u8)(sizeof(struct NetEvent) / 2))
        return 1;
''',
            "SIO snapshot receive branch"
        )

        new_pump = r'''static void SioPumpTx(void)
{
    int eventPending = (g_mailbox.txTail != g_mailbox.txHead);

    /* Alternate compact snapshots with reliable events whenever both exist.
     * Snapshots coalesce to the newest state; reliable events keep their queue.
     */
    if (sSioSnapshotTxPending && (!eventPending || sSioSnapshotPreferSnapshot))
    {
        if (SioSendFrame(SIO_T_SNAPSHOT, sSioSnapshotTxWords, SIO_SNAPSHOT_WORDS))
        {
            sSioSnapshotTxPending = 0;
            sSioSnapshotPreferSnapshot = 0;
        }
        return;
    }

    if (eventPending)
    {
        u32 tail = g_mailbox.txTail;
        if (SioSendFrame(SIO_T_EVENT, (const u16 *)&g_mailbox.tx[tail],
                         (u8)(sizeof(struct NetEvent) / 2)))
        {
            g_mailbox.txTail = WRAP(tail, TX_SLOTS);
            sSioSnapshotPreferSnapshot = 1u;
        }
        return;
    }

    if (sSioSnapshotTxPending
        && SioSendFrame(SIO_T_SNAPSHOT, sSioSnapshotTxWords, SIO_SNAPSHOT_WORDS))
    {
        sSioSnapshotTxPending = 0;
        sSioSnapshotPreferSnapshot = 0;
    }
}'''
        source = replace_once(
            source,
            '''static void SioPumpTx(void)
{
    while (g_mailbox.txTail != g_mailbox.txHead)
    {
        u32 tail = g_mailbox.txTail;

        if (!SioSendFrame(SIO_T_EVENT, (const u16 *)&g_mailbox.tx[tail],
                          (u8)(sizeof(struct NetEvent) / 2)))
            break;

        g_mailbox.txTail = WRAP(tail, TX_SLOTS);
    }
}''',
            new_pump,
            "SIO TX scheduler"
        )

        track_old = '''    if (x != sLastPlayerX || y != sLastPlayerY)
    {
        sLastPlayerX = x;
        sLastPlayerY = y;
        EmitEvent(EVENT_STEP, dir, (u8)speed, x, y);
    }
    else if (dir != sLastPlayerDir)
    {
        /* Fermo ma girato: nessun PASSO lo racconterebbe. */
        EmitEvent(EVENT_TURN, dir, (u8)speed, x, y);
    }
    sLastPlayerDir = dir;
'''
        track_new = '''    if (x != sLastPlayerX || y != sLastPlayerY)
    {
        sLastPlayerX = x;
        sLastPlayerY = y;
#ifndef PAYLOAD_WITH_SIO
        EmitEvent(EVENT_STEP, dir, (u8)speed, x, y);
#endif
    }
    else if (dir != sLastPlayerDir)
    {
        /* Fermo ma girato: nessun PASSO lo racconterebbe. */
#ifndef PAYLOAD_WITH_SIO
        EmitEvent(EVENT_TURN, dir, (u8)speed, x, y);
#endif
    }
    sLastPlayerDir = dir;

#ifdef PAYLOAD_WITH_SIO
    SampleNativeSnapshot(x, y, dir, (u8)speed, mapKey);
#endif
'''
        source = replace_once(source, track_old, track_new, "local player movement event block")

        periodic_sync_old = '''    if (++sFramesSinceSync >= SYNC_PERIOD)
    {
        sFramesSinceSync = 0;
        EmitEvent(EVENT_SYNC, dir, (u8)speed, x, y);
    }
'''
        periodic_sync_new = '''#ifndef PAYLOAD_WITH_SIO
    /* Native SIO uses the compact latest-state snapshot for steady correction.
     * Keep the one-second periodic event only in legacy event-transport builds. */
    if (++sFramesSinceSync >= SYNC_PERIOD)
    {
        sFramesSinceSync = 0;
        EmitEvent(EVENT_SYNC, dir, (u8)speed, x, y);
    }
#endif
'''
        source = replace_once(source, periodic_sync_old, periodic_sync_new, "periodic SYNC replacement")
        source = replace_once(
            source,
            "static void TrackPlayer(u32 playerOe)\n{",
            SAMPLE_FUNCTION + "static void TrackPlayer(u32 playerOe)\n{",
            "snapshot sampler insertion"
        )
        source = replace_once(
            source,
            "static void ConsumeRemoteEvents(void)\n{",
            CONSUME_FUNCTION + "static void ConsumeRemoteEvents(void)\n{",
            "snapshot consumer insertion"
        )
        source = replace_once(
            source,
            '''    DrainMailbox();
    for (i = 0; i < N_REMOTES; i++)
        ConsumeSlotEvents(i);
}''',
            '''    DrainMailbox();
    for (i = 0; i < N_REMOTES; i++)
        ConsumeSlotEvents(i);
#ifdef PAYLOAD_WITH_SIO
    ConsumeNativeSnapshot();
#endif
}''',
            "snapshot consumer call"
        )

        # All expected edits must be present before writing the source.
        for required in (
            "SIO_T_SNAPSHOT 0x05u",
            "SampleNativeSnapshot(x, y, dir, (u8)speed, mapKey);",
            "ConsumeNativeSnapshot();",
            "sSioSnapshotPreferSnapshot",
            "QueueRemoteStep(oe, stepDir, speed, gap > 1);",
        ):
            if required not in source:
                raise ValueError(f"Patch validation failed; missing expected marker: {required}")

        backup_and_write(main_path, source)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Native movement snapshot patch applied to payload/main.c.")
    print("Both master and slave now sample local position at 20 Hz and send compact updates when state changes.")
    print("The receiver reconciles against the latest snapshot instead of accumulating predicted step events.")
    print("Reliable events remain enabled for map entry, status, and trainer-card flows.")
    print("Backup: payload/main.c.pre-native-movement-snapshots.bak")
    print("Next: rebuild native-link ROMs with tools/prepare_native_link_roms.ps1.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fix native snapshot reconciliation and permit snapshot-driven peer discovery.

This is a source-only patch. It relaxes the small-gap teleport threshold, clears
stale movement work only on a true resync, and lets a newly observed native-link
peer enter the normal avatar-spawn path even if its first reliable sync packet
was missed.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_NATIVE_SNAPSHOT_RECONCILIATION_FIX"
HARD_GAP = "#define NATIVE_SNAPSHOT_HARD_RESYNC_GAP 24u"

OLD_PEER_LOOKUP = '''    /* Native cable mode has one remote peer. Wait for its reliable entry event
     * to create the avatar; the most recent snapshot stays available meanwhile.
     */
    for (slot = 0; slot < N_REMOTES; slot++)
        if (g_remotes[slot].known && g_remotes[slot].state == STATE_SPAWNED)
            break;
    if (slot >= N_REMOTES)
        return;

    r = &g_remotes[slot];
    /* The reliable map-entry event owns map transitions. Do not let an older
     * retained snapshot move the avatar back to its previous map while the
     * matching fresh snapshot is still in flight. */
    if (r->mapKey != mapKey)
        return;
    if (!MapRemoteToLocal(r, mapKey, x, y, &lx, &ly, &via))
        return;
'''

NEW_PEER_LOOKUP = '''    /* Native direct-link mode has one peer. Prefer the slot already assigned
     * by reliable events, even if its object is currently awaiting a respawn. */
    slot = N_REMOTES;
    for (i = 0; i < N_REMOTES; i++)
    {
        if (g_remotes[i].known)
        {
            slot = i;
            break;
        }
    }

    /* Recovery path: snapshots continue arriving even if every initial reliable
     * EVENT_SYNC was missed. Claim a clean idle slot and let the normal field
     * loop create the avatar; never create sprites from the serial interrupt. */
    if (slot >= N_REMOTES)
    {
        for (i = 0; i < N_REMOTES; i++)
        {
            if (!g_remotes[i].known
                && g_remotes[i].state == STATE_IDLE
                && g_remotes[i].objectId >= OBJECT_EVENTS_COUNT)
            {
                slot = i;
                break;
            }
        }
    }
    if (slot >= N_REMOTES)
        return;

    r = &g_remotes[slot];
    if (!r->known)
    {
        r->known = 1;
        r->state = STATE_IDLE;
        r->mapKey = mapKey;
        r->targetX = x;
        r->targetY = y;
        r->gender = gender;
        r->avatarState = avatarState;
        r->status = ST_OVERWORLD;
        r->statusAge = 0;
        r->spawnCooldown = 0;
        r->forceResync = 1;
        return; /* the normal OverworldTick spawn path owns sprite creation */
    }

    /* Keep reliable map-entry transitions authoritative. The snapshot is a
     * fast movement correction, not a replacement for map/door sequencing. */
    if (r->mapKey != mapKey)
        return;
    if (!MapRemoteToLocal(r, mapKey, x, y, &lx, &ly, &via))
        return;
'''

OLD_HARD_RESYNC = '''    if (r->forceResync || gap > DRIFT_TOLERANCE)
    {
        if (gap != 0)
            TeleportRemote(oe, lx, ly);
        r->forceResync = 0;
        r->settled = 0;
        r->driftRun = 0;
        return;
    }
'''

NEW_HARD_RESYNC = '''    if (r->forceResync || gap > NATIVE_SNAPSHOT_HARD_RESYNC_GAP)
    {
        /* Only a map/entry resync or a truly enormous gap may snap the avatar.
         * Ordinary movement backlog is handled by fast cardinal steps below. */
        if (gap != 0)
            TeleportRemote(oe, lx, ly);
        r->qTail = r->qHead; /* discard obsolete commands only at true resync */
        r->forceResync = 0;
        r->settled = 0;
        r->driftRun = 0;
        return;
    }
'''

def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {count}.")
    return source.replace(old, new, 1)

def backup_and_write(path: Path, source: str) -> None:
    backup = Path(str(path) + ".pre-snapshot-reconciliation.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(source, encoding="utf-8", newline="\n")

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_native_movement_reconciliation.py <path-to-third_party/gen3-poke-multiplayer>",
              file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    main_path = root / "payload" / "main.c"
    if not main_path.is_file():
        print(f"error: required source file not found: {main_path}", file=sys.stderr)
        return 1

    try:
        source = main_path.read_text(encoding="utf-8")
        if MARKER in source:
            print("Native snapshot reconciliation fix is already applied.")
            return 0

        if "CUBHMA_NATIVE_MOVEMENT_SNAPSHOTS" not in source:
            raise ValueError("Movement snapshot patch is missing. Run patch_native_movement_snapshots.py first.")

        source = replace_once(source, OLD_PEER_LOOKUP, NEW_PEER_LOOKUP, "peer lookup/bootstrap")
        source = replace_once(source, OLD_HARD_RESYNC, NEW_HARD_RESYNC, "hard-resync threshold")

        anchor = "#ifdef PAYLOAD_NATIVE_SIO\n/* Apply the latest compact snapshot"
        source = replace_once(source, anchor, f"#ifdef PAYLOAD_NATIVE_SIO\n{HARD_GAP}\n/* Apply the latest compact snapshot", "native snapshot hard-gap definition")

        # Place the marker inside the patched function, ensuring the marker is
        # only present after every structural edit succeeded.
        source = replace_once(
            source,
            "static void ConsumeNativeSnapshot(void)\n{",
            f"static void ConsumeNativeSnapshot(void)\n{{\n    /* {MARKER} */",
            "reconciliation-fix marker"
        )

        for required in (
            MARKER,
            "gap > NATIVE_SNAPSHOT_HARD_RESYNC_GAP",
            "r->known = 1;",
            "r->qTail = r->qHead;",
            "the normal OverworldTick spawn path owns sprite creation",
        ):
            if required not in source:
                raise ValueError(f"Validation failed; expected text not found: {required}")

        backup_and_write(main_path, source)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Native movement reconciliation fix applied.")
    print("Changes: same-map correction snaps only beyond 24 tiles; smaller gaps are caught up smoothly.")
    print("Snapshots can recover peer discovery if the initial reliable sync packet is missed.")
    print("Avatar creation still runs in the normal game loop, never in the serial interrupt.")
    print("Backup: payload/main.c.pre-snapshot-reconciliation.bak")
    print("Rebuild with tools/prepare_native_link_roms.ps1 and test both role ROMs.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

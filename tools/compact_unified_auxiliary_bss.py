#!/usr/bin/env python3
"""Narrow individually audited bounded counters/flags to reclaim EWRAM.

Run from the CUBHMA-Multiplayer repository root:
  python tools/compact_unified_auxiliary_bss.py

This does not alter linker boundaries or reserved memory. It only narrows scalar
variables whose complete value ranges are constrained by source constants and
their assignments. A backup is created before changing payload/main.c.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_PATH = ROOT / "third_party" / "gen3-poke-multiplayer" / "payload" / "main.c"
MARKER = "CUBHMA_AUX_BSS_COMPACT"

# Verified constraints in main.c:
# entry/status counters are bounded by 3 and 5; heartbeat is 120; map settle
# and menu debounce timers are bounded by 60; link grace is 15. The remaining
# state values are booleans or ST_* enum values 0..7, except sRamCleanDone,
# whose state machine uses only 0, 1 and 2.
FIELDS = (
    "sHavePlayerPos",
    "sEntrySyncsLeft",
    "sEntrySyncTimer",
    "sHaveSettleKey",
    "sMapSettling",
    "sLocalStatus",
    "sStatusRepeatsLeft",
    "sStatusTimer",
    "sStatusHeartbeat",
    "sOutFieldFrames",
    "sLinkBusyLatch",
    "sLinkGrace",
    "sPassThroughWasOn",
    "sRamCleanDone",
    "sSettleTimer",
)

EXPECTED_CONSTANTS = {
    "ENTRY_SYNC_REPEATS": "3u",
    "ENTRY_SYNC_SPACING": "5u",
    "STATUS_REPEATS": "3u",
    "STATUS_SPACING": "5u",
    "STATUS_HEARTBEAT": "120u",
    "MENU_DEBOUNCE_FRAMES": "60u",
    "SETTLE_GIVEUP_FRAMES": "60u",
    "LINK_GRACE_FRAMES": "15u",
}


def main() -> int:
    if not MAIN_PATH.is_file():
        print(f"error: required source not found: {MAIN_PATH}", file=sys.stderr)
        return 1

    source = MAIN_PATH.read_text(encoding="utf-8")
    if MARKER in source:
        print("Auxiliary BSS fields are already compacted; no changes made.")
        return 0
    if "CUBHMA_REMOTE_STATE_COMPACT" not in source:
        print("error: expected Remote compaction first; no changes made.", file=sys.stderr)
        return 1

    # Fail closed if any of the audited bounding constants has changed.
    for name, value in EXPECTED_CONSTANTS.items():
        pattern = rf"(?m)^#define[ \t]+{re.escape(name)}[ \t]+{re.escape(value)}(?:[ \t].*)?$"
        if not re.search(pattern, source):
            print(f"error: expected bounded constant {name}={value}; no changes made.", file=sys.stderr)
            return 1

    changed = source
    for name in FIELDS:
        pattern = rf"(?m)^([ \t]*)static[ \t]+u32[ \t]+{re.escape(name)}[ \t]*;"
        changed, count = re.subn(
            pattern,
            lambda m: f"{m.group(1)}static u8 {name};",
            changed,
        )
        if count != 1:
            print(
                f"error: expected exactly one 'static u32 {name};' declaration; "
                f"found {count}. No changes made.",
                file=sys.stderr,
            )
            return 1

    # The status enum deliberately fits in one byte; this protects against a
    # future source change that invalidates that premise.
    for name, value in (
        ("ST_OVERWORLD", "0u"),
        ("ST_BATTLE", "1u"),
        ("ST_DIALOG", "2u"),
        ("ST_MENU", "3u"),
        ("ST_MENU_BAG", "4u"),
        ("ST_MENU_PARTY", "5u"),
        ("ST_MENU_DEX", "6u"),
        ("ST_MENU_NAV", "7u"),
    ):
        if not re.search(rf"(?m)^#define[ \t]+{name}[ \t]+{re.escape(value)}(?:[ \t].*)?$", changed):
            print(f"error: status value {name} is not the audited value {value}; no changes made.", file=sys.stderr)
            return 1

    # Marker after successful in-memory validation makes the patch idempotent.
    marker = f"/* {MARKER}: 15 bounded scalar fields narrowed after range audit. */\n"
    anchor = "#include \"game_types.h\"\n"
    if changed.count(anchor) != 1:
        print("error: include insertion anchor was not unique; no changes made.", file=sys.stderr)
        return 1
    changed = changed.replace(anchor, anchor + "\n" + marker, 1)

    backup = Path(str(MAIN_PATH) + ".pre-aux-bss-compact.bak")
    if not backup.exists():
        shutil.copy2(MAIN_PATH, backup)
    MAIN_PATH.write_text(changed, encoding="utf-8", newline="\n")

    print("Compacted 15 bounded auxiliary fields in payload/main.c.")
    print("  saved field widths: 15 x u32 -> u8 (up to 45 bytes before alignment)")
    print(f"  backup: {backup.name}")
    print("Next: run .\\tools\\prepare_unified_native_link_rom.ps1")
    print("The linker guard remains unchanged; if it still fails, do not move HANDOFF_BASE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

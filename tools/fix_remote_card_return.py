#!/usr/bin/env python3
"""Fix the remote Trainer Card return callback in the local multiplayer payload.

The remote-card path currently uses CB2_ReturnToFieldWithOpenMenu, which is the
vanilla callback used when the Trainer Card is opened FROM the pause menu. In
the multiplayer overworld interaction path, pressing A did not open the pause
menu first; therefore that callback incorrectly opened the pause menu after the
card was closed. Use CB2_ReturnToField instead.

This edits only the local payload source and symbol generator, makes backups,
and never accesses or modifies ROM files.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

GEN_MARKER = "# CUBHMA_REMOTE_CARD_RETURN_FIX"
MAIN_MARKER = "CUBHMA_REMOTE_CARD_RETURN_FIX"

GEN_OLD = '    "CB2_ReturnToFieldWithOpenMenu",'
GEN_NEW = '''    # CUBHMA_REMOTE_CARD_RETURN_FIX: card opened from the overworld returns to field, not START menu.
    "CB2_ReturnToField",
    "CB2_ReturnToFieldWithOpenMenu",'''

MAIN_OLD = """            ShowTrainerCardInLink((u8)(sCardShowSlot + 1u),
                                  (void *)(ADDR_CB2_ReturnToFieldWithOpenMenu | 1u));"""
MAIN_NEW = """            /* CUBHMA_REMOTE_CARD_RETURN_FIX: we did not open the START menu first. */
            ShowTrainerCardInLink((u8)(sCardShowSlot + 1u),
                                  (void *)(ADDR_CB2_ReturnToField | 1u));"""


def transform(text: str, marker: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if marker in text:
        if new in text:
            return text, False
        raise ValueError(f"{label} has a partial Trainer Card return fix; inspect it manually.")
    n = text.count(old)
    if n != 1:
        raise ValueError(f"Expected one {label} anchor, found {n}. No files changed.")
    return text.replace(old, new, 1), True


def backup_and_write(path: Path, content: str) -> None:
    backup = Path(str(path) + ".pre-card-return-fix.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_remote_card_return.py <path-to-third_party/gen3-poke-multiplayer>",
              file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    gen_path = root / "tools" / "gen_syms.py"
    main_path = root / "payload" / "main.c"
    for path in (gen_path, main_path):
        if not path.is_file():
            print(f"error: required source file not found: {path}", file=sys.stderr)
            return 1

    try:
        new_gen, gen_changed = transform(
            gen_path.read_text(encoding="utf-8"), GEN_MARKER,
            GEN_OLD, GEN_NEW, "tools/gen_syms.py",
        )
        new_main, main_changed = transform(
            main_path.read_text(encoding="utf-8"), MAIN_MARKER,
            MAIN_OLD, MAIN_NEW, "payload/main.c",
        )
        # Validate both edits before touching either file.
        if gen_changed:
            backup_and_write(gen_path, new_gen)
        if main_changed:
            backup_and_write(main_path, new_main)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Remote Trainer Card return fix prepared:")
    print(f"  tools/gen_syms.py: {'patched' if gen_changed else 'already patched'}")
    print(f"  payload/main.c:    {'patched' if main_changed else 'already patched'}")
    print("Backups use the suffix .pre-card-return-fix.bak.")
    print("Rebuild native-link ROMs to include this fix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

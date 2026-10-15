#!/usr/bin/env python3
"""Integrate the CUBHMA multiplayer loader into a local pret/pokeemerald checkout.

This edits only the provided source checkout and does not read or distribute a ROM.
A backup is made before changing main.c. Partial or ambiguous states are refused.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOADER_TEMPLATE = ROOT / "game-side" / "pokeemerald-multiplayer-loader.c"
BACKUP_SUFFIX = ".pre-cubhma-multiplayer.bak"
PROTOTYPE = "void InitIntrHandlers(void);"
NEW_PROTOTYPE = "void CUBHMAMultiplayerPayloadInit(void);"
LOOP_ANCHOR = "    for (;;)\n    {\n        ReadKeys();"
CALL = "    CUBHMAMultiplayerPayloadInit();\n"


def integrate(project_root: Path) -> bool:
    project_root = project_root.resolve()
    main_path = project_root / "src" / "main.c"
    loader_path = project_root / "src" / "cubhma_multiplayer_payload.c"
    backup_path = Path(str(main_path) + BACKUP_SUFFIX)

    if not (project_root / "Makefile").is_file() or not main_path.is_file():
        raise ValueError(f"{project_root} does not look like a pret/pokeemerald checkout.")
    if not LOADER_TEMPLATE.is_file():
        raise FileNotFoundError(f"Loader template missing: {LOADER_TEMPLATE}")

    main_text = main_path.read_text(encoding="utf-8")
    loader_text = LOADER_TEMPLATE.read_text(encoding="utf-8")
    prototype_present = NEW_PROTOTYPE in main_text
    call_present = CALL.strip() in main_text
    loader_present = loader_path.is_file()

    if prototype_present and call_present and loader_present:
        if loader_path.read_text(encoding="utf-8") != loader_text:
            raise ValueError(f"{loader_path} differs from the CUBHMA template; no files changed.")
        print("Already integrated; no changes made.")
        return False

    if prototype_present or call_present or loader_present:
        raise ValueError("Partial/custom integration detected; inspect the relevant source files manually.")
    if backup_path.exists():
        raise ValueError(f"Backup already exists: {backup_path}; refusing to overwrite it.")
    if main_text.count(PROTOTYPE) != 1:
        raise ValueError("Expected exactly one InitIntrHandlers prototype in src/main.c.")
    if main_text.count(LOOP_ANCHOR) != 1:
        raise ValueError("Expected exactly one AgbMain main-loop anchor in src/main.c.")

    patched = main_text.replace(PROTOTYPE, PROTOTYPE + "\n" + NEW_PROTOTYPE, 1)
    patched = patched.replace(LOOP_ANCHOR, CALL + LOOP_ANCHOR, 1)

    shutil.copy2(main_path, backup_path)
    try:
        main_path.write_text(patched, encoding="utf-8", newline="\n")
        loader_path.write_text(loader_text, encoding="utf-8", newline="\n")
    except Exception:
        shutil.copy2(backup_path, main_path)
        if loader_path.exists() and loader_path.read_text(encoding="utf-8") == loader_text:
            loader_path.unlink()
        raise

    print(f"Integrated loader into: {project_root}")
    print(f"Original main.c backup: {backup_path}")
    print(f"Added loader source: {loader_path}")
    print("Rebuild with your own clean baserom.gba before generating payload symbols.")
    return True


def revert(project_root: Path) -> None:
    project_root = project_root.resolve()
    main_path = project_root / "src" / "main.c"
    loader_path = project_root / "src" / "cubhma_multiplayer_payload.c"
    backup_path = Path(str(main_path) + BACKUP_SUFFIX)

    if not backup_path.is_file() or not loader_path.is_file():
        raise FileNotFoundError("Expected integration backup and loader source; refusing a partial revert.")
    loader_text = LOADER_TEMPLATE.read_text(encoding="utf-8")
    if loader_path.read_text(encoding="utf-8") != loader_text:
        raise ValueError(f"{loader_path} differs from the template; refusing to remove it.")
    main_text = main_path.read_text(encoding="utf-8")
    if main_text.count(NEW_PROTOTYPE) != 1 or main_text.count(CALL.strip()) != 1:
        raise ValueError("src/main.c no longer matches the expected integration; refusing to change it.")

    reverted = main_text.replace(PROTOTYPE + "\n" + NEW_PROTOTYPE, PROTOTYPE, 1)
    reverted = reverted.replace(CALL + LOOP_ANCHOR, LOOP_ANCHOR, 1)
    main_path.write_text(reverted, encoding="utf-8", newline="\n")
    loader_path.unlink()
    backup_path.unlink()
    print(f"Removed CUBHMA multiplayer integration from: {project_root}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pokeemerald", required=True, type=Path, help="Path to a local pret/pokeemerald checkout.")
    parser.add_argument("--revert", action="store_true", help="Remove our two insertions and delete the backup.")
    args = parser.parse_args()
    try:
        revert(args.pokeemerald) if args.revert else integrate(args.pokeemerald)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

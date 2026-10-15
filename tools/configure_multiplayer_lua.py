#!/usr/bin/env python3
"""Configure generated mGBA scripts to validate this modified Emerald build.

The upstream injector's stock-ROM fingerprint assumes the retail CB2_Overworld
address and first instruction. CUBHMA's locally rebuilt ROM may move that
symbol, so derive both the address and its validation word from the exact
pokeemerald.map and pokeemerald.gba used to package the multiplayer patch.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

ROM_BASE = 0x08000000
GAME_CODE = b"BPEE"
CB2_SYMBOL = "CB2_Overworld"
MAP_SYMBOL_RE = re.compile(
    r"(?im)^\s*0x([0-9a-f]{8})\s+" + re.escape(CB2_SYMBOL) + r"\s*$"
)
LUA_OVERRIDE_RE = re.compile(
    r"(?m)^ROM_CB2_(?:OVERWORLD|WORD)\s*=.*(?:\r?\n|$)"
)


def resolve_cb2_fingerprint(rom: bytes, map_text: str) -> tuple[int, int]:
    """Return (CB2_Overworld ROM address, first 32-bit word at that address)."""
    if len(rom) < 0xB0:
        raise ValueError("Built ROM is too small to contain a GBA ROM header.")
    if rom[0xAC:0xB0] != GAME_CODE:
        raise ValueError(
            "Built ROM must be English Pokémon Emerald (BPEE); "
            f"found {rom[0xAC:0xB0]!r}."
        )

    addresses = {int(match, 16) for match in MAP_SYMBOL_RE.findall(map_text)}
    if len(addresses) != 1:
        raise ValueError(
            f"Expected one unique {CB2_SYMBOL} address in the modified map; "
            f"found {len(addresses)}."
        )

    address = addresses.pop()
    offset = address - ROM_BASE
    if offset < 0 or offset + 4 > len(rom):
        raise ValueError(
            f"{CB2_SYMBOL} address 0x{address:08X} is outside the built ROM."
        )

    word = struct.unpack_from("<I", rom, offset)[0]
    if word in (0x00000000, 0xFFFFFFFF):
        raise ValueError(
            f"Unexpected {CB2_SYMBOL} signature 0x{word:08X} at "
            f"0x{address:08X}; the map and ROM may not belong to the same build."
        )
    return address, word


def configure_script(path: Path, address: int, word: int) -> None:
    """Add or replace the build-specific ROM fingerprint in a generated Lua script."""
    text = path.read_text(encoding="utf-8-sig")
    text = LUA_OVERRIDE_RE.sub("", text)
    header = (
        "-- CUBHMA build-specific ROM fingerprint; generated automatically.\n"
        f"ROM_CB2_OVERWORLD = 0x{address:08X}\n"
        f"ROM_CB2_WORD = 0x{word:08X}\n"
    )
    path.write_text(header + text, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path,
                        help="Modified local pokeemerald.gba used to build the patch.")
    parser.add_argument("--map", required=True, type=Path,
                        help="Matching modified pokeemerald.map.")
    parser.add_argument("--script", required=True, action="append", type=Path,
                        help="Generated inject.pN.lua file; may be provided more than once.")
    args = parser.parse_args()

    try:
        rom = args.rom.read_bytes()
        map_text = args.map.read_text(encoding="utf-8", errors="replace")
        address, word = resolve_cb2_fingerprint(rom, map_text)
        for script in args.script:
            configure_script(script, address, word)
            print(f"Configured {script}: CB2_Overworld=0x{address:08X}, "
                  f"signature=0x{word:08X}")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

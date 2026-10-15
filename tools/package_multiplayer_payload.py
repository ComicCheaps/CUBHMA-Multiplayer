#!/usr/bin/env python3
"""Embed a built multiplayer payload in a local pokeemerald ROM.

This changes only a user's local build output. It never downloads, commits, or
distributes a ROM. The result can be converted to BPS against the clean original.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

ROM_BASE = 0x08000000
ROM_END = 0x0A000000
GAME_CODE = b"BPEE"
PAYLOAD_BASE = 0x0203CF80
MAX_CLEAR_SIZE = 0x2E80
HOOK_MAGIC = 0x4B4F4F48
ADDRESS_MARKER = 0xC0B4A001
FILE_SIZE_MARKER = 0xC0B4A002
CLEAR_SIZE_MARKER = 0xC0B4A003
DESCRIPTOR_MARKERS = struct.pack("<III", ADDRESS_MARKER, FILE_SIZE_MARKER, CLEAR_SIZE_MARKER)


def parse_payload_end(map_text: str) -> int:
    matches = re.findall(r"(?im)^\s*(0x[0-9a-f]{6,16})\s+payload_end\b", map_text)
    addresses = {int(value, 16) for value in matches}
    if len(addresses) != 1:
        raise ValueError("Could not identify a unique payload_end address in payload.map.")
    return addresses.pop()


def calc_header_checksum(rom: bytearray) -> None:
    if len(rom) < 0xBE:
        raise ValueError("Target is too small to contain a GBA ROM header.")
    rom[0xBD] = (-(sum(rom[0xA0:0xBD]) + 0x19)) & 0xFF


def package_payload(target_rom: bytes, payload: bytes, map_text: str, output_size: int = ROM_END - ROM_BASE) -> bytes:
    if len(target_rom) < 0xC0:
        raise ValueError("Built target is too small to be a GBA ROM.")
    if target_rom[0xAC:0xB0] != GAME_CODE:
        raise ValueError("Built target ROM must have the BPEE game code.")
    if len(payload) < 12:
        raise ValueError("Payload is too small to contain the hook header.")
    if struct.unpack_from("<I", payload, 8)[0] != HOOK_MAGIC:
        raise ValueError("payload.bin is missing the expected HOOK header.")

    payload_end = parse_payload_end(map_text)
    clear_size = payload_end - PAYLOAD_BASE
    if clear_size < len(payload):
        raise ValueError(
            f"Linked payload region ({clear_size:,} bytes) is smaller than payload.bin "
            f"({len(payload):,} bytes); use matching build files."
        )
    if clear_size > MAX_CLEAR_SIZE:
        raise ValueError(f"Linked payload region is too large ({clear_size:,} bytes; limit {MAX_CLEAR_SIZE:,}).")

    locations = []
    start = 0
    while True:
        offset = target_rom.find(DESCRIPTOR_MARKERS, start)
        if offset < 0:
            break
        locations.append(offset)
        start = offset + 1
    if len(locations) != 1:
        raise ValueError(
            f"Expected exactly one CUBHMA payload descriptor; found {len(locations)}. "
            "Integrate the loader and rebuild the target ROM first."
        )

    rom_window_size = ROM_END - ROM_BASE
    payload_offset = (len(target_rom) + 3) & ~3
    if payload_offset + len(payload) > rom_window_size:
        raise ValueError("Payload would exceed the GBA's 32 MiB Game Pak ROM window.")
    rom_address = ROM_BASE + payload_offset
    if rom_address + len(payload) > ROM_END:
        raise ValueError("Payload address falls outside the supported Game Pak ROM window.")
    if output_size < payload_offset + len(payload) or output_size > rom_window_size:
        raise ValueError(
            f"Output ROM size must fit the payload and stay within the 32 MiB Game Pak window; got {output_size:,} bytes."
        )

    output = bytearray(target_rom)
    output.extend(b"\xFF" * (payload_offset - len(output)))
    output.extend(payload)
    output.extend(b"\xFF" * (output_size - len(output)))
    struct.pack_into("<III", output, locations[0], rom_address, len(payload), clear_size)
    calc_header_checksum(output)

    if output[payload_offset:payload_offset + len(payload)] != payload:
        raise ValueError("Internal validation failed: embedded payload differs from payload.bin.")
    if struct.unpack_from("<III", output, locations[0]) != (rom_address, len(payload), clear_size):
        raise ValueError("Internal validation failed: payload descriptor was not written correctly.")
    return bytes(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("built_rom", type=Path, help="Locally built modified pokeemerald.gba.")
    parser.add_argument("payload_bin", type=Path, help="Matching payload.bin.")
    parser.add_argument("payload_map", type=Path, help="Matching payload.map.")
    parser.add_argument("output_rom", type=Path, help="Different output path for the embedded-payload ROM.")
    args = parser.parse_args()
    built_path, payload_path, map_path, output_path = (
        args.built_rom.resolve(), args.payload_bin.resolve(), args.payload_map.resolve(), args.output_rom.resolve()
    )
    if output_path in (built_path, payload_path, map_path):
        print("error: output path must differ from all inputs.", file=sys.stderr)
        return 1
    try:
        target = built_path.read_bytes()
        payload = payload_path.read_bytes()
        map_text = map_path.read_text(encoding="utf-8", errors="replace")
        embedded = package_payload(target, payload, map_text)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(embedded)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Embedded {len(payload):,} bytes at ROM address 0x{ROM_BASE + ((len(target) + 3) & ~3):08X}.")
    print(f"Reserved EWRAM clear length: {parse_payload_end(map_text) - PAYLOAD_BASE:,} bytes.")
    print(f"Wrote local output: {output_path}")
    print("Next: generate a BPS patch against your clean English Emerald v1.0 ROM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

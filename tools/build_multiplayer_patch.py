#!/usr/bin/env python3
"""Build a local BPS patch from clean English Pokémon Emerald v1.0 to a modified build.

No ROM is downloaded, embedded, or uploaded. Both ROM paths are supplied locally.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import struct
import sys
import zlib
from pathlib import Path

CLEAN_SIZE = 0x1000000
GAME_CODE = b"BPEE"
CLEAN_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
MAX_TARGET_SIZE = 1 << 28
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "src/HexManiac.Core/ViewModels/QuickEditItems/multiplayer_emerald.bps.gz"
)


def encode_number(value: int) -> bytes:
    if value < 0:
        raise ValueError("BPS integers cannot be negative.")
    result = bytearray()
    while True:
        digit = value & 0x7F
        value >>= 7
        if value == 0:
            result.append(digit | 0x80)
            return bytes(result)
        result.append(digit)
        value -= 1


def decode_number(data: bytes, position: int, end: int) -> tuple[int, int]:
    value, shift = 0, 1
    while True:
        if position >= end:
            raise ValueError("Truncated BPS integer.")
        byte = data[position]
        position += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, position
        shift <<= 7
        if shift > (1 << 56):
            raise ValueError("Invalid oversized BPS integer.")
        value += shift


def apply_bps_patch(patch: bytes, source: bytes) -> bytes:
    """Small independent BPS1 reader used to verify patches before packaging."""
    if len(patch) < 16 or patch[:4] != b"BPS1":
        raise ValueError("Not a valid BPS1 patch.")
    footer = len(patch) - 12
    if (zlib.crc32(patch[:-4]) & 0xFFFFFFFF) != struct.unpack_from("<I", patch, len(patch) - 4)[0]:
        raise ValueError("BPS patch checksum does not match.")

    source_size, pos = decode_number(patch, 4, footer)
    target_size, pos = decode_number(patch, pos, footer)
    metadata_size, pos = decode_number(patch, pos, footer)
    if metadata_size > footer - pos:
        raise ValueError("BPS metadata is truncated.")
    pos += metadata_size
    if target_size > MAX_TARGET_SIZE:
        raise ValueError("BPS target size is above the supported limit.")
    if len(source) != source_size:
        raise ValueError("Source size does not match the patch.")
    if (zlib.crc32(source) & 0xFFFFFFFF) != struct.unpack_from("<I", patch, footer)[0]:
        raise ValueError("Source checksum does not match the patch.")

    target = bytearray()
    source_relative = target_relative = 0
    while pos < footer:
        action, pos = decode_number(patch, pos, footer)
        command, length = action & 3, (action >> 2) + 1
        if len(target) + length > target_size:
            raise ValueError("BPS action writes past the target.")
        if command == 0:  # SourceRead
            end = len(target) + length
            if end > len(source):
                raise ValueError("SourceRead goes past the source.")
            target.extend(source[len(target):end])
        elif command == 1:  # TargetRead
            if pos + length > footer:
                raise ValueError("TargetRead is truncated.")
            target.extend(patch[pos:pos + length])
            pos += length
        elif command == 2:  # SourceCopy
            delta, pos = decode_number(patch, pos, footer)
            source_relative += -(delta >> 1) if delta & 1 else (delta >> 1)
            end = source_relative + length
            if source_relative < 0 or end > len(source):
                raise ValueError("SourceCopy goes outside the source.")
            target.extend(source[source_relative:end])
            source_relative = end
        else:  # TargetCopy supports overlapping byte runs.
            delta, pos = decode_number(patch, pos, footer)
            target_relative += -(delta >> 1) if delta & 1 else (delta >> 1)
            if target_relative < 0 or target_relative >= len(target):
                raise ValueError("TargetCopy references unwritten data.")
            for offset in range(length):
                index = target_relative + offset
                if index >= len(target):
                    raise ValueError("TargetCopy references unwritten data.")
                target.append(target[index])
            target_relative += length

    if len(target) != target_size:
        raise ValueError("BPS actions did not fill the target.")
    if (zlib.crc32(target) & 0xFFFFFFFF) != struct.unpack_from("<I", patch, footer + 4)[0]:
        raise ValueError("Rebuilt target checksum does not match.")
    return bytes(target)


def build_bps_patch(source: bytes, target: bytes) -> bytes:
    """Create a valid patch using SourceRead for equal runs and TargetRead for changes."""
    if len(target) > MAX_TARGET_SIZE:
        raise ValueError(f"Target exceeds {MAX_TARGET_SIZE:,} bytes.")
    patch = bytearray(b"BPS1")
    patch += encode_number(len(source))
    patch += encode_number(len(target))
    patch += encode_number(0)  # No metadata.

    pos = 0
    while pos < len(target):
        start = pos
        same = pos < len(source) and source[pos] == target[pos]
        pos += 1
        while pos < len(target):
            equal = pos < len(source) and source[pos] == target[pos]
            if equal != same:
                break
            pos += 1
        length = pos - start
        command = 0 if same else 1
        patch += encode_number(((length - 1) << 2) | command)
        if command == 1:
            patch += target[start:pos]

    patch += struct.pack("<I", zlib.crc32(source) & 0xFFFFFFFF)
    patch += struct.pack("<I", zlib.crc32(target) & 0xFFFFFFFF)
    patch += struct.pack("<I", zlib.crc32(patch) & 0xFFFFFFFF)
    result = bytes(patch)
    if apply_bps_patch(result, source) != target:
        raise ValueError("Internal BPS round-trip validation failed.")
    return result


def validate_clean_emerald(source: bytes) -> None:
    if len(source) != CLEAN_SIZE:
        raise ValueError(f"Expected 16 MiB clean Emerald; got {len(source):,} bytes.")
    if source[0xAC:0xB0] != GAME_CODE:
        raise ValueError("Source game code must be BPEE (English Pokémon Emerald).")
    digest = hashlib.sha1(source).hexdigest()
    if digest != CLEAN_SHA1:
        raise ValueError(
            "Source is not clean Pokémon Emerald (USA/Europe) v1.0. "
            f"SHA-1 found {digest}; expected {CLEAN_SHA1}."
        )


def build_from_files(source_path: Path, target_path: Path, output_path: Path) -> bytes:
    source_path, target_path, output_path = (
        source_path.resolve(), target_path.resolve(), output_path.resolve()
    )
    if output_path in (source_path, target_path):
        raise ValueError("Output path must not overwrite either ROM input.")
    if not source_path.is_file():
        raise ValueError(f"Source ROM not found: {source_path}")
    if not target_path.is_file():
        raise ValueError(f"Built ROM not found: {target_path}")

    source, target = source_path.read_bytes(), target_path.read_bytes()
    validate_clean_emerald(source)
    if len(target) < 0xB0 or target[0xAC:0xB0] != GAME_CODE:
        raise ValueError("Built target ROM must retain the BPEE game code.")
    if source == target:
        raise ValueError("Built target is identical to vanilla Emerald; no changes to package.")

    patch = build_bps_patch(source, target)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(gzip.compress(patch, compresslevel=9, mtime=0))
    return patch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a validated BPS patch from clean English Emerald v1.0 to a local modified build."
    )
    parser.add_argument("source_rom", type=Path, help="Your clean Emerald v1.0 ROM.")
    parser.add_argument("built_rom", type=Path, help="The locally compiled modified ROM.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output .bps.gz resource path.")
    args = parser.parse_args(argv)
    try:
        patch = build_from_files(args.source_rom, args.built_rom, args.output)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.output.resolve()} ({args.output.resolve().stat().st_size:,} compressed bytes)")
    print(f"BPS patch is {len(patch):,} bytes; round-trip validation passed.")
    print("Source ROM fingerprint verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

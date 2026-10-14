import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_multiplayer_payload import (  # noqa: E402
    DESCRIPTOR_MARKERS,
    HOOK_MAGIC,
    PAYLOAD_BASE,
    package_payload,
    parse_payload_end,
)


def fake_rom(size=0x4000):
    rom = bytearray(b"\xFF" * size)
    rom[0xAC:0xB0] = b"BPEE"
    rom[0x1000:0x1000 + len(DESCRIPTOR_MARKERS)] = DESCRIPTOR_MARKERS
    return bytes(rom)


def fake_payload(size=32):
    payload = bytearray(b"\xA5" * size)
    struct.pack_into("<I", payload, 8, HOOK_MAGIC)
    return bytes(payload)


class PackagePayloadTests(unittest.TestCase):
    def test_parse_payload_end_from_linker_map(self):
        text = " .bss 0x0203D000 0x80\n 0x0203D080 payload_end = .\n"
        self.assertEqual(0x0203D080, parse_payload_end(text))

    def test_embeds_payload_and_patches_descriptor(self):
        source = fake_rom()
        payload = fake_payload()
        result = package_payload(source, payload, "0x0203D080 payload_end = .\n")
        payload_offset = (len(source) + 3) & ~3
        address, size, clear_size = struct.unpack_from("<III", result, 0x1000)
        self.assertEqual(0x08000000 + payload_offset, address)
        self.assertEqual(len(payload), size)
        self.assertEqual(0x0203D080 - PAYLOAD_BASE, clear_size)
        self.assertEqual(payload, result[payload_offset:payload_offset + len(payload)])
        expected = (-(sum(result[0xA0:0xBD]) + 0x19)) & 0xFF
        self.assertEqual(expected, result[0xBD])

    def test_rejects_target_without_descriptor(self):
        rom = bytearray(fake_rom())
        rom[0x1000:0x1000 + len(DESCRIPTOR_MARKERS)] = bytes(len(DESCRIPTOR_MARKERS))
        with self.assertRaisesRegex(ValueError, "descriptor"):
            package_payload(bytes(rom), fake_payload(), "0x0203D080 payload_end = .")

    def test_rejects_duplicate_descriptors(self):
        rom = bytearray(fake_rom())
        rom[0x2000:0x2000 + len(DESCRIPTOR_MARKERS)] = DESCRIPTOR_MARKERS
        with self.assertRaisesRegex(ValueError, "found 2"):
            package_payload(bytes(rom), fake_payload(), "0x0203D080 payload_end = .")

    def test_rejects_wrong_game_code(self):
        rom = bytearray(fake_rom())
        rom[0xAC:0xB0] = b"BPRE"
        with self.assertRaisesRegex(ValueError, "BPEE"):
            package_payload(bytes(rom), fake_payload(), "0x0203D080 payload_end = .")

    def test_rejects_wrong_payload_header(self):
        payload = bytearray(fake_payload())
        payload[8:12] = b"NOPE"
        with self.assertRaisesRegex(ValueError, "HOOK"):
            package_payload(fake_rom(), bytes(payload), "0x0203D080 payload_end = .")

    def test_rejects_payload_region_too_small(self):
        with self.assertRaisesRegex(ValueError, "smaller than payload"):
            package_payload(fake_rom(), fake_payload(300), "0x0203D080 payload_end = .")

    def test_rejects_payload_region_too_large(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            package_payload(fake_rom(), fake_payload(), "0x02040000 payload_end = .")

    def test_rejects_ambiguous_payload_end(self):
        with self.assertRaisesRegex(ValueError, "unique payload_end"):
            parse_payload_end("0x0203D080 payload_end = .\n0x0203D090 payload_end = .\n")


if __name__ == "__main__":
    unittest.main()

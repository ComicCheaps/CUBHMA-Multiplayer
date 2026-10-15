import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_multiplayer_patch import (  # noqa: E402
    apply_bps_patch,
    build_bps_patch,
    decode_number,
    encode_number,
)


class BpsBuilderTests(unittest.TestCase):
    def test_varints_round_trip(self):
        for value in (0, 1, 2, 127, 128, 129, 255, 16383, 16384, 0xFFFFFFFF):
            with self.subTest(value=value):
                encoded = encode_number(value)
                decoded, next_pos = decode_number(encoded, 0, len(encoded))
                self.assertEqual(value, decoded)
                self.assertEqual(len(encoded), next_pos)

    def test_sparse_changes_round_trip(self):
        source = bytes(range(256)) * 8
        target = bytearray(source)
        target[17:21] = b"PLAY"
        target[400:419] = b"multiplayer-feature"
        target[-3:] = b"END"
        target = bytes(target)
        patch = build_bps_patch(source, target)
        self.assertEqual(b"BPS1", patch[:4])
        self.assertEqual(target, apply_bps_patch(patch, source))
        self.assertLess(len(patch), len(target))

    def test_target_can_be_longer_or_shorter(self):
        for source, target in (
            (b"emerald", b"emerald-plus-local-multiplayer"),
            (b"the original rom contents", b"the rom"),
            (b"", b"new target"),
            (b"unchanged", b"unchanged"),
        ):
            with self.subTest(source=source, target=target):
                self.assertEqual(target, apply_bps_patch(build_bps_patch(source, target), source))

    def test_wrong_source_checksum_is_rejected(self):
        patch = build_bps_patch(b"source", b"target")
        with self.assertRaisesRegex(ValueError, "checksum"):
            apply_bps_patch(patch, b"Source")

    def test_corrupted_patch_is_rejected(self):
        patch = bytearray(build_bps_patch(b"source", b"target"))
        patch[4] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            apply_bps_patch(bytes(patch), b"source")

    def test_bad_magic_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "BPS1"):
            apply_bps_patch(b"NOPE" + bytes(20), b"source")


if __name__ == "__main__":
    unittest.main()

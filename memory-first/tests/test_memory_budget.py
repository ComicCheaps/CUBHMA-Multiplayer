"""Tests for the memory-first compile-time budget contract.

These tests need only the Python standard library. They validate the constants,
not a payload binary; the linker-map and worst-case-stack check is a separate
mandatory gate before the runtime is embedded or released.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "include" / "mf_memory_budget.h"


def define_value(name: str) -> int:
    source = HEADER.read_text(encoding="utf-8")
    pattern = rf"^#define\s+{re.escape(name)}\s+(0x[0-9A-Fa-f]+|[0-9]+)[uUlL]*\s*$"
    match = re.search(pattern, source, flags=re.MULTILINE)
    if not match:
        raise AssertionError(f"Missing or unsupported numeric define: {name}")
    return int(match.group(1), 0)


class MemoryBudgetContractTests(unittest.TestCase):
    def test_address_window_matches_documented_size(self):
        base = define_value("MF_EWRAM_PAYLOAD_BASE_ADDRESS")
        end = define_value("MF_EWRAM_PAYLOAD_END_ADDRESS")
        window = define_value("MF_EWRAM_WINDOW_BYTES")
        self.assertEqual(end - base, window)
        self.assertEqual(window, 0x3080)

    def test_runtime_budget_preserves_guard(self):
        window = define_value("MF_EWRAM_WINDOW_BYTES")
        guard = define_value("MF_EWRAM_SAFETY_GUARD_BYTES")
        runtime_budget = define_value("MF_EWRAM_RUNTIME_BUDGET_BYTES")
        self.assertGreaterEqual(guard, 0x200)
        self.assertEqual(window - guard, runtime_budget)
        self.assertEqual(runtime_budget, 0x2E80)

    def test_first_milestone_has_one_remote_peer(self):
        self.assertEqual(define_value("MF_MAX_REMOTE_PLAYERS"), 1)


if __name__ == "__main__":
    unittest.main()

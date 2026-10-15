"""Tests for the memory-first EWRAM layout contract.

These tests validate constants only. They do not inspect a compiled payload;
linker-map and worst-case stack checks remain mandatory before embedding.
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
    def test_total_window_and_static_region_match_addresses(self):
        base = define_value("MF_EWRAM_PAYLOAD_BASE_ADDRESS")
        handoff = define_value("MF_EWRAM_HANDOFF_BASE_ADDRESS")
        end = define_value("MF_EWRAM_WINDOW_END_ADDRESS")
        self.assertEqual(end - base, define_value("MF_EWRAM_WINDOW_BYTES"))
        self.assertEqual(handoff - base, define_value("MF_EWRAM_STATIC_REGION_BYTES"))
        self.assertEqual(end - handoff, define_value("MF_EWRAM_HANDOFF_REGION_BYTES"))
        self.assertEqual(end - base, 0x3080)
        self.assertEqual(handoff - base, 0x2E80)

    def test_handoff_subregions_fit_and_keep_gap_before_stack(self):
        handoff = define_value("MF_EWRAM_HANDOFF_REGION_BYTES")
        lateclear = define_value("MF_EWRAM_LATECLEAR_MAX_BYTES")
        guard = define_value("MF_EWRAM_HANDOFF_GUARD_BYTES")
        stack = define_value("MF_EWRAM_PRIVATE_IRQ_STACK_BYTES")
        self.assertEqual(lateclear + guard + stack, handoff)
        self.assertEqual(lateclear, 0xC0)
        self.assertEqual(guard, 0x20)
        self.assertEqual(stack, 0x120)

    def test_static_irq_stack_limit_is_at_most_half_stack(self):
        stack = define_value("MF_EWRAM_PRIVATE_IRQ_STACK_BYTES")
        limit = define_value("MF_EWRAM_IRQ_STACK_USAGE_LIMIT")
        self.assertLessEqual(limit * 2, stack)
        self.assertEqual(limit, 0x90)

    def test_first_milestone_has_one_remote_peer(self):
        self.assertEqual(define_value("MF_MAX_REMOTE_PLAYERS"), 1)


if __name__ == "__main__":
    unittest.main()

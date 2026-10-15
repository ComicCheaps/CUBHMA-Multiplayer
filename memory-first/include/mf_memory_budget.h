#ifndef CUBHMA_MEMORY_FIRST_BUDGET_H
#define CUBHMA_MEMORY_FIRST_BUDGET_H

/*
 * Initial memory contract for the pinned retail-USA Emerald profile.
 *
 * This is a deliberately stricter target than the measured upstream baseline.
 * The baseline had 0xD8 bytes of .lateclear and only 8 bytes before the stack;
 * this target caps .lateclear at 0xC0 and preserves a 0x20-byte gap.
 * The linker map and compiler stack reports must verify every build.
 */
#define MF_EWRAM_PAYLOAD_BASE_ADDRESS       0x0203CF80u
#define MF_EWRAM_HANDOFF_BASE_ADDRESS       0x0203FE00u
#define MF_EWRAM_WINDOW_END_ADDRESS         0x02040000u

#define MF_EWRAM_WINDOW_BYTES               0x00003080u
#define MF_EWRAM_STATIC_REGION_BYTES        0x00002E80u
#define MF_EWRAM_HANDOFF_REGION_BYTES       0x00000200u
#define MF_EWRAM_LATECLEAR_MAX_BYTES        0x000000C0u
#define MF_EWRAM_HANDOFF_GUARD_BYTES        0x00000020u
#define MF_EWRAM_PRIVATE_IRQ_STACK_BYTES    0x00000120u
#define MF_EWRAM_IRQ_STACK_USAGE_LIMIT      0x00000090u

/* Two total players: at most one remote-player state in this milestone. */
#define MF_MAX_REMOTE_PLAYERS               1u

#if (MF_EWRAM_WINDOW_END_ADDRESS <= MF_EWRAM_PAYLOAD_BASE_ADDRESS)
#error "Invalid memory-first EWRAM address range."
#endif

#if ((MF_EWRAM_WINDOW_END_ADDRESS - MF_EWRAM_PAYLOAD_BASE_ADDRESS) != MF_EWRAM_WINDOW_BYTES)
#error "EWRAM window size no longer matches its address range."
#endif

#if ((MF_EWRAM_HANDOFF_BASE_ADDRESS - MF_EWRAM_PAYLOAD_BASE_ADDRESS) != MF_EWRAM_STATIC_REGION_BYTES)
#error "Static payload region size no longer matches the handoff boundary."
#endif

#if ((MF_EWRAM_WINDOW_END_ADDRESS - MF_EWRAM_HANDOFF_BASE_ADDRESS) != MF_EWRAM_HANDOFF_REGION_BYTES)
#error "Handoff region size no longer matches its address range."
#endif

#if ((MF_EWRAM_LATECLEAR_MAX_BYTES + MF_EWRAM_HANDOFF_GUARD_BYTES + MF_EWRAM_PRIVATE_IRQ_STACK_BYTES) != MF_EWRAM_HANDOFF_REGION_BYTES)
#error "Lateclear, guard and private stack must fit in the handoff region."
#endif

#if ((MF_EWRAM_IRQ_STACK_USAGE_LIMIT * 2u) > MF_EWRAM_PRIVATE_IRQ_STACK_BYTES)
#error "The static worst-case IRQ stack limit must stay within half the allocation."
#endif

#if (MF_MAX_REMOTE_PLAYERS != 1u)
#error "The memory-first milestone is deliberately two-player only."
#endif

#endif /* CUBHMA_MEMORY_FIRST_BUDGET_H */

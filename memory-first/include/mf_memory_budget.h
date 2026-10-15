#ifndef CUBHMA_MEMORY_FIRST_BUDGET_H
#define CUBHMA_MEMORY_FIRST_BUDGET_H

/*
 * Initial budget contract for the retail-USA Emerald profile.
 *
 * This is a guardrail, not a claim that the runtime has already been measured.
 * The final gate must count loaded image + initialized data + BSS + worst-case
 * stack using the actual linker map and stack analysis.
 */
#define MF_EWRAM_PAYLOAD_BASE_ADDRESS 0x0203CF80u
#define MF_EWRAM_PAYLOAD_END_ADDRESS  0x02040000u
#define MF_EWRAM_WINDOW_BYTES         0x00003080u
#define MF_EWRAM_SAFETY_GUARD_BYTES   0x00000200u
#define MF_EWRAM_RUNTIME_BUDGET_BYTES 0x00002E80u

/* Two total players means only one remote-player state is required locally. */
#define MF_MAX_REMOTE_PLAYERS         1u

#if (MF_EWRAM_PAYLOAD_END_ADDRESS <= MF_EWRAM_PAYLOAD_BASE_ADDRESS)
#error "Invalid memory-first EWRAM address range."
#endif

#if ((MF_EWRAM_PAYLOAD_END_ADDRESS - MF_EWRAM_PAYLOAD_BASE_ADDRESS) != MF_EWRAM_WINDOW_BYTES)
#error "EWRAM window size no longer matches its address range."
#endif

#if ((MF_EWRAM_WINDOW_BYTES - MF_EWRAM_SAFETY_GUARD_BYTES) != MF_EWRAM_RUNTIME_BUDGET_BYTES)
#error "Runtime budget must leave the full EWRAM safety guard unused."
#endif

#if (MF_EWRAM_SAFETY_GUARD_BYTES < 0x200u)
#error "Do not reduce the minimum 512-byte EWRAM safety guard."
#endif

#if (MF_MAX_REMOTE_PLAYERS != 1u)
#error "The memory-first milestone is deliberately two-player only."
#endif

#endif /* CUBHMA_MEMORY_FIRST_BUDGET_H */

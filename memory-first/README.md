# Memory-first implementation area

This folder is the new implementation lane for the two-player runtime contract. It intentionally does not include a copied or modified version of the third-party payload.

Rules for new runtime code:

- Start with one remote player.
- No heap allocation in runtime code.
- All buffers have compile-time capacities.
- Any new per-peer field or buffer must have a size rationale and test.
- Keep transport code separate from remote overworld object management.
- Keep the payload, initialized data, BSS and worst-case stack within the contract in `include/mf_memory_budget.h`.
- Do not embed or ship ROM images.
- Do not reintroduce the experimental four-player source-rewriting scripts into this path.

The first source file is the budget header, not a pretend multiplayer implementation. The linker-map measurement and a validated ROM startup hook are required before this folder can claim a working runtime.

See [the rebuild plan](../docs/memory-first-rebuild.md).

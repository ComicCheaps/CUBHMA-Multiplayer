# Memory-first multiplayer rebuild

## Status

This branch is a clean development lane for replacing the experimental unified four-player implementation. The initial commit establishes the architecture and a machine-checkable memory contract; it does **not** claim that a ROM-resident multiplayer patch is already working.

Keep the existing branches and local folders as forensic/reference material. Do not reset, delete, or overwrite them as part of this rebuild.

## Product goal

Create a CUBHMA workflow that can produce and apply a multiplayer patch from a user's own compatible Pokémon Emerald ROM. The patched game should start multiplayer code from the ROM itself; normal play must not depend on manually loading a Lua script. CUBHMA remains the patching interface, not the place where the multiplayer engine lives.

## Deliberately narrow first milestone

- Two players only: one local player and exactly one remote peer.
- Start with clean English Pokémon Emerald v1.0, file size `0x1000000`, game code `BPEE` at offset `0xAC`, SHA-1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`.
- One identical patched ROM for both participants; Host/Join is a runtime decision, not a compile-time master/slave ROM identity.
- Reuse the upstream project's already-working overworld object, movement-action, animation and map-transition logic where the payload interfaces permit it. Do not fork/rewrite that layer until a test demonstrates the need.
- Fixed-size storage only: no runtime heap allocation, no unbounded queues, no four-player arrays or lobby state in the initial runtime.
- Windows PowerShell build workflow for day-to-day builds. Reuse checked-in/generated symbols; the normal build must not require WSL or rebuilding the `pret/pokeemerald` decompilation.
- Keep patches and derived ROMs local to the user. Never commit or distribute ROM images.

This is a compatibility target, not a promise that arbitrary Emerald ROM hacks will work. The first patch must validate the exact source fingerprint and exact hook-site bytes. Additional ROM hacks require their own explicit compatibility profile and tests.

## Memory contract

The pinned upstream retail-USA payload layout reserves the EWRAM window from `0x0203CF80` through (but not including) `0x02040000`: `0x3080` bytes (12,416 bytes). It splits the window into two regions; the top 512 bytes are **not** unused:

- The static payload region ends at `HANDOFF_BASE = 0x0203FE00`. Header, state, mailbox, code, initialized data and BSS must all end by that address. Its maximum size is `0x2E80` bytes (11,904 bytes).
- The handoff region from `0x0203FE00` to `0x02040000` is `0x200` bytes (512 bytes). Upstream reserves `0x120` bytes (288 bytes) at the top for the private IRQ stack.
- This plan limits late-cleared data at the beginning of the handoff region to `0xC0` bytes (192 bytes). A further `0x20` bytes (32 bytes) must remain between late-cleared data and the stack.
- The upstream stack guard requires the statically calculated worst-case IRQ path to use no more than half of the `0x120`-byte stack allocation: `0x90` bytes (144 bytes). Calculate actual usage from compiler stack reports; do not assume it.

The linker/map report—not `payload.bin` length alone—is the authority. Report static payload end, BSS, late-cleared region, stack bounds and calculated worst-case stack for every candidate build. A build that violates any individual limit fails. Do not move game-owned memory boundaries or suppress a safety assertion to make a build pass.

The automated tests verify constants and arithmetic only. They do not measure a compiled payload. A linker-map and stack measurement is mandatory before embedding a build, and the layout must be re-confirmed against the exact ROM profile before runtime integration.

## Architecture boundaries

1. **CUBHMA UI and patching:** validate the input ROM, apply a BPS patch transactionally, and make Save As the safe default. No networking logic belongs in the C# editor.
2. **ROM bootstrap:** a small, separate component must validate its embedded descriptor, move/call the payload at a safe point, preserve the original game's required interrupt behavior, and fail closed when the exact expected hook bytes are absent. It must be developed against vanilla Emerald first without compiling a modified decompilation.
3. **Multiplayer runtime:** keep remote-player state to one peer initially. Use fixed-width fields and bounded buffers. Keep transport/framing separate from overworld object management.
4. **Transport/session:** implement only the minimum two-player handshake and liveness/disconnect behavior. Do not implement lobby sizes 3/4, peer arrays for three remotes, trading, or battle synchronization in the first milestone.
5. **Packaging:** embed build output into a local target ROM, generate a BPS patch from the verified clean base, and round-trip the patch against the target bytes before exposing it to CUBHMA.

The bootstrap is the riskiest new component: the previous experiments relied on the Lua injector to install the live hook, while the CUBHMA loader only copied the payload. The clean rebuild must prove a ROM-resident entry path instead of assuming that embedding bytes alone starts the code.

## Milestones and exit criteria

### M0 — Clean baseline and measurements

- [x] Checkout the rebuild branch in a separate working directory.
- [x] Verify the pinned submodule commit and keep the pre-rebuild experiment untouched.
- [x] Build the unmodified upstream payload on Windows using the documented PowerShell script and checked-in USA symbols.
- [x] Save the measured output in [baseline-memory-report.md](baseline-memory-report.md).
- [ ] Complete the skipped Lua syntax/payload-byte self-check.
- [ ] Capture section and symbol-level memory usage from the generated linker map.

**Measured baseline:** payload binary 9,680 bytes; code/data/BSS reservation 10,168 bytes; 1,736 bytes remain before `HANDOFF_BASE`; static IRQ-path stack bound 136 of 288 bytes (the build threshold is 144); and only 8 bytes separate `.lateclear` from the private stack.

This is the unmodified upstream payload with `-LinkRole loopback -Syms usa -OutName memory-baseline`, not the new two-player runtime. Its linker emitted an RWX LOAD-segment warning. The build's optional Lua check was skipped because the build script did not locate Python, even though `python --version` works interactively; that check is still open.

**Exit:** repeatable build, saved size report, Lua self-check completed, and map/symbol-level measurement captured. Do not start rewriting runtime code until these measurements are saved.

### M1 — Compact two-player runtime contract

- Define one peer's state and a fixed maximum message size only after confirming the existing upstream protocol.
- Measure every state structure with compiler output or `sizeof` assertions.
- Retain only the required sequence/deduplication state and the bounded data needed for one remote peer.
- Add host-native protocol tests for sequence wrap, duplicate events, malformed frames, disconnect timeout and map transition reset.

**Exit:** tests pass; no new field or buffer is added without a documented budget impact.

### M2 — ROM-resident bootstrap proof

- Derive the injection point from verified vanilla USA Emerald code and the matching symbol/map information.
- Require both ROM fingerprint and expected original hook bytes before patching.
- Preserve the overwritten instructions and chain back safely; reject anything ambiguous.
- Do not build a modified `pokeemerald` decompilation. If the exact startup hook cannot be proven safe by binary-level validation, stop and reassess the design rather than slipping Linux into the normal workflow.

**Exit:** patched vanilla Emerald boots through title screen and overworld in mGBA; repeated boots and save/load pass; single-player remains normal; no manual Lua injection is needed for startup.

### M3 — Two-player communication and overworld

- First prove a handshake with counters, peer identity, timeout and a visible failure state.
- Connect the validated transport to the reused remote-player logic.
- Test walking, turning, same-map play, map transitions, pause/menu entry, one peer disconnect, and reconnect.
- Repeat tests with both instances using byte-identical patched ROMs.

**Exit:** at least 30 repeatable two-instance runs without a crash, stuck player, stale remote sprite, or lost local input. This is a practical gate, not a claim of formal bug-freedom.

### M4 — CUBHMA integration

- Add a separate Quick Edit action only after the patch format and source checks are stable.
- Test wrong ROM, modified ROM, truncated patch, bad patch checksum, and saving a new output file.
- Keep generated ROMs and payload binaries ignored by Git.

**Exit:** CUBHMA refuses unsupported input safely and produces a round-trip-verified patch from a compatible ROM.

### M5 — ROM-hack profiles and extra features

Only after M4 passes, evaluate individual Emerald ROM hacks. Each profile must define what is known about the base revision, overwritten code, free space, symbol compatibility and test coverage. Four-player support, online relays, trades and battles are separate future milestones, not part of the first runtime.

## Windows development commands

The standard workflow should need PowerShell, Python 3.11+, and the Arm GNU Toolchain (including `arm-none-eabi-gcc` and `arm-none-eabi-objcopy`). The CUBHMA desktop editor uses .NET 6 / Visual Studio as in the existing project.

First inspect a clean clone and the toolchain. Do not run cleanup/reset commands against the user's current working folder. Once M0 has recorded the clean upstream build command and outputs, add an automated map-footprint check to CI so the memory contract is enforced on every payload change.

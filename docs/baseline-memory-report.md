# Measured upstream payload baseline

## Scope

This is a record of a successful local build of the **pinned upstream payload**, before any new memory-first runtime code has been written. It is reference data for the rebuild, not a release claim.

- Parent repository branch: `feature/memory-first-two-player`
- Upstream submodule commit: `9b7a51c360718a1df5a41f89ffe66b12867b0098`
- Build command: `./build.ps1 -LinkRole loopback -Syms usa -OutName memory-baseline`
- Profile: English USA Emerald symbols (BPEE)
- Transport mode: emulator loopback; no `-WithSio`
- Compiler reported by the build: Arm GNU Toolchain `14.2 rel1`
- Generated payload: `third_party/gen3-poke-multiplayer/build/payload.bin`
- Generated map: `third_party/gen3-poke-multiplayer/build/payload.map`
- Generated Lua: `third_party/gen3-poke-multiplayer/mgba/inject.memory-baseline.lua`

The build uses locally generated artifacts; do not commit the ROM or generated build binaries.

## Measurements captured from build output

| Measurement | Result |
|---|---:|
| Payload binary length | 9,680 bytes |
| Reserved code + initialized data + BSS | 10,168 bytes |
| Static EWRAM capacity before `HANDOFF_BASE` | 11,904 bytes |
| Static EWRAM margin | 1,736 bytes |
| Payload state structure | 436 bytes / 109 32-bit fields |
| Mailbox offset | `+0x1C8` |
| Worst-case statically calculated IRQ path | 136 bytes |
| Private IRQ stack allocation | 288 bytes (`0x120`) |
| Existing script's maximum accepted IRQ path | 144 bytes |
| Remaining stack-path headroom to that threshold | 8 bytes |

The calculated stack path was reported as:

`hook.S (8) → payload_frame (40) → StatusTick (8) → EmitStatus (16) → EmitEvent (32) → EmitRaw (32) = 136 bytes`.

## Handoff region and critical finding

The linker reports:

- `.lateclear` ends at `0x0203FED8`.
- The private stack begins at `0x0203FEE0`.
- Only 8 bytes separate the late-cleared data from the private stack.
- The `.lateclear` section begins at `0x0203FE00`, so its current observed size is `0xD8` (216 bytes).

This is narrower than the memory-first target contract: the rebuild intends to cap `.lateclear` at `0xC0` (192 bytes) and keep `0x20` (32 bytes) between it and the 288-byte stack. That means the target requires reclaiming at least 24 bytes from the existing late-cleared region, assuming the stack allocation and region boundaries are retained. The stack calculation also sits only 8 bytes below the existing build's 50% threshold. Neither should be hidden by weakening assertions.

## Verification status and warnings

- Payload compilation and link completed successfully.
- The linker printed a warning that `payload.elf` has a LOAD segment with RWX permissions. This did not fail the build and needs review before deciding whether it is appropriate for this embedded layout.
- The script printed `python non trovato` and did not compile-check the generated Lua script. An interactive `python --version` did work, so this appears to be a mismatch between the script's Python discovery rules and the local interpreter path, not proof that Python is absent.
- The build printed that `PayloadState` (109 fields), the Lua table, and generated offsets agree.

## Next actions

1. Run `python -c "import sys; print(sys.executable); print(sys.version)"` from the submodule folder to identify the interpreter path.
2. Run `python .\tools\check_lua.py .\mgba\inject.memory-baseline.lua .\build\payload.bin` manually. This utility uses `lupa` when installed to compile the Lua and verify the embedded payload bytes; if `lupa` is missing it will report that the optional check was skipped.
3. Save a symbol/section report from `payload.elf` and `payload.map` before designing new data structures.
4. Use this as the reference baseline only. The actual memory-first runtime is not implemented or verified yet.

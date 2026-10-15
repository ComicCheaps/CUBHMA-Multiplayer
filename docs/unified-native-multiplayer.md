# Unified native multiplayer: runtime lobby and four-player transport

## Goal

Build one byte-identical Emerald ROM for every participant. Multiplayer is optional; players select it from an in-game Multiplayer menu, then choose Host or Join. The host selects a lobby size from 2 to 4 players. No player should need a separately compiled "master" or "slave" ROM.

## Current prototype limitations

- `prepare_native_link_roms.ps1` creates separate master/slave ROMs.
- `PAYLOAD_NATIVE_SIO_MASTER` currently controls who starts serial transfers at compile time.
- `payload/sio.c` contains one RX parser and only consumes one hardware data register. It therefore cannot independently decode all three remote players.
- The overworld already has three remote-player slots, and `EVENT_SLOT` already reserves the high type bits for the receiver's remote slot. The missing work is in the transport and session layer, not the object-event count.
- Movement snapshots currently retain state for only one peer, so the snapshot receiver must become per-peer too.

## Intended player flow

1. Open the Multiplayer option from the in-game menu. Normal single-player continues to work without starting SIO.
2. Choose Host or Join.
3. Host chooses 2, 3, or 4 total players; joiners search/wait for the host.
4. The host drives SIO clock transfers. Joining consoles use the same ROM but do not start the clock.
5. The lobby displays detected player slots and waits for the configured number of participants. The host starts the session when everyone is present, or cancels back to the game.
6. Each ROM uses its SIO hardware ID to identify the local player and map the other three IDs into local remote slots. A received event must carry its sender-slot metadata into the existing per-slot event queue.

## Required technical changes

### Session lifecycle

- Add runtime `SioSetRole` / session start-stop control; remove role choice from the ROM's compiled identity.
- Keep the serial port inactive in single-player.
- Add a menu state machine with Host, Join, Lobby Size, Connect/Cancel, and a player-count display.
- Establish an explicit lobby handshake so joiners learn the host's chosen size and session state; do not infer lobby state from sprite presence alone.

### Four-player serial protocol

- Keep one transmit stream per ROM. In multiplayer SIO, the parent clocks transfers and every console supplies one word per transfer.
- Maintain a separate RX decoder per remote hardware ID (SIOMULTI0 through SIOMULTI3, skipping the local ID).
- Route decoded reliable events into remote slots 0-2 by adding the source slot to the event type's reserved high bits.
- Maintain one latest-state movement snapshot per remote player, not one global snapshot.
- Ignore absent slots, recover from missed frames, and retain reliable map/door/status/card messages.

### Safety and compatibility

- Preserve the existing native two-player build and adapter/Lua build until the unified ROM is independently verified.
- Keep changes on this branch until two-player and four-player tests pass.
- Do not replace the existing tested ROMs or modify the original clean ROM.
- Verify the payload EWRAM and stack budgets after every transport change.

## Verification checklist

- A host ROM and one joiner ROM have identical hashes.
- Two copies of that same ROM connect after choosing Host and Join.
- No connection is made in single-player mode.
- A lobby size of 2 does not admit a third peer; sizes 3 and 4 wait for the matching participant count.
- Four consoles see the correct three remote characters, each with independent movement, status, trainer card, and map-transition state.
- Missing/unplugged peers do not freeze movement or cause stale characters to remain.
- Native SIO adapter builds and legacy payload builds still compile, and the payload fits its reserved EWRAM/stack budgets.

## First implementation milestone: unified two-player proof of concept

The branch now includes source-patch and build helpers for one ROM that can select Host or Join at runtime. The test menu is opened with SELECT in the overworld, and single-player leaves native SIO inactive. The dedicated output is `build/unified/Emerald-unified.gba`.

This milestone is deliberately limited to two players. It does not yet implement the lobby-size selector, a full join/ready handshake, or four-player SIO receive demultiplexing. The patch and build scripts have not yet been verified against the user's local ARM toolchain; treat the resulting ROM as a test build and keep the previous working master/slave ROMs untouched.


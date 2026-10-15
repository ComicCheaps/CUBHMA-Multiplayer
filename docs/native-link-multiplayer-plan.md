# Native-link multiplayer roadmap

## Goal

Build a patched English Pokémon Emerald ROM whose multiplayer code starts from inside the ROM and exchanges remote-player information through a Game Boy Advance link-cable connection supported by the emulator. The player should not have to load an mGBA Lua script or start a separate per-emulator TCP/UDP bridge.

The first milestone remains intentionally small: two copies of the modified game connect, see each other's trainer sprites, and observe walking animations on the same map.

## What we learned from the current prototype

The existing `gen3-poke-multiplayer` project already contains valuable remote-player logic: it creates object events, sends movement events instead of constantly teleporting coordinates, and handles map transitions.

Its transport implementations are not interchangeable:

- Its mGBA emulator path uses a Lua script as the injector and network bridge.
- Its `-WithSio` build is documented for a real GBA connected through a physical adapter/firmware. The build deliberately marks this payload as unsuitable for the normal mGBA script path unless a special diagnostic override is used.

The CUBHMA loader currently copies the payload into EWRAM but intentionally leaves the live IRQ vector alone. The Lua injector is responsible for installing the hook. That bootstrap therefore cannot yet provide a script-free startup by itself.

Consequently, this is **not** solved by changing the ROM fingerprint, setting `-WithSio`, or embedding the current payload unchanged.

## Target architecture

1. **ROM-resident bootstrap.** The patch embeds the multiplayer code and starts it automatically from the game. The bootstrap must validate the embedded descriptor and hook safely after the game's required memory and interrupt initialization. It must preserve and chain the original IRQ handler.
2. **Emulator-compatible GBA link transport.** Implement a transport specifically for the emulator's link-cable mode. It must exchange small, framed movement/map messages between the game instances, establish player slots, recover from lost or late messages, and leave the serial hardware available to the game's existing Cable Club/trade/battle routines.
3. **Transport-neutral remote-player logic.** Reuse the existing payload's overworld tracking, remote object creation, movement actions, and sprite animation wherever its constraints permit. Keep communication code separate from the game-object code.
4. **In-game status and failure handling.** Add a small way to identify disconnected/unpaired peers and make development failures visible without a script console.
5. **CUBHMA packaging.** Keep the ROM patching workflow, but stop making mGBA Lua scripts and TCP bridge startup a prerequisite for the target experience.

A GBA link cable is a data channel, not internet by itself. Online play still depends on an emulator/core that can connect its virtual link cable between players. The Pokémon Quetzal online guide documents RetroArch with the gpSP core and its “Link Cable - Pokémon Gen3 mode” setting. This project will implement its own compatible gameplay layer rather than assume access to Quetzal's private implementation.

## Build and verification milestones

### Milestone A — prove the emulated serial transport

Before touching remote sprites, build a small native test for two instances. Display or record a successful handshake, peer IDs, incrementing transmit/receive counters, checksum errors, and peer timeout. Verify that both instances can exchange data using the chosen emulator/core.

### Milestone B — start embedded code without Lua

Make the patch load the resident code and install its hook automatically. Confirm the original game still boots, menus work, and the original IRQ handler continues to run. Repeated boots and save/load must be safe.

### Milestone C — connect the existing remote-player layer

Feed received movement and map events into the payload's existing queue/mailbox, then verify trainer visibility, walking/running animations, and map transitions.

### Milestone D — regression and expansion

Confirm that standard Cable Club link sessions can still use the serial port, peers can disconnect/reconnect safely, and two-player co-op works over multiple maps before considering trading/battle integration or more players.

## Guardrails

- Do not distribute or commit ROM images. Work from the user's own locally obtained base ROM.
- Do not claim multiplayer works until two instances pass the handshake and overworld tests.
- Keep the Lua/bridge prototype as a reference for comparison, not as the final startup or networking architecture.
- Never switch the current build to `-WithSio` in hopes of making it work in an emulator; that payload is documented for a different transport setup.

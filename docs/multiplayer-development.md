# Emerald multiplayer development notes

## Fixed compatibility target

This patch workflow accepts only clean retail English Pokémon Emerald v1.0:
- File size: 16 MiB (0x1000000 bytes)
- Game code at 0xAC: BPEE
- SHA-1: f3ae088181bf583e55daf962a92bb46f4f1d07b7

The ROM is supplied locally by the user. Never commit or upload ROM files or built game images.

## Patch generation

1. Set up the original decompilation using the upstream pret/pokeemerald build instructions.
2. Use your own clean English Emerald v1.0 ROM as that build's base ROM.
3. Implement and test the game-side multiplayer changes in the decompilation.
4. Compile the modified game ROM locally.
5. Run this from the CUBHMA repository root:

   python tools/build_multiplayer_patch.py C:/path/to/clean_emerald.gba C:/path/to/built_pokeemerald.gba

The utility checks the source fingerprint and target game code, creates a BPS1 patch, reapplies it in memory, and verifies that the output exactly matches the compiled target. It writes deterministic gzip output to:

   src/HexManiac.Core/ViewModels/QuickEditItems/multiplayer_emerald.bps.gz

The WPF project automatically packages that optional file as resources/multiplayer_emerald.bps.gz. The generated file is intentionally ignored by Git so a locally produced ROM patch is not accidentally committed. The patcher tool will report that the game-side patch is missing until that file exists.

A different region, copier-header ROM, edited source ROM, wrong checksum, or wrong game code is rejected.

## Game-side milestones

The CUBHMA tool only transports an already-built patch; it does not create multiplayer behavior. The game-side work remains the main task.

1. Transport smoke test: connect two Emerald instances in the intended GBA link-cable emulator mode.
2. Overworld session: keep the link session alive outside the original Cable Club flow and handle disconnect/reconnect.
3. Player replication: show remote trainer object events and synchronize map identity, coordinates, facing, movement, and animations.
4. Transitions: resynchronize safely after doors, warps, map changes, menus, battles, and save/load.
5. Interactions: define NPC scripts, item pickups, trainer battles, and event handling. Start with independent story progression for each player.
6. Qualification: build from the exact clean ROM above, round-trip the patch, test application in CUBHMA, and test two connected emulator instances before shipping.

Vanilla Emerald already contains code for link-room players and exchanging their key input, but that alone does not enable free-roaming co-op. Extending link sessions and player replication to normal overworld maps is the substantive game-side task. Quetzal is a behavioral reference, not code included in this project.

## Local tests

Run: python -m unittest discover -s tools/tests -v

The tests use short synthetic byte sequences; they do not require a real ROM.

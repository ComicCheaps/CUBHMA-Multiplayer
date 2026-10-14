# Emerald multiplayer development

This branch targets local cooperative overworld multiplayer for the original English Pokémon Emerald v1.0 ROM, using CUBHMA as the ROM patching interface.

The game-side runtime comes from the public gen3-poke-multiplayer project, pinned as a GPL-3.0 submodule. The integration glue, local payload packager, and CUBHMA patcher remain separate. Keep the third-party source and license when redistributing derivative payload builds.

## Compatibility target

- Clean English Pokémon Emerald v1.0 only
- File size: 16 MiB (0x1000000)
- Game code at offset 0xAC: BPEE
- SHA-1: f3ae088181bf583e55daf962a92bb46f4f1d07b7

Use your own legally obtained clean ROM as the decompilation's baserom.gba. Never upload it, commit it, or share a pre-patched ROM image.

## Build workflow

1. Initialise the payload submodule:

~~~powershell
git submodule update --init --recursive
~~~

2. Set up pret/pokeemerald following its official build instructions, with your own clean English Emerald v1.0 baserom.gba. Run from the CUBHMA repository:

~~~powershell
python tools/integrate_pokeemerald.py --pokeemerald "C:/src/pokeemerald"
~~~

The installer backs up src/main.c, adds one loader source file and a call during AgbMain startup, refuses partial/ambiguous states, and supports --revert. The loader does nothing while descriptor markers remain unpatched.

3. Build the modified decompilation by its usual process (normally WSL/Linux with the GBA toolchain):

~~~bash
make -j"$(nproc)"
~~~

This intentionally modified build is not expected to pass the original ROM's byte-for-byte comparison. The modified build's map must match the loader-integrated sources.

4. Generate function symbols and build a local server and client script from the pinned payload project:

~~~powershell
python ./third_party/gen3-poke-multiplayer/tools/gen_syms.py "C:/src/pokeemerald/pokeemerald.map"
Push-Location ./third_party/gen3-poke-multiplayer
./build.ps1 -LinkRole server -LinkHost 127.0.0.1 -LinkPort 8765 -OutName local-server
./build.ps1 -LinkRole client -LinkHost 127.0.0.1 -LinkPort 8765 -OutName local-client
Pop-Location
~~~

These generate payload.bin, payload.map and two Lua scripts under the submodule. They are local build outputs, not committed files.

5. Embed payload.bin into the modified target ROM, then generate a BPS patch against the clean ROM:

~~~powershell
python tools/package_multiplayer_payload.py "C:/src/pokeemerald/pokeemerald.gba" "./third_party/gen3-poke-multiplayer/build/payload.bin" "./third_party/gen3-poke-multiplayer/build/payload.map" "./build/pokeemerald-multiplayer-embedded.gba"
python tools/build_multiplayer_patch.py "C:/path/to/your-clean-emerald.gba" "./build/pokeemerald-multiplayer-embedded.gba" --output "./src/HexManiac.Core/ViewModels/QuickEditItems/multiplayer_emerald.bps.gz"
~~~

The packager validates the payload HOOK header, linker-map end symbol, reserved EWRAM space, descriptor uniqueness, and game code. The BPS tool verifies the clean ROM fingerprint and round-trips the generated patch byte-for-byte. Generated ROM/payload files are git-ignored.

6. Build CUBHMA:

~~~powershell
dotnet build HexManiacAdvance.sln -c Release -p:PlatformTarget=x64
~~~

Open your clean ROM and run Utilities → Misc → Apply Emerald Multiplayer. Use File → Save As to keep the original file. The CUBHMA build optionally packages the generated server and client scripts under resources/multiplayer.

7. For the first local test, open the patched output in two mGBA instances, enter the overworld, load inject.local-server.lua in the first and inject.local-client.lua in the second, and confirm both trainers can see each other moving. Then test a route transition. This workflow is local server/client link mode; it does not imply online Internet matchmaking.

## Tests and release status

Run the Python packaging tests without a ROM:

~~~powershell
python -m unittest discover -s tools/tests -v
~~~

CI also builds CUBHMA and runs its unit-test project. The real Emerald build, actual payload fit, two-instance multiplayer session, map transitions and clean-ROM BPS output still need to be tested locally before this feature is release-ready.

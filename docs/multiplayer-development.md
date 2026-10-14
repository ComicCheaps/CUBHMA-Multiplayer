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

Set up pret/pokeemerald following its official build instructions and use your own clean English Emerald v1.0 ROM.

2. Add the payload loader to your local decompilation:

~~~powershell
python tools/integrate_pokeemerald.py --pokeemerald "C:/src/pokeemerald"
~~~

The installer backs up src/main.c, adds one loader source file and a call during AgbMain startup, refuses partial/ambiguous states, and supports --revert. The loader does nothing while descriptor marker values remain unpatched.

3. Build the modified decompilation using pret/pokeemerald's usual build process (normally WSL/Linux with the GBA toolchain):

~~~bash
make -j"$(nproc)"
~~~

This intentionally modified build is not expected to pass the original ROM's byte-for-byte comparison. The modified build's map must match the loader-integrated sources.

4. Generate function symbols from the modified map and build the two local mGBA client scripts:

~~~powershell
python ./third_party/gen3-poke-multiplayer/tools/gen_syms.py "C:/src/pokeemerald/pokeemerald.map"
Push-Location ./third_party/gen3-poke-multiplayer
./build.ps1 -LinkRole client -LinkPort 8201 -OutName p1 -Syms usa
./build.ps1 -LinkRole client -LinkPort 8202 -OutName p2 -Syms usa
Pop-Location
~~~

These generate payload.bin, payload.map, inject.p1.lua and inject.p2.lua under the submodule. These scripts use two local TCP ports; the project's Python relay/bridge connects them together.

5. Embed payload.bin into the modified target ROM, then generate a BPS patch against the clean ROM:

~~~powershell
python tools/package_multiplayer_payload.py "C:/src/pokeemerald/pokeemerald.gba" "./third_party/gen3-poke-multiplayer/build/payload.bin" "./third_party/gen3-poke-multiplayer/build/payload.map" "./build/pokeemerald-multiplayer-embedded.gba"
python tools/build_multiplayer_patch.py "C:/path/to/your-clean-emerald.gba" "./build/pokeemerald-multiplayer-embedded.gba" --output "./src/HexManiac.Core/ViewModels/QuickEditItems/multiplayer_emerald.bps.gz"
~~~

The packager validates the payload HOOK header, linker-map end symbol, reserved EWRAM space, descriptor uniqueness and game code. The BPS tool verifies the clean ROM fingerprint and round-trips the patch byte-for-byte. Generated ROM/payload files are git-ignored.

6. Build CUBHMA after the two scripts and patch exist:

~~~powershell
dotnet build HexManiacAdvance.sln -c Release -p:PlatformTarget=x64
~~~

When present, CUBHMA packages the BPS patch plus resources/multiplayer/inject.p1.lua and inject.p2.lua. Open your clean ROM and run Utilities → Misc → Apply Emerald Multiplayer; use File → Save As to preserve the original.

7. Test two local players. In PowerShell, start the submodule's local relay and TCP bridges using the scripts already generated above:

~~~powershell
Push-Location ./third_party/gen3-poke-multiplayer/net
./run-local.ps1 -SkipBuild
~~~

Open the patched ROM in two mGBA instances and enter the overworld. In instance 1, load resources/multiplayer/inject.p1.lua via Tools → Scripting → Load script; in instance 2, load resources/multiplayer/inject.p2.lua. Confirm both trainers can see each other moving, then test a route transition. Keep the relay/bridge process open while playing.

## Tests and release status

Run the Python packaging tests without a ROM:

~~~powershell
python -m unittest discover -s tools/tests -v
~~~

CI also builds CUBHMA and runs its unit-test project. The actual Emerald build, payload fit, two-instance session, map transitions and clean-ROM BPS output still need local validation before this feature is release-ready.

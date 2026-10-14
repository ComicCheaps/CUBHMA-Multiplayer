[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PokeemeraldRoot,

    [Parameter(Mandatory = $true)]
    [string]$CleanEmeraldRom,

    [string]$OutputRom = "",

    [ValidateRange(1, 65535)]
    [int]$Port1 = 8201,

    [ValidateRange(1, 65535)]
    [int]$Port2 = 8202
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$submoduleRoot = Join-Path $repoRoot "third_party\gen3-poke-multiplayer"
$pokeemerald = (Resolve-Path $PokeemeraldRoot).Path
$cleanRom = (Resolve-Path $CleanEmeraldRom).Path
$builtRom = Join-Path $pokeemerald "pokeemerald.gba"
$mapPath = Join-Path $pokeemerald "pokeemerald.map"
$payloadBin = Join-Path $submoduleRoot "build\payload.bin"
$payloadMap = Join-Path $submoduleRoot "build\payload.map"
$symbolsScript = Join-Path $submoduleRoot "tools\gen_syms.py"
$packageScript = Join-Path $repoRoot "tools\package_multiplayer_payload.py"
$patchScript = Join-Path $repoRoot "tools\build_multiplayer_patch.py"
$embeddedRom = if ([string]::IsNullOrWhiteSpace($OutputRom)) {
    Join-Path $repoRoot "build\pokeemerald-multiplayer-embedded.gba"
} else {
    [System.IO.Path]::GetFullPath($OutputRom)
}
$bpsOutput = Join-Path $repoRoot "src\HexManiac.Core\ViewModels/QuickEditItems/multiplayer_emerald.bps.gz"

foreach ($required in @($builtRom, $mapPath, $cleanRom, $symbolsScript, $packageScript, $patchScript)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required input file not found: $required"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $submoduleRoot "build.ps1") -PathType Leaf)) {
    throw "Multiplayer submodule is missing. Run: git submodule update --init --recursive"
}
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw "Python was not found on PATH." }
$python = $pythonCommand.Source
if ([string]::IsNullOrWhiteSpace($python)) { $python = "python" }

Write-Output "Step 1/4: Generate game function symbols from the modified Emerald map..."
& $python $symbolsScript $mapPath
if ($LASTEXITCODE -ne 0) { throw "gen_syms.py failed (exit $LASTEXITCODE)." }

Write-Output "Step 2/4: Build matching payload and two local mGBA client scripts..."
Push-Location $submoduleRoot
try {
    & ".\build.ps1" -LinkRole client -LinkPort $Port1 -OutName "p1" -Syms usa
    & ".\build.ps1" -LinkRole client -LinkPort $Port2 -OutName "p2" -Syms usa
} finally {
    Pop-Location
}
foreach ($required in @($payloadBin, $payloadMap, (Join-Path $submoduleRoot "mgba\inject.p1.lua"), (Join-Path $submoduleRoot "mgba\inject.p2.lua"))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Expected build output not found: $required"
    }
}

Write-Output "Step 3/4: Embed the payload into the locally built Emerald ROM..."
& $python $packageScript $builtRom $payloadBin $payloadMap $embeddedRom
if ($LASTEXITCODE -ne 0) { throw "Payload embedding failed (exit $LASTEXITCODE)." }

Write-Output "Step 4/4: Generate a BPS patch against the supplied clean ROM..."
& $python $patchScript $cleanRom $embeddedRom --output $bpsOutput
if ($LASTEXITCODE -ne 0) { throw "BPS generation failed (exit $LASTEXITCODE)." }

Write-Output ""
Write-Output "Multiplayer patch generated and round-trip verified:"
Write-Output "  BPS: $bpsOutput"
Write-Output "  Scripts: $(Join-Path $submoduleRoot 'mgba\inject.p1.lua') and inject.p2.lua"
Write-Output "Next: build CUBHMA, apply Utilities > Misc > Apply Emerald Multiplayer, then test two mGBA instances."

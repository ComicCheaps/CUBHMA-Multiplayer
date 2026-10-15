[CmdletBinding()]
param(
    [string]$PokeemeraldRoot = "C:\src\pokeemerald"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$submoduleRoot = Join-Path $repoRoot "third_party\gen3-poke-multiplayer"
$gameRoot = (Resolve-Path $PokeemeraldRoot).Path
$builtRom = Join-Path $gameRoot "pokeemerald.gba"
$mapPath = Join-Path $gameRoot "pokeemerald.map"
$symbolsScript = Join-Path $submoduleRoot "tools\gen_syms.py"
$buildScript = Join-Path $submoduleRoot "build.ps1"
$payloadBin = Join-Path $submoduleRoot "build\payload.bin"
$payloadMap = Join-Path $submoduleRoot "build\payload.map"
$packageScript = Join-Path $repoRoot "tools\package_multiplayer_payload.py"
$outputDir = Join-Path $repoRoot "build\native-link"

foreach ($required in @($builtRom, $mapPath, $symbolsScript, $buildScript, $packageScript)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw ("Required build input not found: " + $required + [Environment]::NewLine + "Build the modified pokeemerald project first.")
    }
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw "Python was not found on PATH." }
$python = $pythonCommand.Source
if ([string]::IsNullOrWhiteSpace($python)) { $python = "python" }

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

Write-Output "Step 1/5: Regenerate game symbols from the current modified-ROM map..."
& $python $symbolsScript $mapPath
if ($LASTEXITCODE -ne 0) { throw "gen_syms.py failed (exit $LASTEXITCODE)." }

foreach ($role in @("master", "slave")) {
    Write-Output ""
    Write-Output "Step 2/5: Build the native SIO payload for role '$role'..."
    Push-Location $submoduleRoot
    try {
        & ".\build.ps1" -WithSio -NativeSioRole $role -LinkRole "off" -OutName "native-$role" -Syms "usa"
        if ($LASTEXITCODE -ne 0) { throw "Payload build for role '$role' failed (exit $LASTEXITCODE)." }
    } finally {
        Pop-Location
    }

    foreach ($required in @($payloadBin, $payloadMap)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Expected payload build output not found: $required"
        }
    }

    $roleRom = Join-Path $outputDir "Emerald-native-$role.gba"
    Write-Output "Step 3/5: Package the '$role' payload into a separate local test ROM..."
    & $python $packageScript $builtRom $payloadBin $payloadMap $roleRom
    if ($LASTEXITCODE -ne 0) { throw "ROM packaging for role '$role' failed (exit $LASTEXITCODE)." }
    if (-not (Test-Path -LiteralPath $roleRom -PathType Leaf)) {
        throw "Packager reported success, but test ROM was not found: $roleRom"
    }
    Write-Output "Created: $roleRom"
}

Write-Output ""
Write-Output "Step 4/5: Verify that both role ROMs exist..."
$masterRom = Join-Path $outputDir "Emerald-native-master.gba"
$slaveRom = Join-Path $outputDir "Emerald-native-slave.gba"
foreach ($rom in @($masterRom, $slaveRom)) {
    $file = Get-Item -LiteralPath $rom
    Write-Output ("{0} ({1:N1} MiB)" -f $file.FullName, ($file.Length / 1MB))
}

Write-Output ""
Write-Output "Step 5/5: Build preparation complete."
Write-Output "These are unverified prototype ROMs. Do not overwrite baserom.gba or your current patched copies."
Write-Output "Next test: use two emulator instances with a virtual GBA cable connection, then check the in-game serial handshake."

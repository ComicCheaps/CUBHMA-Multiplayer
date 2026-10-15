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
$outputDir = Join-Path $repoRoot "build\unified"
$outputRom = Join-Path $outputDir "Emerald-unified.gba"

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

Write-Output "Step 1/3: Regenerate game symbols from the current modified-ROM map..."
& $python $symbolsScript $mapPath
if ($LASTEXITCODE -ne 0) { throw "gen_syms.py failed (exit $LASTEXITCODE)." }

Write-Output ""
Write-Output "Step 2/3: Build the single unified native-SIO payload..."
Push-Location $submoduleRoot
try {
    & ".\build.ps1" -WithSio -NativeSioRole "unified" -LinkRole "off" -OutName "native-unified" -Syms "usa"
    if ($LASTEXITCODE -ne 0) { throw "Unified payload build failed (exit $LASTEXITCODE)." }
} finally {
    Pop-Location
}

foreach ($required in @($payloadBin, $payloadMap)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Expected payload build output not found: $required"
    }
}

Write-Output ""
Write-Output "Step 3/3: Package one identical ROM for hosts and joiners..."
& $python $packageScript $builtRom $payloadBin $payloadMap $outputRom
if ($LASTEXITCODE -ne 0) { throw "Unified ROM packaging failed (exit $LASTEXITCODE)." }
if (-not (Test-Path -LiteralPath $outputRom -PathType Leaf)) {
    throw "Packager reported success, but unified ROM was not found: $outputRom"
}

$file = Get-Item -LiteralPath $outputRom
Write-Output ""
Write-Output ("Created: {0} ({1:N1} MiB)" -f $file.FullName, ($file.Length / 1MB))
Write-Output "Use this exact file for BOTH emulator instances."
Write-Output "This prototype supports runtime Host/Join for two players. Four-player lobby sizing is not implemented yet."
Write-Output "Keep your existing master/slave test ROMs as backups."

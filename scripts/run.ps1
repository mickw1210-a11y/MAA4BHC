param([switch]$Offline, [switch]$SmokeTest, [switch]$ManualInventory, [switch]$ReadOnly, [switch]$InventoryCapture)
. (Join-Path $PSScriptRoot 'project-env.ps1')
Set-Location -LiteralPath $ProjectRoot
$ProjectPython = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ProjectPython)) { throw '请先运行 scripts/setup.ps1' }
$ProjectArgs = @('-m','app.main')
if ($Offline) { $ProjectArgs += '--offline' }
if ($SmokeTest) { $ProjectArgs += '--smoke-test' }
if ($ManualInventory) { $ProjectArgs += '--manual-inventory' }
if ($ReadOnly) { $ProjectArgs += '--read-only' }
if ($InventoryCapture) { $ProjectArgs += '--inventory-capture' }
& $ProjectPython @ProjectArgs
exit $LASTEXITCODE


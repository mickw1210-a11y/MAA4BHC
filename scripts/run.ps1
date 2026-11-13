param([switch]$Offline, [switch]$SmokeTest, [switch]$ManualInventory, [switch]$ReadOnly, [switch]$InventoryCapture)
. (Join-Path $PSScriptRoot 'project-env.ps1')
Set-Location -LiteralPath $ProjectRoot
$ProjectPython = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ProjectPython)) { throw '请先运行 scripts/setup.ps1' }
& $ProjectPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { throw '项目 Python 无法运行或版本低于 3.10；请检查项目环境并使用 Python 3.10 或更新版本。' }
$ProjectArgs = @('-m','app.main')
if ($Offline) { $ProjectArgs += '--offline' }
if ($SmokeTest) { $ProjectArgs += '--smoke-test' }
if ($ManualInventory) { $ProjectArgs += '--manual-inventory' }
if ($ReadOnly) { $ProjectArgs += '--read-only' }
if ($InventoryCapture) { $ProjectArgs += '--inventory-capture' }
& $ProjectPython @ProjectArgs
exit $LASTEXITCODE


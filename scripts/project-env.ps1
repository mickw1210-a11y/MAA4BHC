$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProjectCache = Join-Path $ProjectRoot '.cache'
foreach ($name in @('tmp','pip','npm','pycache')) {
    New-Item -ItemType Directory -Path (Join-Path $ProjectCache $name) -Force | Out-Null
}
New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'runtime/logs') -Force | Out-Null
$env:TEMP = Join-Path $ProjectCache 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $ProjectCache 'pip'
$env:PIP_CONFIG_FILE = 'NUL'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$env:PYTHONPYCACHEPREFIX = Join-Path $ProjectCache 'pycache'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:NPM_CONFIG_CACHE = Join-Path $ProjectCache 'npm'
$env:NPM_CONFIG_UPDATE_NOTIFIER = 'false'
$env:DOTNET_CLI_HOME = Join-Path $ProjectCache 'dotnet'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'


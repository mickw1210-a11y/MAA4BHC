param([string]$Python = 'python')
. (Join-Path $PSScriptRoot 'project-env.ps1')
Set-Location -LiteralPath $ProjectRoot
$ProjectPython = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ProjectPython)) {
    & $Python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw '无法使用指定的 Python；请选择 Python 3.10 或更新版本后重试。' }
    & $Python -m venv (Join-Path $ProjectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw '无法创建项目Python环境' }
}
& $ProjectPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { throw '项目 Python 无法运行或版本低于 3.10；请检查项目环境并使用 Python 3.10 或更新版本。' }
& $ProjectPython -m pip install --index-url https://pypi.org/simple --prefer-binary --only-binary=maafw,pillow,numpy,pythonnet,cffi --log (Join-Path $ProjectRoot 'runtime/logs/pip-install.log') -r (Join-Path $ProjectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python依赖安装失败' }
$ProjectLock = & $ProjectPython -m pip freeze
if ($LASTEXITCODE -ne 0) { throw '无法读取安装结果' }
[System.IO.File]::WriteAllLines((Join-Path $ProjectRoot 'requirements-lock.txt'), [string[]]$ProjectLock, (New-Object System.Text.UTF8Encoding($false)))
Push-Location (Join-Path $ProjectRoot 'ui')
try {
    if (Test-Path -LiteralPath 'package-lock.json') { & npm.cmd ci --registry=https://registry.npmjs.org }
    else { & npm.cmd install --registry=https://registry.npmjs.org }
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }


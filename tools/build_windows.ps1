$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv and pip install -e .[dev] first.' }
& $python -B tools/release_resources.py
if ($LASTEXITCODE -ne 0) { throw 'Resource validation failed' }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $python -m PyInstaller --noconfirm --clean packaging/FirmwareColorStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
$version = & $python -c 'from firmware_color_studio import __version__; print(__version__)'
$compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($compiler) { $compilerPath = $compiler.Source }
else { $compilerPath = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe' }
if (-not (Test-Path -LiteralPath $compilerPath)) { throw 'Install Inno Setup 6 first.' }
& $compilerPath "/DAppVersion=$version" packaging/installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
$installer = Join-Path $repoRoot "dist\FirmwareColorStudio-$version-windows-x64-setup.exe"
$hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($installer))" | Set-Content -LiteralPath (Join-Path $repoRoot 'dist\SHA256SUMS.txt') -Encoding ascii
Write-Output $installer

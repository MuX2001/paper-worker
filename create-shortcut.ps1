$ErrorActionPreference = 'Stop'
$venv = Join-Path $PSScriptRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$base = & $python -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Could not locate the base Python installation.' }
# A native GUI interpreter under the venv discovers ../pyvenv.cfg directly.
# Keep its runtime DLLs alongside it so Explorer's PATH is immaterial.
$guiDir = New-Item -ItemType Directory -Force -Path (Join-Path $venv 'GUI')
Copy-Item -LiteralPath (Join-Path $base 'pythonw.exe') -Destination $guiDir.FullName -Force
Get-ChildItem -LiteralPath $base -Filter '*.dll' -File |
    Copy-Item -Destination $guiDir.FullName -Force
$pythonw = Join-Path $guiDir.FullName 'pythonw.exe'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $PSScriptRoot 'Paper Worker.lnk'))
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m paper_worker.gui'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Save()

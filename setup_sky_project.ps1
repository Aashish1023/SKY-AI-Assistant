# setup_sky_project.ps1
# Project Sky - Phase 1, Step 1.1: project skeleton + virtual environment.
# Safe to re-run: it never overwrites files that already exist.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\setup_sky_project.ps1
#   powershell -ExecutionPolicy Bypass -File .\setup_sky_project.ps1 -Root "D:\Dev\sky"

param(
    [string]$Root = (Join-Path $HOME "Projects\sky")
)

$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath($Root)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Step($msg) { Write-Host ""; Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "   OK  $msg" -ForegroundColor Green }
function Write-Skip($msg) { Write-Host "   --  $msg" -ForegroundColor DarkGray }

function Write-FileIfMissing([string]$RelPath, [string]$Content) {
    $full = Join-Path $Root $RelPath
    if (Test-Path $full) { Write-Skip "exists:  $RelPath"; return }
    [System.IO.File]::WriteAllText($full, $Content, $utf8NoBom)
    Write-Ok "created: $RelPath"
}

# ---------------------------------------------------------------- Python
Write-Step "Checking Python"
try {
    $ver = (& python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
} catch {
    throw "Python was not found on PATH. Install Python 3.11+ and re-run."
}
if ([version]$ver -lt [version]'3.11') { throw "Python $ver found, but 3.11 or newer is required." }
Write-Ok "Python $ver"

# ----------------------------------------------------------- Directories
Write-Step "Creating folders in $Root"
$dirs = @(
    'app\core', 'app\ai', 'app\voice', 'app\memory', 'app\automation',
    'app\productivity', 'app\ui', 'app\utils',
    'data', 'logs', 'scripts', 'tests', 'assets\icons', 'assets\sounds'
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
}
Write-Ok "folder tree ready"

# --------------------------------------------------------------- Files
Write-Step "Writing project files"

$packages = @(
    'app', 'app\core', 'app\ai', 'app\voice', 'app\memory',
    'app\automation', 'app\productivity', 'app\ui', 'app\utils'
)
foreach ($p in $packages) { Write-FileIfMissing "$p\__init__.py" "" }
Write-FileIfMissing 'assets\icons\.gitkeep' ""
Write-FileIfMissing 'assets\sounds\.gitkeep' ""

Write-FileIfMissing 'requirements.txt' @'
# Runtime dependencies for Sky (Phase 1)
PySide6-Essentials>=6.8
ollama>=0.4
psutil>=6.0
'@

Write-FileIfMissing 'requirements-dev.txt' @'
-r requirements.txt
pytest>=8.0
'@

Write-FileIfMissing '.gitignore' @'
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
logs/
*.db
.env
'@

Write-FileIfMissing 'pytest.ini' @'
[pytest]
testpaths = tests
pythonpath = .
'@

Write-FileIfMissing 'README.md' @'
# Sky

A local, voice-first AI desktop assistant for Windows.

Status: Phase 1 (foundation) in progress.

## Run

    .\.venv\Scripts\python.exe main.py

## Test

    .\.venv\Scripts\python.exe -m pytest
'@

Write-FileIfMissing 'main.py' @'
"""Sky entry point (placeholder - replaced in step 1.5)."""
from __future__ import annotations

import sys


def main() -> int:
    print(f"Sky scaffold is in place. Python {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@

Write-FileIfMissing 'scripts\check_env.py' @'
"""Quick sanity check that Sky's dependencies are installed."""
from __future__ import annotations

import sys
from importlib import metadata

REQUIRED = ("PySide6-Essentials", "ollama", "psutil", "pytest")


def main() -> int:
    print(f"Python {sys.version.split()[0]}")
    failed = False

    for name in REQUIRED:
        try:
            print(f"  {name:<24} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            print(f"  {name:<24} MISSING")
            failed = True

    try:
        from PySide6 import QtWidgets  # noqa: F401

        print(f"  {'PySide6 QtWidgets':<24} import OK")
    except Exception as exc:
        print(f"  {'PySide6 QtWidgets':<24} import FAILED: {exc}")
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
'@

Write-FileIfMissing 'tests\test_smoke.py' @'
"""Smoke tests: the environment and project layout are sane."""
import sys


def test_python_version_supported():
    assert sys.version_info >= (3, 11)


def test_app_package_importable():
    import app  # noqa: F401
'@

# ---------------------------------------------------------------- Venv
Write-Step "Creating virtual environment"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    Write-Skip ".venv already exists"
} else {
    & python -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
    Write-Ok ".venv created"
}

Write-Step "Installing dependencies (a few hundred MB - this can take several minutes)"
& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed. Check your internet connection." }
& $venvPy -m pip install -r (Join-Path $Root "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Copy the error above and send it to me." }
Write-Ok "dependencies installed"

# ----------------------------------------------------------------- Git
Write-Step "Git"
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $Root ".git")) {
        Write-Skip "git repository already initialised"
    } else {
        git -C $Root init | Out-Null
        Write-Ok "git repository initialised"
    }
} else {
    Write-Skip "git not found - skipping"
}

Write-Host ""
Write-Host "Sky scaffold complete: $Root" -ForegroundColor Green
Write-Host "Next: cd `"$Root`" and run the three verification commands from the chat." -ForegroundColor Green

param(
    [switch]$OneFile,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Create the Python virtual environment first."
}

Push-Location $Root
try {
    if (-not $SkipInstall) {
        & $Python -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install build dependencies."
        }
    }

    $env:TG_PIC_COLLECTOR_ONEFILE = if ($OneFile) { "1" } else { "0" }
    & $Python -m PyInstaller --noconfirm --clean TG-Pic-Collector.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    if ($OneFile) {
        Write-Host "Build complete: dist\TG Pic Collector.exe"
    } else {
        Write-Host "Build complete: dist\TG Pic Collector\TG Pic Collector.exe"
    }
}
finally {
    Remove-Item Env:\TG_PIC_COLLECTOR_ONEFILE -ErrorAction SilentlyContinue
    Pop-Location
}

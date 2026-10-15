# Run from PowerShell 7. Installs QASC into its own virtual environment.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create QASC virtual environment' }
    }
    & ./.venv/Scripts/python.exe -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'Could not install QASC' }
    Write-Host 'Ready: ./.venv/Scripts/qasc.exe doctor'
} finally { Pop-Location }

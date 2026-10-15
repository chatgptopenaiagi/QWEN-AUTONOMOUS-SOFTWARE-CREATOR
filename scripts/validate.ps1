$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $pythonCommand = if (Test-Path -LiteralPath '.venv/Scripts/python.exe') { './.venv/Scripts/python.exe' } else { 'python' }
    $previousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    try {
        & $pythonCommand -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw 'QASC validation failed' }
    } finally { $env:PYTHONPATH = $previousPythonPath }
} finally { Pop-Location }

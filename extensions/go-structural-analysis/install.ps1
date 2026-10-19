param([string]$Python = 'python', [switch]$SkipDependencies)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$workerRoot = Join-Path $env:LOCALAPPDATA 'GO Structural Analysis\solver-v0.1'
$pluginRoot = Join-Path $env:APPDATA 'ingetrazo\plugins\go_structural_analysis'
$venvPython = Join-Path $workerRoot 'Scripts\python.exe'
if (-not $SkipDependencies) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Get-Command uv -ErrorAction SilentlyContinue) { & uv venv $workerRoot --python 3.12 }
        else { & $Python -m venv $workerRoot }
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create solver venv' }
    }
    if (Get-Command uv -ErrorAction SilentlyContinue) { & uv pip install --python $venvPython -r (Join-Path $projectRoot 'requirements.txt') }
    else { & $venvPython -m pip install -r (Join-Path $projectRoot 'requirements.txt') }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install solver dependencies' }
}
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Solver runtime missing' }
New-Item -ItemType Directory -Path $pluginRoot -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'go_structural_analysis') -File -Filter '*.py' | Copy-Item -Destination $pluginRoot -Force
@{python=$venvPython; protocol=1} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $pluginRoot 'worker_config.json') -Encoding utf8
Write-Output "Installed GO Structural Analysis v0.2.4: $pluginRoot"
Write-Output "Solver runtime: $venvPython"
Write-Output 'Restart IngeTrazo to auto-load, then Extensions > GO Structural Analysis v0.2.4.'

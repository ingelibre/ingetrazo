param(
    [ValidateSet('Preflight','Install','Verify','Uninstall')][string]$Mode = 'Verify',
    [string]$InstallRoot = $PSScriptRoot,
    [string]$PluginRoot = (Join-Path $env:APPDATA 'ingetrazo\plugins\go_structural_analysis'),
    [switch]$Gui
)
$ErrorActionPreference = 'Stop'
$logRoot = $env:TEMP
try {
    $InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
    $PluginRoot = [IO.Path]::GetFullPath($PluginRoot)
    $manifestPath = Join-Path $InstallRoot 'installation.json'
    if ($Mode -in @('Preflight','Uninstall') -and (Test-Path -LiteralPath $manifestPath)) {
        $PluginRoot = [IO.Path]::GetFullPath((Get-Content -Raw -Encoding utf8 -LiteralPath $manifestPath | ConvertFrom-Json).plugin_root)
    }
    foreach ($root in @($InstallRoot,$PluginRoot)) {
        foreach ($protected in @($env:ProgramFiles,${env:ProgramFiles(x86)},$env:WINDIR)) {
            if ($protected -and ($root.Equals($protected,[StringComparison]::OrdinalIgnoreCase) -or $root.StartsWith($protected+'\',[StringComparison]::OrdinalIgnoreCase))) { throw 'Install only in your user folder, not Program Files or Windows.' }
        }
    }
    if (Test-Path -LiteralPath $InstallRoot) { $logRoot = $InstallRoot }
    $defaultPlugin = Join-Path $env:APPDATA 'ingetrazo\plugins\go_structural_analysis'
    if ($PluginRoot.Equals($defaultPlugin,[StringComparison]::OrdinalIgnoreCase) -and $Mode -in @('Preflight','Install','Uninstall')) {
        if (Get-Process -Name ingetrazo -ErrorAction SilentlyContinue) { throw 'Close IngeTrazo after saving your work, then run Setup again.' }
    }
    if ($Mode -eq 'Preflight') { exit 0 }
    $python = Join-Path $InstallRoot 'runtime\python.exe'
    $manifestPath = Join-Path $InstallRoot 'installation.json'
    if ($Mode -eq 'Uninstall') {
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw -Encoding utf8 -LiteralPath $manifestPath | ConvertFrom-Json
            $PluginRoot = [IO.Path]::GetFullPath($manifest.plugin_root)
            $config = Join-Path $PluginRoot 'worker_config.json'
            if (Test-Path -LiteralPath $config) {
                $worker = Get-Content -Raw -Encoding utf8 -LiteralPath $config | ConvertFrom-Json
                if ($worker.python -eq $python) {
                    # Only remove this install's known package files, never models or backups.
                    foreach ($fileName in $manifest.plugin_files) {
                        if ([IO.Path]::GetFileName($fileName) -ne $fileName) { throw 'Invalid installed-file manifest' }
                        $filePath = Join-Path $PluginRoot $fileName
                        if (Test-Path -LiteralPath $filePath) { Remove-Item -LiteralPath $filePath -Force }
                    }
                    Remove-Item -LiteralPath $config -Force
                }
            }
        }
        exit 0
    }
    if ($Mode -eq 'Install') {
        $package = Join-Path $InstallRoot 'plugin'
        if (-not (Test-Path -LiteralPath $python)) { throw 'Bundled solver runtime missing. Run Setup again.' }
        # Verify the bundled worker before touching an existing plugin.
        $precheck = & $python -I (Join-Path $InstallRoot 'healthcheck.py') $package $python 2>&1
        if ($LASTEXITCODE -ne 0) { throw ('Bundled Solver failed before plugin deployment: '+($precheck | Out-String)) }
        if (Test-Path -LiteralPath $PluginRoot) {
            $backupRoot = Join-Path $env:LOCALAPPDATA ('GO Structural Analysis\plugin-backups\'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            Copy-Item -LiteralPath $PluginRoot -Destination $backupRoot -Recurse
        }
        New-Item -ItemType Directory -Path $PluginRoot -Force | Out-Null
        $files = Get-ChildItem -LiteralPath $package -Filter '*.py' -File
        $files | Copy-Item -Destination $PluginRoot -Force
        @{ python=$python; protocol=1 } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PluginRoot 'worker_config.json') -Encoding utf8
        @{ version='0.2.4'; plugin_root=$PluginRoot; plugin_files=@($files.Name); runtime=$python } | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8
    } elseif (Test-Path -LiteralPath $manifestPath) {
        $PluginRoot = (Get-Content -Raw -Encoding utf8 -LiteralPath $manifestPath | ConvertFrom-Json).plugin_root
    }
    $output = & $python -I (Join-Path $InstallRoot 'healthcheck.py') $PluginRoot 2>&1
    $workerExitCode = $LASTEXITCODE
    $output | Set-Content -LiteralPath (Join-Path $InstallRoot 'solver-check.log') -Encoding utf8
    if ($workerExitCode -ne 0) { throw ('Solver verification failed. See solver-check.log. '+($output | Out-String)) }
    $result = ($output | Out-String) | ConvertFrom-Json
    if ($result.status -ne 'Passed') { throw 'Solver verification failed.' }
    if ($Gui) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show('Solver check passed. Open IngeTrazo > Extensions > GO Structural Analysis > Model > Engineering Examples / Benchmarks.','GO Structural Analysis') | Out-Null
    }
    Write-Output ($output | Out-String)
    exit 0
} catch {
    $message = $_.Exception.Message
    $message | Set-Content -LiteralPath (Join-Path $logRoot 'setup-error.log') -Encoding utf8
    if ($Gui) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($message,'GO Structural Analysis setup') | Out-Null
    }
    Write-Error $message
    exit 1
}

param([string]$SetupExe = (Join-Path $PSScriptRoot '..\dist\GO-Structural-Analysis-v0.2.4-Windows-x64-Setup.exe'))
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$testRoot=Join-Path $projectRoot ('artifacts\installer\test-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
$appRoot=Join-Path $testRoot ('installed app '+[string][char]0x0E44+[char]0x0E17+[char]0x0E22)
$pluginRoot=Join-Path $testRoot 'plugins\go_structural_analysis'
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
$checks=[Collections.Generic.List[object]]::new()
function Record([string]$Name,[bool]$Passed,[string]$Detail='') {
    $checks.Add(@{check=$Name;status=$(if($Passed){'Passed'}else{'Failed'});detail=$Detail})
    $checks | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $testRoot 'checks.json') -Encoding utf8
    if (-not $Passed) { throw "Check failed: $Name $Detail" }
}
function HashPlugin {
    $root=Join-Path $env:APPDATA 'ingetrazo\plugins\go_structural_analysis'
    $hashes=@{}
    Get-ChildItem -LiteralPath $root -File | ForEach-Object { $hashes[$_.Name]=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    return ($hashes | ConvertTo-Json -Compress)
}
function InstallTest {
    $arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR="'+$appRoot+'" /PluginDir="'+$pluginRoot+'" /LOG="'+(Join-Path $testRoot 'setup.log')+'"'
    $process=Start-Process -FilePath $SetupExe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    Record 'setup_executable_exit' ($process.ExitCode -eq 0) ('Exit '+$process.ExitCode)
}
$originalHash=HashPlugin
InstallTest
$python=Join-Path $appRoot 'runtime\python.exe'
Record 'runtime_installed' (Test-Path -LiteralPath $python)
$config=Get-Content -LiteralPath (Join-Path $pluginRoot 'worker_config.json') -Raw -Encoding utf8 | ConvertFrom-Json
Record 'worker_runtime_relocated' ($config.python -eq $python)
$health=Get-Content -LiteralPath (Join-Path $appRoot 'solver-check.log') -Raw -Encoding utf8 | ConvertFrom-Json
Record 'solver_healthcheck' ($health.status -eq 'Passed')
& $python -I (Join-Path $PSScriptRoot 'test_installer_worker.py') $pluginRoot (Join-Path $testRoot 'examples.json')
Record 'bundled_runtime_all_21_examples' ($LASTEXITCODE -eq 0)
$unrelated=Join-Path $pluginRoot 'user-note.txt'
'preserve this user file' | Set-Content -LiteralPath $unrelated
$modelPath=Join-Path $testRoot 'user-model.igz'
Copy-Item -LiteralPath (Join-Path $projectRoot 'artifacts\v0.1.3\benchmark-v0.1.3.igz') -Destination $modelPath
$modelHash=(Get-FileHash -LiteralPath $modelPath).Hash
$oldPluginHash=(Get-FileHash -LiteralPath (Join-Path $pluginRoot '__init__.py')).Hash
InstallTest
$backupRoot=Join-Path $env:LOCALAPPDATA 'GO Structural Analysis\plugin-backups'
$latest=Get-ChildItem -LiteralPath $backupRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
$saved=Join-Path $latest.FullName 'go_structural_analysis\__init__.py'
Record 'reinstall_backup' ((Test-Path -LiteralPath $saved) -and (Get-FileHash -LiteralPath $saved).Hash -eq $oldPluginHash)
$defaultPlugin=Join-Path $env:APPDATA 'ingetrazo\plugins\go_structural_analysis'
if (Get-Process -Name ingetrazo -ErrorAction SilentlyContinue) {
    $blockedRoot=Join-Path $testRoot 'blocked-install'
    $arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR="'+$blockedRoot+'" /LOG="'+(Join-Path $testRoot 'blocked.log')+'"'
    $process=Start-Process -FilePath $SetupExe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    Record 'running_host_install_blocked' ($process.ExitCode -ne 0 -and -not (Test-Path -LiteralPath (Join-Path $blockedRoot 'runtime\python.exe')))
}
$uninstaller=Join-Path $appRoot 'unins000.exe'
if (-not $appRoot.StartsWith($testRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe uninstall test path' }
$process=Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -WindowStyle Hidden -Wait -PassThru
Record 'uninstall_exit' ($process.ExitCode -eq 0)
Record 'owned_plugin_removed' (-not (Test-Path -LiteralPath (Join-Path $pluginRoot '__init__.py')))
Record 'runtime_removed' (-not (Test-Path -LiteralPath $python))
Record 'unrelated_file_preserved' (Test-Path -LiteralPath $unrelated)
Record 'model_preserved' ((Get-FileHash -LiteralPath $modelPath).Hash -eq $modelHash)
Record 'original_live_plugin_unchanged' ((HashPlugin) -eq $originalHash)
$summary=@{date=(Get-Date -Format o);setup_file=[IO.Path]::GetFullPath($SetupExe);setup_sha256=(Get-FileHash -LiteralPath $SetupExe -Algorithm SHA256).Hash;test_root=$testRoot;passed=@($checks|Where-Object status -eq 'Passed').Count;failed=@($checks|Where-Object status -eq 'Failed').Count;checks=$checks;not_tested=@('Clean Windows VM with no Python installed','Interactive wizard clicks','Cold IngeTrazo restart after installing Setup','Windows code signing/SmartScreen reputation')}
$summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $projectRoot 'artifacts\installer\test-results.json') -Encoding utf8
Write-Output ([PSCustomObject]$summary | Select-Object passed,failed,test_root | ConvertTo-Json)

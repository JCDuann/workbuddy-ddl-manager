param([string]$WorkspacePath = '', [string]$WorkBuddyHome = '', [string]$PythonPath = '', [string]$NodePath = '', [switch]$Fresh)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
if (-not $WorkBuddyHome) { $WorkBuddyHome = Join-Path $env:USERPROFILE '.workbuddy' }
if (-not $WorkspacePath) { $WorkspacePath = Join-Path $env:USERPROFILE 'WorkBuddy\Claw' }
if (-not $PythonPath) {
    $ddlDefaultPython = Join-Path $WorkBuddyHome 'binaries\python\envs\default\Scripts\python.exe'
    if (Test-Path -LiteralPath $ddlDefaultPython) { $PythonPath = $ddlDefaultPython }
    else { $PythonPath = (Get-ChildItem -LiteralPath (Join-Path $WorkBuddyHome 'binaries\python') -Filter python.exe -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName }
}
if (-not $NodePath) {
    $NodePath = (Get-ChildItem -LiteralPath (Join-Path $WorkBuddyHome 'binaries\node\versions') -Filter node.exe -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
if (-not $PythonPath -or -not $NodePath) {
    Write-Host 'Python or Node was not found in WorkBuddy. Open WorkBuddy once and ask it to initialize its local Python/Node environment, then retry.'
    Write-Host 'Advanced: setup.ps1 -PythonPath <python.exe> -NodePath <node.exe> -WorkspacePath <workspace>'
    exit 1
}
Write-Host ('Installing into: ' + $WorkspacePath)
$ddlInstallArgs = @((Join-Path $PSScriptRoot 'deploy.py'), '--workspace', $WorkspacePath, '--workbuddy-home', $WorkBuddyHome, '--python', $PythonPath, '--node', $NodePath)
if ($Fresh) { $ddlInstallArgs += '--fresh' }
if (-not (Get-Process -Name WorkBuddy -ErrorAction SilentlyContinue)) { $ddlInstallArgs += '--register-tasks' }
& $PythonPath @ddlInstallArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Installation complete. Open WorkBuddy using the workspace above. Connect QQ, send your bot one message, then run qq-setup.cmd.'
Write-Host 'If native tasks were not registered, close WorkBuddy and run setup.cmd again, or create the 3 tasks described in ddl-manager.'

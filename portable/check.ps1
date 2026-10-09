$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$ddlInstallPath = Join-Path $PSScriptRoot 'installed.json'
if (-not (Test-Path -LiteralPath $ddlInstallPath)) { Write-Host 'Run setup.cmd first.'; exit 1 }
$ddlInstall = Get-Content -LiteralPath $ddlInstallPath -Encoding UTF8 -Raw | ConvertFrom-Json
Push-Location -LiteralPath $ddlInstall.deployment
try {
    & $ddlInstall.python -m unittest test_ddl test_cards
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $ddlInstall.python (Join-Path $ddlInstall.deployment 'ddl.py') status
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $ddlInstall.python (Join-Path $ddlInstall.deployment 'qq_message.py') status
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $ddlInstall.node --input-type=module -e "await import('./runtime/node_modules/@tencent-connect/qqbot-nodejs/dist/index.js'); console.log('QQ SDK load: OK');"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
Write-Host 'Local checks passed. Scheduled execution and QQ delivery still require actual run/receipt checks.'

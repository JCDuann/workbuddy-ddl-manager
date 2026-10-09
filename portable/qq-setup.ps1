param([string]$OpenId = '')
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$ddlInstallPath = Join-Path $PSScriptRoot 'installed.json'
if (-not (Test-Path -LiteralPath $ddlInstallPath)) { Write-Host 'Run setup.cmd first.'; exit 1 }
$ddlInstall = Get-Content -LiteralPath $ddlInstallPath -Encoding UTF8 -Raw | ConvertFrom-Json
Write-Host 'This will configure the local QQ sender and send ONE deployment test card to your verified QQ private chat.'
Write-Host 'If WorkBuddy credentials are encrypted, a local authorization QR image will open. Choose the same bot.'
$ddlQqArgs = @((Join-Path $PSScriptRoot 'configure_qq.py'), '--deployment', $ddlInstall.deployment, '--test')
if ($OpenId) { $ddlQqArgs += @('--openid', $OpenId) }
& $ddlInstall.python @ddlQqArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Check the test card in QQ, then send a query to the bot to verify inbound replies as well.'

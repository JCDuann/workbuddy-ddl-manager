param([string]$Destination = '')
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$ddlInstallPath = Join-Path $PSScriptRoot 'installed.json'
if (-not (Test-Path -LiteralPath $ddlInstallPath)) { Write-Host 'Run setup.cmd first.'; exit 1 }
$ddlInstall = Get-Content -LiteralPath $ddlInstallPath -Encoding UTF8 -Raw | ConvertFrom-Json
if (-not $Destination) { $Destination = Join-Path $PSScriptRoot ('DDL-data-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.sqlite3') }
$ddlExportCode = 'import sqlite3,sys; a=sqlite3.connect(sys.argv[1]); b=sqlite3.connect(sys.argv[2]); a.backup(b); b.close(); a.close(); print("Consistent database export complete.")'
& $ddlInstall.python -c $ddlExportCode (Join-Path $ddlInstall.deployment 'data\ddl.sqlite3') $Destination
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host ('Saved: ' + $Destination)

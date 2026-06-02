# deploy.ps1 — copy repo -> home per sync-manifest.txt
param([switch]$WhatIf)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$manifest = Join-Path $repoRoot 'sync-manifest.txt'
$xf = @('*.pyc','*.bak','settings.local.json','auth.json','oauth_creds.json','google_accounts.json','*.sqlite','*.sqlite-shm','*.sqlite-wal','history.jsonl','*.log','installation_id')
$xd = @('__pycache__','logs','sessions','tmp','.git')

foreach ($line in Get-Content $manifest) {
  $t = $line.Trim()
  if (-not $t -or $t.StartsWith('#')) { continue }
  $parts = $t -split '\|', 2
  $repoRel = $parts[0].Trim()
  $homePath = ($parts[1].Trim()) -replace '^~', $HOME
  $src = Join-Path $repoRoot $repoRel
  if ($repoRel.EndsWith('/')) {
    if ($WhatIf) { Write-Host "[deploy] DIR  $src -> $homePath"; continue }
    robocopy $src $homePath /E /XD $xd /XF $xf /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for $src" }
  } else {
    if ($WhatIf) { Write-Host "[deploy] FILE $src -> $homePath"; continue }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $homePath) | Out-Null
    Copy-Item -Force $src $homePath
  }
}
Write-Host "deploy complete."

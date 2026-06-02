# capture.ps1 — copy home -> repo per sync-manifest.txt (excludes secrets/caches)
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
  $dst = Join-Path $repoRoot $repoRel
  if ($repoRel.EndsWith('/')) {
    if ($WhatIf) { Write-Host "[capture] DIR  $homePath -> $dst"; continue }
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    robocopy $homePath $dst /E /XD $xd /XF $xf /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) for $homePath" }
  } else {
    if (-not (Test-Path $homePath)) { Write-Host "[capture] SKIP (missing) $homePath"; continue }
    if ($WhatIf) { Write-Host "[capture] FILE $homePath -> $dst"; continue }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    Copy-Item -Force $homePath $dst
  }
}
Write-Host "capture complete."

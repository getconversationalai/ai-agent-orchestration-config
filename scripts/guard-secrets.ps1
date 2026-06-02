# guard-secrets.ps1 — scan files for secret-SHAPED values. Exit 1 if any found.
# Usage: guard-secrets.ps1 [-All]   (default: scans git staged files)
# Patterns are assembled from fragments so this file holds no key-shaped literal.
param([switch]$All)
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$aws = 'A' + 'KIA[0-9A-Z]{16}'
$skl = 'sk_' + 'live_[A-Za-z0-9]{8,}'
$skt = 'sk_' + 'test_[A-Za-z0-9]{8,}'
$ght = 'gh' + '[posru]_[A-Za-z0-9]{20,}'
$patterns = @(
  $aws, $skl, $skt, $ght,
  '-----BEGIN [A-Z ]*PRIVATE KEY-----',
  'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
  'postgres(ql)?://[^\s:@/]+:[^\s@/]+@'
)
if ($All) { $files = git ls-files } else { $files = git diff --cached --name-only }
$bad = $false
foreach ($f in $files) {
  if (-not (Test-Path $f)) { continue }
  foreach ($pat in $patterns) {
    $hit = Select-String -Path $f -Pattern $pat -AllMatches -ErrorAction SilentlyContinue
    if ($hit) { $bad = $true; Write-Host "SECRET? $f matches /$pat/" -ForegroundColor Red }
  }
}
if ($bad) { Write-Host "guard-secrets: BLOCKED - secret-shaped content found." -ForegroundColor Red; exit 1 }
Write-Host "guard-secrets: clean."; exit 0

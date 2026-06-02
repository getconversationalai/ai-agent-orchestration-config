# install-hooks.ps1 — install guard-secrets as the git pre-commit hook
$repoRoot = Split-Path -Parent $PSScriptRoot
$hookDir = Join-Path $repoRoot '.git/hooks'
New-Item -ItemType Directory -Force -Path $hookDir | Out-Null
$hook = @'
#!/bin/sh
powershell -NoProfile -File scripts/guard-secrets.ps1 || {
  echo "Commit blocked by guard-secrets.ps1"; exit 1; }
'@
Set-Content -Path (Join-Path $hookDir 'pre-commit') -Value $hook -NoNewline -Encoding ASCII
Write-Host "pre-commit hook installed."

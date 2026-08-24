New-Item -ItemType Directory -Force -Path backups | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$file = "backups\sae_cdmx_$stamp.dump"
cmd /c "docker compose exec -T db pg_dump -U postgres -d sae_cdmx -Fc > $file"
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el backup" }
Write-Host "Backup creado: $file"

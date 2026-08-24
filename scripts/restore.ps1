param([Parameter(Mandatory=$true)][string]$File)
if (-not (Test-Path $File)) { throw "No existe: $File" }
cmd /c "type \"$File\" | docker compose exec -T db pg_restore -U postgres -d sae_cdmx --clean --if-exists --no-owner"
if ($LASTEXITCODE -ne 0) { throw "No se pudo restaurar el backup" }
Write-Host "Restauración terminada."

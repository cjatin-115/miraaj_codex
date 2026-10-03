$ErrorActionPreference = "Stop"
docker compose up -d postgres redis
if (!(Test-Path .env)) { Copy-Item .env.example .env }
Write-Host "Dependencies are starting. In separate terminals run:"
Write-Host "  python -m uvicorn miraaj_api.main:app --reload --app-dir apps/api/src"
Write-Host "  python workers/video-worker/main.py"
Write-Host "  npm run dev:web"

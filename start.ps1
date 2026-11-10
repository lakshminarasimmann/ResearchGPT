<#
.SYNOPSIS
    Starts ResearchGPT: the FastAPI backend and the Vite frontend.

.DESCRIPTION
    Checks that Ollama is reachable and the configured model is present, then
    launches each server in its own PowerShell window.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -ApiOnly
#>
param(
    [switch]$ApiOnly,
    [switch]$UiOnly
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Read-EnvValue([string]$name, [string]$fallback) {
    $envFile = Join-Path $root '.env'
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match "^\s*$name\s*=\s*(.+?)\s*$") { return $Matches[1] }
        }
    }
    return $fallback
}

$ollamaUrl = Read-EnvValue 'RAG_OLLAMA_BASE_URL' 'http://localhost:11434'
$model     = Read-EnvValue 'RAG_OLLAMA_MODEL'    'mistral:7b'
$apiPort   = Read-EnvValue 'RAG_API_PORT'        '8001'

# ── Preflight: is the local model actually available? ────────────────────────
if (-not $UiOnly) {
    Write-Host "Checking Ollama at $ollamaUrl ..." -ForegroundColor Cyan
    try {
        $tags = Invoke-RestMethod -Uri "$ollamaUrl/api/tags" -TimeoutSec 5
        $names = $tags.models | ForEach-Object { $_.name }
        if ($names -contains $model) {
            Write-Host "  OK - $model is available." -ForegroundColor Green
        } else {
            Write-Warning "  $model is not installed. Run: ollama pull $model"
            Write-Host   "  Installed: $($names -join ', ')"
        }
    } catch {
        Write-Warning "  Could not reach Ollama. Start it with 'ollama serve'."
        Write-Host   "  (Or set RAG_LLM_PROVIDER=openai in .env to use a remote API.)"
    }
}

# ── Launch ───────────────────────────────────────────────────────────────────
if (-not $UiOnly) {
    Write-Host "Starting API on http://127.0.0.1:$apiPort ..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$root'; python -m uvicorn api.main:app --port $apiPort"
    )
}

if (-not $ApiOnly) {
    if (-not (Test-Path (Join-Path $root 'frontend/node_modules'))) {
        Write-Host "Installing frontend dependencies ..." -ForegroundColor Cyan
        npm --prefix (Join-Path $root 'frontend') install
    }
    Write-Host "Starting UI on http://localhost:5173 ..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$root'; npm --prefix frontend run dev"
    )
}

Write-Host ""
Write-Host "ResearchGPT is starting. Open http://localhost:5173" -ForegroundColor Green

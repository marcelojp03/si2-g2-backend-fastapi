# SI2 SIA FastAPI - Deploy to ECR
# Uso: .\deploy-to-ecr.ps1

param(
    [string]$ImageTag = "latest"
)

Write-Host "Verificando Docker..." -ForegroundColor Cyan

# Verificar si Docker esta corriendo
$dockerRunning = $false
try {
    docker ps > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        $dockerRunning = $true
    }
} catch {}

if (-not $dockerRunning) {
    Write-Host "Docker Desktop no esta corriendo" -ForegroundColor Yellow
    Write-Host "Iniciando Docker Desktop..." -ForegroundColor Cyan

    Start-Process "Docker Desktop" -WindowStyle Hidden

    Write-Host "Esperando a que Docker inicie..." -ForegroundColor Yellow
    $timeout = 60
    $elapsed = 0

    while (-not $dockerRunning -and $elapsed -lt $timeout) {
        Start-Sleep -Seconds 5
        $elapsed += 5
        try {
            docker ps > $null 2>&1
            if ($LASTEXITCODE -eq 0) {
                $dockerRunning = $true
                break
            }
        } catch {}
        Write-Host "." -NoNewline -ForegroundColor Gray
    }

    Write-Host ""

    if (-not $dockerRunning) {
        Write-Host "ERROR: Docker no pudo iniciarse automaticamente" -ForegroundColor Red
        Write-Host "Por favor:" -ForegroundColor Yellow
        Write-Host "   1. Abre Docker Desktop manualmente" -ForegroundColor White
        Write-Host "   2. Espera a que termine de cargar" -ForegroundColor White
        Write-Host "   3. Ejecuta este script de nuevo" -ForegroundColor White
        exit 1
    }

    Write-Host "OK: Docker Desktop iniciado" -ForegroundColor Green
}

# Variables ECR
$AWS_REGION = "us-east-1"
$AWS_ACCOUNT_ID = "851725478821"
$ECR_REPO_NAME = "si2-sia-fastapi"
$ECR_URI = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME"

# Directorio raiz del proyecto FastAPI (dos niveles arriba de scripts/deploy/)
$PROJECT_ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Write-Host "Directorio del proyecto: $PROJECT_ROOT" -ForegroundColor Gray

Write-Host "`nConstruyendo imagen Docker..." -ForegroundColor Cyan
docker build -t "${ECR_REPO_NAME}:${ImageTag}" $PROJECT_ROOT

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Error construyendo imagen" -ForegroundColor Red
    exit 1
}

Write-Host "Autenticando con ECR..." -ForegroundColor Cyan
$loginPassword = aws ecr get-login-password --region $AWS_REGION
$loginPassword | docker login --username AWS --password-stdin $ECR_URI

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Error autenticando con ECR" -ForegroundColor Red
    exit 1
}

Write-Host "Etiquetando imagen..." -ForegroundColor Cyan
docker tag "${ECR_REPO_NAME}:${ImageTag}" "${ECR_URI}:${ImageTag}"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Error etiquetando imagen" -ForegroundColor Red
    exit 1
}

Write-Host "Subiendo imagen a ECR..." -ForegroundColor Cyan
docker push "${ECR_URI}:${ImageTag}"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nOK: Imagen subida exitosamente!" -ForegroundColor Green
    Write-Host "ECR URI: ${ECR_URI}:${ImageTag}" -ForegroundColor Cyan
    Write-Host "`nProximo paso: Desplegar en App Runner" -ForegroundColor Yellow
    Write-Host "   - Ve a AWS Console -> App Runner" -ForegroundColor White
    Write-Host "   - Selecciona 'Deploy' en tu servicio si2-sia-fastapi" -ForegroundColor White
} else {
    Write-Host "`nERROR: Error subiendo imagen" -ForegroundColor Red
    exit 1
}

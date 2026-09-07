param()

$ErrorActionPreference = "Stop"

$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Backend = Join-Path $RepoPath "apps\platform-web\backend"
$Frontend = Join-Path $RepoPath "apps\platform-web\frontend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$ControlScript = Join-Path $PSScriptRoot "DBI-ControlCenter.ps1"

$RuntimeDir = Join-Path $env:LOCALAPPDATA "DALGORO\DBI"
$LogsDir = Join-Path $RuntimeDir "logs"
$ConfigPath = Join-Path $RuntimeDir "local-ops.json"
$ApiPasswordPath = Join-Path $RuntimeDir "dbi-api-password.xml"
$JwtSecretPath = Join-Path $RuntimeDir "jwt-secret.xml"
$AuthDb = Join-Path $RuntimeDir "dbi_auth.sqlite3"
$AuthEmail = "dbi.local@dalgoro.ec"
$ContainerName = "dbi-postgis-development"
$CloudflaredDir = Join-Path $env:USERPROFILE "cloudflared"
$CloudflaredExe = Join-Path $CloudflaredDir "cloudflared.exe"

function Wait-DockerReady {
    try {
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
    } catch {}

    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerDesktop)) {
        throw "Docker Desktop no esta instalado en la ruta esperada."
    }
    Start-Process -FilePath $dockerDesktop | Out-Null

    $deadline = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep -Seconds 2
        try {
            & docker info *> $null
            if ($LASTEXITCODE -eq 0) { return }
        } catch {}
    } while ((Get-Date) -lt $deadline)

    throw "Docker Desktop no quedo listo en 120 segundos."
}

function Save-ProtectedSecret([string]$PlainText, [string]$Path) {
    $secure = ConvertTo-SecureString $PlainText -AsPlainText -Force
    $secure | Export-Clixml -Path $Path
}

function New-Shortcut(
    [string]$ShortcutPath,
    [string]$Arguments,
    [string]$Description
) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $RepoPath
    $shortcut.Description = $Description
    $shortcut.Save()
}

Write-Host "DBI Local Ops - instalacion inicial"
Write-Host "Repositorio: $RepoPath"

if (-not (Test-Path $Python)) {
    throw "No existe el entorno virtual backend: $Python"
}
if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    throw "No se encontro el frontend esperado: $Frontend"
}
if (-not (Test-Path $ControlScript)) {
    throw "No se encontro DBI-ControlCenter.ps1"
}

New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogsDir, $CloudflaredDir | Out-Null

Write-Host "1/7 Verificando Docker/PostGIS..."
Wait-DockerReady

$knownContainer = (& docker ps -a --filter "name=^/$ContainerName$" --format "{{.Names}}" 2>$null | Select-Object -First 1)
if ($knownContainer -ne $ContainerName) {
    throw "No existe $ContainerName. Debe aprovisionarse primero la base DBI local."
}
$running = (& docker inspect -f "{{.State.Running}}" $ContainerName 2>$null | Select-Object -First 1)
if ($running -ne "true") {
    & docker start $ContainerName *> $null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar $ContainerName" }
}

Write-Host "2/7 Preparando cloudflared..."
if (-not (Test-Path $CloudflaredExe)) {
    Invoke-WebRequest `
        -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
        -OutFile $CloudflaredExe
}
& $CloudflaredExe --version
if ($LASTEXITCODE -ne 0) { throw "cloudflared no funciona correctamente." }

Write-Host "3/7 Protegiendo credenciales DBI locales con DPAPI..."
$apiPassword = [guid]::NewGuid().ToString("N")
$sql = "ALTER ROLE dbi_development_api WITH PASSWORD '$apiPassword';"
$sql | docker exec -i $ContainerName psql -U postgres -d dbi_development -v ON_ERROR_STOP=1 *> $null
if ($LASTEXITCODE -ne 0) { throw "No se pudo actualizar la credencial del rol DBI API." }
Save-ProtectedSecret $apiPassword $ApiPasswordPath
$apiPassword = $null

$jwtSecret = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
Save-ProtectedSecret $jwtSecret $JwtSecretPath
$env:JWT_SECRET = $jwtSecret
$jwtSecret = $null

Write-Host "4/7 Creando autenticacion local persistente..."
$loginSecure = Read-Host "Cree la contrasena LOCAL que usara para entrar a DBI" -AsSecureString
$loginPlain = [System.Net.NetworkCredential]::new("", $loginSecure).Password
if ([string]::IsNullOrWhiteSpace($loginPlain) -or $loginPlain.Length -lt 8) {
    throw "La contrasena local debe tener al menos 8 caracteres."
}

$authDbUrl = $AuthDb.Replace("\", "/")
$env:DATABASE_URL = "sqlite+pysqlite:///$authDbUrl"
$env:DBI_LOCAL_LOGIN_PASSWORD = $loginPlain
$env:DBI_LOCAL_LOGIN_EMAIL = $AuthEmail
Push-Location $Backend
try {
@'
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.user import User
from app.core.security import get_password_hash

engine = create_engine(os.environ["DATABASE_URL"])
Base.metadata.create_all(engine)

email = os.environ["DBI_LOCAL_LOGIN_EMAIL"]
password = os.environ["DBI_LOCAL_LOGIN_PASSWORD"]

with Session(engine) as session:
    user = session.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            full_name="DALGORO DBI Local",
            email=email,
            hashed_password=get_password_hash(password),
            role="ADMIN",
            is_active=True,
            is_deleted=False,
        )
        session.add(user)
    else:
        user.hashed_password = get_password_hash(password)
        user.role = "ADMIN"
        user.is_active = True
        user.is_deleted = False
    session.commit()
    session.refresh(user)
    print(f"local_login=READY user_id={user.id} email={user.email}")
'@ | & $Python -
    if ($LASTEXITCODE -ne 0) { throw "No se pudo inicializar la autenticacion SQLite local." }
} finally {
    Pop-Location
    Remove-Item Env:DATABASE_URL, Env:DBI_LOCAL_LOGIN_PASSWORD, Env:DBI_LOCAL_LOGIN_EMAIL, Env:JWT_SECRET -ErrorAction SilentlyContinue
    $loginPlain = $null
    $loginSecure = $null
}

Write-Host "5/7 Guardando configuracion local sin secretos..."
$config = [ordered]@{
    repo_path = $RepoPath
    container_name = $ContainerName
    backend_port = 8000
    frontend_port = 4173
    cloudflared_exe = $CloudflaredExe
    auth_db = $AuthDb
    auth_email = $AuthEmail
    tunnel_mode = "quick"
    tunnel_name = ""
    public_hostname = ""
}
$config | ConvertTo-Json -Depth 4 | Set-Content -Path $ConfigPath -Encoding UTF8

Write-Host "6/7 Creando inicio automatico y acceso al Control Center..."
$startupDir = [Environment]::GetFolderPath("Startup")
$desktopDir = [Environment]::GetFolderPath("Desktop")
$startupShortcut = Join-Path $startupDir "DALGORO DBI - Autostart.lnk"
$controlShortcut = Join-Path $desktopDir "DALGORO DBI Control Center.lnk"

$quotedControl = '"' + $ControlScript + '"'
New-Shortcut `
    -ShortcutPath $startupShortcut `
    -Arguments "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $quotedControl -Action Start" `
    -Description "Inicia DALGORO Banana Intelligence al iniciar sesion en Windows"

New-Shortcut `
    -ShortcutPath $controlShortcut `
    -Arguments "-NoProfile -ExecutionPolicy Bypass -File $quotedControl -Action UI" `
    -Description "Control Center de DALGORO Banana Intelligence"

Write-Host "7/7 Iniciando DBI ahora..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ControlScript -Action Start
if ($LASTEXITCODE -ne 0) { throw "La instalacion termino, pero DBI no pudo arrancar. Abra el Control Center y revise los logs." }

Write-Host ""
Write-Host "installation=READY"
Write-Host "login_email=$AuthEmail"
Write-Host "control_center=$controlShortcut"
Write-Host "autostart=$startupShortcut"
Write-Host ""
Write-Host "IMPORTANTE: Quick Tunnel es solo temporal. Para uso de campo estable configure un Cloudflare Named Tunnel con hostname fijo."

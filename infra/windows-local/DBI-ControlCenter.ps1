param(
    [ValidateSet("UI", "Start", "Stop", "Restart", "Status", "Open")]
    [string]$Action = "UI"
)

$ErrorActionPreference = "Stop"

$RuntimeDir = Join-Path $env:LOCALAPPDATA "DALGORO\DBI"
$ConfigPath = Join-Path $RuntimeDir "local-ops.json"
$StatePath = Join-Path $RuntimeDir "runtime-state.json"
$LogsDir = Join-Path $RuntimeDir "logs"
$ApiPasswordPath = Join-Path $RuntimeDir "dbi-api-password.xml"
$JwtSecretPath = Join-Path $RuntimeDir "jwt-secret.xml"

function Ensure-DbiRuntimeDirectories {
    New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogsDir | Out-Null
}

function Get-DbiConfig {
    if (-not (Test-Path $ConfigPath)) {
        throw "DBI Local Ops no esta instalado. Ejecute primero Install-DBI-ControlCenter.ps1."
    }
    return Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
}

function Get-DbiPlainSecret([string]$Path) {
    if (-not (Test-Path $Path)) {
        throw "Falta un secreto local protegido: $Path"
    }
    $secure = Import-Clixml -Path $Path
    return [System.Net.NetworkCredential]::new("", $secure).Password
}

function Test-DbiPort([int]$Port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Test-DbiHttp([string]$Url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 4
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Wait-DbiCondition([scriptblock]$Condition, [int]$TimeoutSeconds, [string]$FailureMessage) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 750
    } while ((Get-Date) -lt $deadline)
    throw $FailureMessage
}

function Get-DbiState {
    if (-not (Test-Path $StatePath)) { return $null }
    try { return Get-Content -Raw -Path $StatePath | ConvertFrom-Json } catch { return $null }
}

function Save-DbiState($State) {
    $State | ConvertTo-Json -Depth 6 | Set-Content -Path $StatePath -Encoding UTF8
}

function Test-DbiProcess([int]$ProcessId) {
    if ($ProcessId -le 0) { return $false }
    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Stop-DbiProcessTree([int]$ProcessId) {
    if (-not (Test-DbiProcess $ProcessId)) { return }
    & taskkill.exe /PID $ProcessId /T /F *> $null
}

function Ensure-DockerReady($Config) {
    $dockerReady = $false
    try {
        & docker info *> $null
        $dockerReady = ($LASTEXITCODE -eq 0)
    } catch {}

    if (-not $dockerReady) {
        $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        if (-not (Test-Path $dockerDesktop)) {
            throw "Docker Desktop no esta disponible en la ruta esperada."
        }
        Start-Process -FilePath $dockerDesktop | Out-Null
        Wait-DbiCondition -TimeoutSeconds 120 -FailureMessage "Docker Desktop no quedo listo en 120 segundos." -Condition {
            try {
                & docker info *> $null
                return ($LASTEXITCODE -eq 0)
            } catch { return $false }
        }
    }

    $containerName = [string]$Config.container_name
    $knownContainer = (& docker ps -a --filter "name=^/$containerName$" --format "{{.Names}}" 2>$null | Select-Object -First 1)
    if ($knownContainer -ne $containerName) {
        throw "No existe el contenedor local requerido: $containerName"
    }

    $running = (& docker inspect -f "{{.State.Running}}" $containerName 2>$null | Select-Object -First 1)
    if ($running -ne "true") {
        & docker start $containerName *> $null
        if ($LASTEXITCODE -ne 0) { throw "No se pudo iniciar $containerName" }
    }
}

function Get-LatestFrontendSourceTime([string]$Frontend) {
    $paths = @(
        (Join-Path $Frontend "src"),
        (Join-Path $Frontend "public"),
        (Join-Path $Frontend "package.json"),
        (Join-Path $Frontend "package-lock.json"),
        (Join-Path $Frontend "vite.config.ts")
    ) | Where-Object { Test-Path $_ }

    $items = foreach ($path in $paths) {
        if ((Get-Item $path).PSIsContainer) {
            Get-ChildItem -Path $path -Recurse -File -ErrorAction SilentlyContinue
        } else {
            Get-Item $path
        }
    }
    return ($items | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
}

function Ensure-FrontendBuild($Config) {
    $frontend = Join-Path ([string]$Config.repo_path) "apps\platform-web\frontend"
    $distIndex = Join-Path $frontend "dist\index.html"
    $needsBuild = -not (Test-Path $distIndex)

    if (-not $needsBuild) {
        $latestSource = Get-LatestFrontendSourceTime $frontend
        $distTime = (Get-Item $distIndex).LastWriteTimeUtc
        $needsBuild = $latestSource -gt $distTime
    }

    if (-not $needsBuild) { return }

    $buildOut = Join-Path $LogsDir "frontend-build.out.log"
    $buildErr = Join-Path $LogsDir "frontend-build.err.log"
    Remove-Item $buildOut, $buildErr -Force -ErrorAction SilentlyContinue

    $build = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run build" `
        -WorkingDirectory $frontend -WindowStyle Hidden -Wait -PassThru `
        -RedirectStandardOutput $buildOut -RedirectStandardError $buildErr
    if ($build.ExitCode -ne 0) {
        throw "Fallo npm run build. Revise $buildErr"
    }
}

function Start-DbiTunnel($Config) {
    $state = Get-DbiState
    if ($state -and $state.tunnel_pid -and (Test-DbiProcess ([int]$state.tunnel_pid))) {
        return [pscustomobject]@{
            ProcessId = [int]$state.tunnel_pid
            PublicUrl = [string]$state.public_url
            PublicHost = ([uri][string]$state.public_url).Host
        }
    }

    $cloudflared = [string]$Config.cloudflared_exe
    if (-not (Test-Path $cloudflared)) {
        throw "cloudflared no existe en $cloudflared"
    }

    $outLog = Join-Path $LogsDir "cloudflared.out.log"
    $errLog = Join-Path $LogsDir "cloudflared.err.log"
    Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue

    $mode = [string]$Config.tunnel_mode
    if ($mode -eq "named") {
        if (-not $Config.tunnel_name -or -not $Config.public_hostname) {
            throw "El modo named requiere tunnel_name y public_hostname en local-ops.json."
        }
        $arguments = @("tunnel", "run", [string]$Config.tunnel_name)
        $publicUrl = "https://$([string]$Config.public_hostname)"
    } else {
        $arguments = @("tunnel", "--url", "http://127.0.0.1:$([int]$Config.frontend_port)")
        $publicUrl = $null
    }

    $process = Start-Process -FilePath $cloudflared -ArgumentList $arguments `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog

    if ($mode -ne "named") {
        Wait-DbiCondition -TimeoutSeconds 40 -FailureMessage "Cloudflare no entrego una URL Quick Tunnel. Revise $errLog" -Condition {
            $text = ""
            if (Test-Path $outLog) { $text += (Get-Content -Raw $outLog -ErrorAction SilentlyContinue) }
            if (Test-Path $errLog) { $text += "`n" + (Get-Content -Raw $errLog -ErrorAction SilentlyContinue) }
            $match = [regex]::Match($text, "https://[a-z0-9-]+\.trycloudflare\.com")
            if ($match.Success) {
                $script:QuickTunnelUrl = $match.Value
                return $true
            }
            return $false
        }
        $publicUrl = $script:QuickTunnelUrl
    }

    return [pscustomobject]@{
        ProcessId = $process.Id
        PublicUrl = $publicUrl
        PublicHost = ([uri]$publicUrl).Host
    }
}

function Start-DbiBackend($Config) {
    $backendPort = [int]$Config.backend_port
    if (Test-DbiPort $backendPort) { return $null }

    $repo = [string]$Config.repo_path
    $backend = Join-Path $repo "apps\platform-web\backend"
    $python = Join-Path $backend ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) { throw "No existe el venv backend: $python" }

    $dbiPassword = Get-DbiPlainSecret $ApiPasswordPath
    $jwtSecret = Get-DbiPlainSecret $JwtSecretPath
    $authDb = ([string]$Config.auth_db).Replace("\", "/")

    $env:DATABASE_URL = "sqlite+pysqlite:///$authDb"
    $env:JWT_SECRET = $jwtSecret
    $env:DBI_ENVIRONMENT = "development"
    $env:DBI_DATABASE_URL = "postgresql+psycopg://dbi_development_api:$dbiPassword@127.0.0.1:55432/dbi_development"
    $env:PYTHONUTF8 = "1"

    try {
        $outLog = Join-Path $LogsDir "backend.out.log"
        $errLog = Join-Path $LogsDir "backend.err.log"
        Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue
        $process = Start-Process -FilePath $python `
            -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$backendPort" `
            -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    } finally {
        Remove-Item Env:DATABASE_URL, Env:JWT_SECRET, Env:DBI_ENVIRONMENT, Env:DBI_DATABASE_URL, Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    }

    Wait-DbiCondition -TimeoutSeconds 35 -FailureMessage "FastAPI no respondio. Revise $errLog" -Condition {
        Test-DbiHttp "http://127.0.0.1:$backendPort/api/v1/health"
    }
    return $process
}

function Start-DbiFrontend($Config, [string]$AllowedHost) {
    $frontendPort = [int]$Config.frontend_port
    if (Test-DbiPort $frontendPort) { return $null }

    Ensure-FrontendBuild $Config
    $frontend = Join-Path ([string]$Config.repo_path) "apps\platform-web\frontend"

    $env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = $AllowedHost
    try {
        $outLog = Join-Path $LogsDir "frontend.out.log"
        $errLog = Join-Path $LogsDir "frontend.err.log"
        Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue
        $command = "npm run preview -- --host 127.0.0.1 --port $frontendPort"
        $process = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $command `
            -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    } finally {
        Remove-Item Env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS -ErrorAction SilentlyContinue
    }

    Wait-DbiCondition -TimeoutSeconds 25 -FailureMessage "Vite Preview no respondio. Revise $errLog" -Condition {
        Test-DbiHttp "http://127.0.0.1:$frontendPort/api/v1/health"
    }
    return $process
}

function Start-DbiStack {
    Ensure-DbiRuntimeDirectories
    $config = Get-DbiConfig
    Ensure-DockerReady $config

    $backend = Start-DbiBackend $config
    $tunnel = Start-DbiTunnel $config
    $frontend = Start-DbiFrontend $config $tunnel.PublicHost

    $oldState = Get-DbiState
    $state = [ordered]@{
        started_at = (Get-Date).ToString("o")
        backend_pid = if ($backend) { $backend.Id } elseif ($oldState) { $oldState.backend_pid } else { 0 }
        frontend_pid = if ($frontend) { $frontend.Id } elseif ($oldState) { $oldState.frontend_pid } else { 0 }
        tunnel_pid = $tunnel.ProcessId
        public_url = $tunnel.PublicUrl
        tunnel_mode = [string]$config.tunnel_mode
    }
    Save-DbiState $state

    return [pscustomobject]@{
        Status = "RUNNING"
        PublicUrl = $tunnel.PublicUrl
    }
}

function Stop-DbiStack {
    $config = Get-DbiConfig
    $state = Get-DbiState

    if ($state) {
        foreach ($pidValue in @($state.frontend_pid, $state.backend_pid, $state.tunnel_pid)) {
            if ($pidValue) { Stop-DbiProcessTree ([int]$pidValue) }
        }
    }

    $containerName = [string]$config.container_name
    try {
        $running = (& docker inspect -f "{{.State.Running}}" $containerName 2>$null | Select-Object -First 1)
        if ($running -eq "true") { & docker stop $containerName *> $null }
    } catch {}

    Save-DbiState ([ordered]@{
        stopped_at = (Get-Date).ToString("o")
        backend_pid = 0
        frontend_pid = 0
        tunnel_pid = 0
        public_url = if ($state) { $state.public_url } else { "" }
        tunnel_mode = [string]$config.tunnel_mode
    })
}

function Get-DbiStatus {
    $config = Get-DbiConfig
    $state = Get-DbiState
    $container = "STOPPED"
    try {
        $running = (& docker inspect -f "{{.State.Running}}" ([string]$config.container_name) 2>$null | Select-Object -First 1)
        if ($running -eq "true") { $container = "RUNNING" }
    } catch {}

    $backend = if (Test-DbiHttp "http://127.0.0.1:$([int]$config.backend_port)/api/v1/health") { "RUNNING" } else { "STOPPED" }
    $frontend = if (Test-DbiHttp "http://127.0.0.1:$([int]$config.frontend_port)/api/v1/health") { "RUNNING" } else { "STOPPED" }
    $tunnel = if ($state -and $state.tunnel_pid -and (Test-DbiProcess ([int]$state.tunnel_pid))) { "RUNNING" } else { "STOPPED" }

    return [pscustomobject]@{
        Database = $container
        Backend = $backend
        Frontend = $frontend
        Tunnel = $tunnel
        PublicUrl = if ($state) { [string]$state.public_url } else { "" }
        TunnelMode = [string]$config.tunnel_mode
    }
}

function Open-DbiApp {
    $status = Get-DbiStatus
    $url = $status.PublicUrl
    if (-not $url) { $url = "http://127.0.0.1:4173" }
    Start-Process $url | Out-Null
}

function Show-DbiControlCenter {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "DALGORO Banana Intelligence - Control Center"
    $form.Width = 640
    $form.Height = 410
    $form.StartPosition = "CenterScreen"
    $form.MaximizeBox = $false

    $title = New-Object System.Windows.Forms.Label
    $title.Text = "DBI Control Center"
    $title.AutoSize = $true
    $title.Font = New-Object System.Drawing.Font("Segoe UI", 18)
    $title.Location = New-Object System.Drawing.Point(22, 18)
    $form.Controls.Add($title)

    $statusBox = New-Object System.Windows.Forms.TextBox
    $statusBox.Multiline = $true
    $statusBox.ReadOnly = $true
    $statusBox.Width = 585
    $statusBox.Height = 135
    $statusBox.Location = New-Object System.Drawing.Point(22, 62)
    $statusBox.Font = New-Object System.Drawing.Font("Consolas", 10)
    $form.Controls.Add($statusBox)

    $urlBox = New-Object System.Windows.Forms.TextBox
    $urlBox.ReadOnly = $true
    $urlBox.Width = 585
    $urlBox.Location = New-Object System.Drawing.Point(22, 208)
    $form.Controls.Add($urlBox)

    $startButton = New-Object System.Windows.Forms.Button
    $startButton.Text = "Iniciar / Reanudar"
    $startButton.Width = 145
    $startButton.Height = 42
    $startButton.Location = New-Object System.Drawing.Point(22, 252)
    $form.Controls.Add($startButton)

    $stopButton = New-Object System.Windows.Forms.Button
    $stopButton.Text = "Detener temporalmente"
    $stopButton.Width = 155
    $stopButton.Height = 42
    $stopButton.Location = New-Object System.Drawing.Point(177, 252)
    $form.Controls.Add($stopButton)

    $restartButton = New-Object System.Windows.Forms.Button
    $restartButton.Text = "Reiniciar sistema"
    $restartButton.Width = 135
    $restartButton.Height = 42
    $restartButton.Location = New-Object System.Drawing.Point(342, 252)
    $form.Controls.Add($restartButton)

    $openButton = New-Object System.Windows.Forms.Button
    $openButton.Text = "Abrir DBI"
    $openButton.Width = 120
    $openButton.Height = 42
    $openButton.Location = New-Object System.Drawing.Point(487, 252)
    $form.Controls.Add($openButton)

    $refreshButton = New-Object System.Windows.Forms.Button
    $refreshButton.Text = "Actualizar estado"
    $refreshButton.Width = 145
    $refreshButton.Height = 34
    $refreshButton.Location = New-Object System.Drawing.Point(22, 310)
    $form.Controls.Add($refreshButton)

    $note = New-Object System.Windows.Forms.Label
    $note.Text = "Cerrar esta ventana NO detiene DBI. Use 'Detener temporalmente' cuando necesite parar el sistema."
    $note.AutoSize = $true
    $note.Location = New-Object System.Drawing.Point(177, 319)
    $form.Controls.Add($note)

    $refresh = {
        try {
            $s = Get-DbiStatus
            $statusBox.Text = "PostGIS : $($s.Database)`r`nFastAPI : $($s.Backend)`r`nFrontend: $($s.Frontend)`r`nTunnel  : $($s.Tunnel)`r`nModo    : $($s.TunnelMode)"
            $urlBox.Text = $s.PublicUrl
        } catch {
            $statusBox.Text = $_.Exception.Message
        }
    }

    $startButton.Add_Click({
        $form.UseWaitCursor = $true
        try { Start-DbiStack | Out-Null } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "DBI") | Out-Null }
        $form.UseWaitCursor = $false
        & $refresh
    })
    $stopButton.Add_Click({
        $form.UseWaitCursor = $true
        try { Stop-DbiStack } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "DBI") | Out-Null }
        $form.UseWaitCursor = $false
        & $refresh
    })
    $restartButton.Add_Click({
        $form.UseWaitCursor = $true
        try { Stop-DbiStack; Start-DbiStack | Out-Null } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "DBI") | Out-Null }
        $form.UseWaitCursor = $false
        & $refresh
    })
    $openButton.Add_Click({ try { Open-DbiApp } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "DBI") | Out-Null } })
    $refreshButton.Add_Click({ & $refresh })

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 5000
    $timer.Add_Tick({ & $refresh })
    $timer.Start()

    & $refresh
    [void]$form.ShowDialog()
}

Ensure-DbiRuntimeDirectories

switch ($Action) {
    "Start" {
        $result = Start-DbiStack
        Write-Host "dbi_status=$($result.Status)"
        Write-Host "dbi_url=$($result.PublicUrl)"
    }
    "Stop" {
        Stop-DbiStack
        Write-Host "dbi_status=STOPPED"
    }
    "Restart" {
        Stop-DbiStack
        $result = Start-DbiStack
        Write-Host "dbi_status=$($result.Status)"
        Write-Host "dbi_url=$($result.PublicUrl)"
    }
    "Status" {
        Get-DbiStatus | Format-List
    }
    "Open" { Open-DbiApp }
    default { Show-DbiControlCenter }
}

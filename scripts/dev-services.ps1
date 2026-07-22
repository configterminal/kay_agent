<#
.SYNOPSIS
  AI dev environment - start/stop and zombie process cleanup

.EXAMPLE
  .\scripts\dev-services.ps1 status
  .\scripts\dev-services.ps1 stop
  .\scripts\dev-services.ps1 start
  .\scripts\dev-services.ps1 restart
  .\scripts\dev-services.ps1 kill-zombies
  .\scripts\dev-services.ps1 start -Reload
  .\scripts\dev-services.ps1 restart -Redis
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'stop', 'start', 'restart', 'kill-zombies')]
    [string] $Action = 'status',

    [switch] $Reload,
    [switch] $Redis
)

$ErrorActionPreference = 'Continue'

$ProjectRoot  = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython   = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$UiDir        = Join-Path $ProjectRoot 'src\ui'
$BackendPort  = 8000
$FrontendPort = 5173
$RedisPort    = 6380
$PidDir       = Join-Path $ProjectRoot 'tmp\dev-services'
$BackendPidFile  = Join-Path $PidDir 'backend.shell.pid'
$FrontendPidFile = Join-Path $PidDir 'frontend.shell.pid'
$BackendWindowTitle  = 'agent-dev-backend'
$FrontendWindowTitle = 'agent-dev-frontend'

function Write-Info([string]$Msg) { Write-Host "[dev] $Msg" -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host "[dev] $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "[dev] $Msg" -ForegroundColor Yellow }
function Write-Err([string]$Msg)  { Write-Host "[dev] $Msg" -ForegroundColor Red }

function Get-PortOwnerPids([int]$Port) {
    $pids = @()
    try {
        $pids = @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    catch {
        $lines = netstat -ano | Select-String ":$Port\s"
        foreach ($line in $lines) {
            if ($line -match '\s+(\d+)\s*$') { $pids += [int]$Matches[1] }
        }
        $pids = @($pids | Select-Object -Unique)
    }
    return @($pids | Where-Object { $_ -gt 0 })
}

function Get-AgentPythonPids() {
    $hits = @()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            $cmd = $p.CommandLine
            if (-not $cmd) { continue }
            $isAgent = ($cmd -match [regex]::Escape($ProjectRoot)) -or
                       ($cmd -match 'src\.main:app') -or
                       ($cmd -match 'uvicorn')
            $isOrphan = ($cmd -match 'spawn_main') -and ($cmd -match 'multiprocessing')
            if ($isAgent -or $isOrphan) { $hits += [int]$p.ProcessId }
        }
    }
    catch { Write-Warn "list python failed: $_" }
    return @($hits | Select-Object -Unique)
}

function Get-VitePids() {
    $hits = @()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            $cmd = $p.CommandLine
            if ($cmd -and (($cmd -match 'vite') -or ($cmd -match [regex]::Escape($UiDir)))) {
                $hits += [int]$p.ProcessId
            }
        }
    }
    catch { Write-Warn "list node failed: $_" }
    return @($hits | Select-Object -Unique)
}

function Stop-Pids([int[]]$Pids, [string]$Label) {
    if (-not $Pids -or $Pids.Count -eq 0) {
        Write-Info "$Label : no process"
        return
    }
    foreach ($procId in ($Pids | Sort-Object -Unique)) {
        try {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if (-not $proc) {
                Write-Warn "$Label PID $procId stale in netstat"
                continue
            }
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Ok "stopped $Label PID $procId"
        }
        catch { Write-Warn "stop $Label PID $procId failed: $_" }
    }
}

function Ensure-PidDir() {
    if (-not (Test-Path $PidDir)) {
        New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
    }
}

function Save-ShellPid([string]$File, [int]$ProcId) {
    Ensure-PidDir
    Set-Content -Path $File -Value "$ProcId" -Encoding ascii
}

function Read-ShellPid([string]$File) {
    if (-not (Test-Path $File)) { return $null }
    $raw = (Get-Content -Path $File -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($raw -match '^\d+$') { return [int]$raw }
    return $null
}

function Get-ParentPid([int]$ProcId) {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
        if ($p -and $p.ParentProcessId) { return [int]$p.ParentProcessId }
    }
    catch { }
    return $null
}

function Get-DevShellPids() {
    # Find PowerShell/CMD shells launched for this project's backend/frontend.
    # Used so restart closes previous -NoExit windows instead of stacking them.
    $hits = @()

    foreach ($file in @($BackendPidFile, $FrontendPidFile)) {
        $pidFromFile = Read-ShellPid -File $file
        if ($pidFromFile) { $hits += $pidFromFile }
    }

    # Parent shell of port owners (powershell -> python/node)
    foreach ($port in @($BackendPort, $FrontendPort)) {
        foreach ($childId in @(Get-PortOwnerPids -Port $port)) {
            $parentId = Get-ParentPid -ProcId $childId
            if ($parentId) { $hits += $parentId }
        }
    }
    foreach ($childId in @((Get-AgentPythonPids) + (Get-VitePids))) {
        $parentId = Get-ParentPid -ProcId $childId
        if ($parentId) { $hits += $parentId }
    }

    try {
        $shells = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(powershell|pwsh|cmd)\.exe$' }
        foreach ($p in $shells) {
            $cmd = $p.CommandLine
            if (-not $cmd) { continue }
            $isBackendShell = ($cmd -match 'uvicorn') -and (
                ($cmd -match [regex]::Escape($ProjectRoot)) -or
                ($cmd -match 'src\.main:app') -or
                ($cmd -match [regex]::Escape($BackendWindowTitle))
            )
            $isFrontendShell = ($cmd -match 'npm run dev') -and (
                ($cmd -match [regex]::Escape($UiDir)) -or
                ($cmd -match [regex]::Escape($FrontendWindowTitle)) -or
                ($cmd -match 'vite')
            )
            $isTitled = ($cmd -match [regex]::Escape($BackendWindowTitle)) -or
                        ($cmd -match [regex]::Escape($FrontendWindowTitle))
            if ($isBackendShell -or $isFrontendShell -or $isTitled) {
                $hits += [int]$p.ProcessId
            }
        }
    }
    catch { Write-Warn "list shell windows failed: $_" }

    # Do not kill the window currently running this script
    $selfId = [System.Diagnostics.Process]::GetCurrentProcess().Id
    $selfParent = Get-ParentPid -ProcId $selfId
    return @($hits | Where-Object { $_ -gt 0 -and $_ -ne $selfId -and $_ -ne $selfParent } | Select-Object -Unique)
}

function Stop-DevShellWindows() {
    $shellPids = Get-DevShellPids
    if ($shellPids.Count -eq 0) {
        Write-Info 'dev shell windows : no process'
    }
    else {
        Stop-Pids -Pids $shellPids -Label 'dev-shell'
    }
    # Remove stale pid files
    foreach ($file in @($BackendPidFile, $FrontendPidFile)) {
        if (Test-Path $file) {
            Remove-Item -Path $file -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-DevServices() {
    Write-Info 'stopping dev services...'

    # Stop workers first, then leftover -NoExit shell windows
    $backendPids = @()
    $backendPids += @(Get-PortOwnerPids -Port $BackendPort)
    $backendPids += @(Get-AgentPythonPids)
    $backendPids = @($backendPids | Select-Object -Unique)
    Stop-Pids -Pids $backendPids -Label 'backend'

    $frontendPids = @()
    $frontendPids += @(Get-PortOwnerPids -Port $FrontendPort)
    $frontendPids += @(Get-VitePids)
    $frontendPids = @($frontendPids | Select-Object -Unique)
    Stop-Pids -Pids $frontendPids -Label 'frontend'

    Start-Sleep -Seconds 1
    Stop-DevShellWindows

    # Second pass: netstat can briefly keep stale PIDs; re-kill if still listening
    Start-Sleep -Seconds 1
    $left8000 = Get-PortOwnerPids -Port $BackendPort
    $left5173 = Get-PortOwnerPids -Port $FrontendPort
    if ($left8000.Count -gt 0) {
        Stop-Pids -Pids $left8000 -Label 'backend-retry'
        Start-Sleep -Milliseconds 500
        $left8000 = Get-PortOwnerPids -Port $BackendPort
    }
    if ($left5173.Count -gt 0) {
        Stop-Pids -Pids $left5173 -Label 'frontend-retry'
        Start-Sleep -Milliseconds 500
        $left5173 = Get-PortOwnerPids -Port $FrontendPort
    }
    if ($left8000.Count -gt 0) { Write-Warn "port 8000 still used: $($left8000 -join ', ')" }
    if ($left5173.Count -gt 0) { Write-Warn "port 5173 still used: $($left5173 -join ', ')" }
}

function Test-HttpOk([string]$Url, [int]$TimeoutSec = 5) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return @{ Ok = $true; Status = $resp.StatusCode; Body = $resp.Content }
    }
    catch { return @{ Ok = $false; Status = 0; Body = $_.Exception.Message } }
}

function Show-Status() {
    Write-Info "project: $ProjectRoot"
    Write-Host ''

    foreach ($item in @(
            @{ Name = 'backend';  Port = $BackendPort;  Url = "http://127.0.0.1:$BackendPort/readyz" },
            @{ Name = 'frontend'; Port = $FrontendPort; Url = "http://127.0.0.1:$FrontendPort/" },
            @{ Name = 'redis';    Port = $RedisPort;    Url = $null }
        )) {
        $pids = Get-PortOwnerPids -Port $item.Port
        $pidText = if ($pids.Count) { ($pids -join ', ') } else { '(free)' }
        Write-Host ("{0,-10} :{1,-5} PID {2}" -f $item.Name, $item.Port, $pidText)
        if ($item.Url) {
            $r = Test-HttpOk -Url $item.Url
            if ($r.Ok) {
                $preview = if ($r.Body.Length -gt 80) { $r.Body.Substring(0, 80) + '...' } else { $r.Body }
                Write-Host ("           HTTP {0} {1}" -f $r.Status, $preview)
            }
            else { Write-Host ("           HTTP down ({0})" -f $r.Body) }
        }
    }

    $orphans = Get-AgentPythonPids
    if ($orphans.Count -gt 0) {
        Write-Warn "agent python processes (possible orphan worker): $($orphans -join ', ')"
    }
}

function Start-RedisIfNeeded() {
    $running = docker ps --filter "name=redis-stack" --format "{{.Names}}" 2>$null
    if ($running -match 'redis-stack') {
        if ($Redis) {
            Write-Info 'restarting redis-stack...'
            docker restart redis-stack | Out-Null
            Write-Ok 'redis-stack restarted'
        }
        else { Write-Info 'redis-stack already running (use -Redis to restart)' }
        return
    }
    Write-Info 'starting redis-stack container...'
    docker run -d --name redis-stack -p 6380:6379 -p 8002:8001 redis/redis-stack:latest | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok 'redis-stack started on 6380' }
    else { Write-Err 'redis start failed - check docker' }
}

function Start-DevServices() {
    if (-not (Test-Path $VenvPython)) {
        Write-Err "venv not found: $VenvPython"
        exit 1
    }

    $busy8000 = Get-PortOwnerPids -Port $BackendPort
    $busy5173 = Get-PortOwnerPids -Port $FrontendPort
    if ($busy8000.Count -gt 0 -or $busy5173.Count -gt 0) {
        Write-Warn 'ports busy, running stop first...'
        Stop-DevServices
    }

    Start-RedisIfNeeded
    Ensure-PidDir

    $reloadArg = if ($Reload) { '--reload' } else { '' }
    # Window title + pid file so stop/restart can close old shells
    $backendScript = @(
        "`$Host.UI.RawUI.WindowTitle = '$BackendWindowTitle'"
        "Set-Location '$ProjectRoot'"
        "& '$VenvPython' -m uvicorn src.main:app --host 127.0.0.1 --port $BackendPort $reloadArg"
    ) -join '; '
    Write-Info "starting backend on port $BackendPort"
    $backendProc = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList '-NoExit', '-Command', $backendScript `
        -WindowStyle Normal -PassThru
    if ($backendProc) { Save-ShellPid -File $BackendPidFile -ProcId $backendProc.Id }

    $frontendScript = @(
        "`$Host.UI.RawUI.WindowTitle = '$FrontendWindowTitle'"
        "Set-Location '$UiDir'"
        "npm run dev -- --host 127.0.0.1 --port $FrontendPort"
    ) -join '; '
    Write-Info "starting frontend on port $FrontendPort"
    $frontendProc = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList '-NoExit', '-Command', $frontendScript `
        -WindowStyle Normal -PassThru
    if ($frontendProc) { Save-ShellPid -File $FrontendPidFile -ProcId $frontendProc.Id }

    if ($Reload) {
        Write-Warn 'reload enabled; if Milvus lock error, run: .\scripts\dev-services.ps1 restart'
    }
    else {
        Write-Info 'reload disabled by default; use: .\scripts\dev-services.ps1 start -Reload'
    }

    Write-Info 'waiting for readyz (30-90s)...'
    $deadline = (Get-Date).AddSeconds(120)
    $backendReady = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        $r = Test-HttpOk -Url "http://127.0.0.1:$BackendPort/readyz" -TimeoutSec 8
        if ($r.Ok -and $r.Body -match '"ready"\s*:\s*true') {
            $backendReady = $true
            break
        }
    }

    $fe = Test-HttpOk -Url "http://127.0.0.1:$FrontendPort/" -TimeoutSec 5
    if ($backendReady) { Write-Ok "backend ready: http://127.0.0.1:$BackendPort/readyz" }
    else { Write-Warn 'backend not ready yet - check new PowerShell window' }
    if ($fe.Ok) { Write-Ok "frontend ready: http://127.0.0.1:$FrontendPort/" }
    else { Write-Warn 'frontend not ready yet - check new PowerShell window' }
}

function Kill-ZombieProcesses() {
    Write-Info 'killing zombies (ports + agent python + vite)...'
    Stop-DevServices
    $again = Get-AgentPythonPids
    Stop-Pids -Pids $again -Label 'orphan-python'
    Start-Sleep -Seconds 1
    Show-Status
}

Set-Location $ProjectRoot

switch ($Action) {
    'status'       { Show-Status }
    'stop'         { Stop-DevServices; Show-Status }
    'start'        { Start-DevServices; Show-Status }
    'restart'      { Stop-DevServices; Start-Sleep -Seconds 2; Start-DevServices; Show-Status }
    'kill-zombies' { Kill-ZombieProcesses }
}

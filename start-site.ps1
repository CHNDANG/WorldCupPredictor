param(
  [int]$Port = 4173
)

$ErrorActionPreference = "Stop"
$Root = "D:\WorldCupPredictor"
$Python = "C:\Program Files\Python312\python.exe"

function Test-ProcessCommand {
  param([string]$Pattern)
  @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*$Pattern*"
  })
}

function Start-IfMissing {
  param(
    [string]$Name,
    [string]$Pattern,
    [string]$Arguments,
    [string]$WorkingDirectory,
    [string]$Stdout,
    [string]$Stderr
  )

  $running = Test-ProcessCommand -Pattern $Pattern
  if ($running.Count -gt 0) {
    Write-Host "$Name already running: $($running[0].ProcessId)"
    return
  }

  $startArgs = @{
    FilePath = $Python
    ArgumentList = $Arguments
    WorkingDirectory = $WorkingDirectory
    WindowStyle = "Hidden"
  }
  if ($Stdout) { $startArgs.RedirectStandardOutput = $Stdout }
  if ($Stderr) { $startArgs.RedirectStandardError = $Stderr }
  Start-Process @startArgs
  Write-Host "$Name started"
}

function Stop-DuplicatePythonProcesses {
  param([string]$Pattern)
  $running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*$Pattern*"
  } | Sort-Object ProcessId)
  if ($running.Count -le 1) { return }
  $running | Select-Object -Skip 1 | ForEach-Object {
    Write-Host "stop duplicate $Pattern pid=$($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force
  }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
  if ($owner -and $owner.CommandLine -like "*site-server.py*") {
    Write-Host "site already listening: $($listener.OwningProcess)"
  } else {
    Write-Host "stop stale listener on $Port pid=$($listener.OwningProcess)"
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Seconds 1
    $listener = $null
  }
}

if (-not $listener) {
  Start-IfMissing `
    -Name "site" `
    -Pattern "site-server.py" `
    -Arguments "work\site-server.py --port $Port --bind 127.0.0.1 --min-refresh-seconds 12 --background-interval 15" `
    -WorkingDirectory $Root `
    -Stdout "$Root\work\site-server.stdout.log" `
    -Stderr "$Root\work\site-server.stderr.log"
}

$liveProcs = Test-ProcessCommand -Pattern "live-feed-bridge-espn.py"
if ($liveProcs.Count -gt 0) {
  Write-Host "stop standalone live feed; site server refreshes on open"
  $liveProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

Start-IfMissing `
  -Name "news feed" `
  -Pattern "news-feed-bridge.py" `
  -Arguments "work\news-feed-bridge.py --interval 300" `
  -WorkingDirectory $Root `
  -Stdout "$Root\work\news-feed-bridge.stdout.log" `
  -Stderr "$Root\work\news-feed-bridge.stderr.log"

Start-Sleep -Seconds 1
Stop-DuplicatePythonProcesses -Pattern "live-feed-bridge-espn.py"
Stop-DuplicatePythonProcesses -Pattern "news-feed-bridge.py"
Stop-DuplicatePythonProcesses -Pattern "site-server.py"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/worldcup-predictions.html" -TimeoutSec 5 | Out-Null
Write-Host "ready: http://127.0.0.1:$Port/worldcup-predictions.html"

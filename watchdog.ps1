$ErrorActionPreference = "Continue"

$Root = "D:\WorldCupPredictor"
$StartScript = Join-Path $Root "start-site.ps1"
$Log = Join-Path $Root "work\watchdog.log"

function Write-Log {
  param([string]$Message)
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -LiteralPath $Log -Encoding UTF8 -Value "$stamp $Message"
}

try {
  $pageOk = $false
  try {
    $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/worldcup-predictions.html" -TimeoutSec 5
    $pageOk = $response.StatusCode -eq 200
  } catch {
    $pageOk = $false
  }

  $siteProc = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*site-server.py*"
  })
  $newsProc = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "python.exe" -and $_.CommandLine -like "*news-feed-bridge.py*"
  })

  if (-not $pageOk -or $siteProc.Count -eq 0 -or $newsProc.Count -eq 0) {
    Write-Log "restart needed pageOk=$pageOk site=$($siteProc.Count) news=$($newsProc.Count)"
    powershell -ExecutionPolicy Bypass -File $StartScript | Out-Null
    Start-Sleep -Seconds 2
  }

  $final = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/worldcup-predictions.html" -TimeoutSec 5
  Write-Log "ok status=$($final.StatusCode)"
} catch {
  Write-Log "ERROR $($_.Exception.Message)"
  exit 1
}

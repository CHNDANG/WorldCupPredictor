param(
  [int]$Port = 4173,
  [ValidateSet("auto", "cloudflare", "localhostrun", "localtunnel")]
  [string]$Provider = "auto",
  [switch]$Fresh,
  [switch]$InstallCloudflared
)

$ErrorActionPreference = "Stop"
$Root = "D:\WorldCupPredictor"
$Tools = Join-Path $Root "tools"
$Work = Join-Path $Root "work"
$Cloudflared = Join-Path $Tools "cloudflared.exe"
$UrlFile = Join-Path $Work "public-url.txt"
$CloudflaredUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

$ProviderConfig = @{
  cloudflare = @{
    Stdout = Join-Path $Work "cloudflared.stdout.log"
    Stderr = Join-Path $Work "cloudflared.stderr.log"
    UrlPattern = "https://[-a-zA-Z0-9]+\.trycloudflare\.com"
  }
  localhostrun = @{
    Stdout = Join-Path $Work "localhost-run.stdout.log"
    Stderr = Join-Path $Work "localhost-run.stderr.log"
    UrlPattern = "https://[-a-zA-Z0-9]+\.lhr\.life"
  }
  localtunnel = @{
    Stdout = Join-Path $Work "localtunnel.stdout.log"
    Stderr = Join-Path $Work "localtunnel.stderr.log"
    UrlPattern = "https://[-a-zA-Z0-9.]+\.loca\.lt"
  }
}

function Test-Cloudflared {
  if (-not (Test-Path $Cloudflared)) { return $false }
  try {
    $version = & $Cloudflared --version 2>$null
    return ($LASTEXITCODE -eq 0 -and $version -match "cloudflared")
  } catch {
    return $false
  }
}

function Install-CloudflaredBinary {
  New-Item -ItemType Directory -Force -Path $Tools | Out-Null
  Remove-Item -Path $Cloudflared -Force -ErrorAction SilentlyContinue
  Write-Host "download cloudflared to $Cloudflared"

  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    & $curl.Source -L --fail --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 90 --speed-limit 1024 --speed-time 20 --output $Cloudflared $CloudflaredUrl
    if ($LASTEXITCODE -ne 0) {
      Remove-Item -Path $Cloudflared -Force -ErrorAction SilentlyContinue
      throw "curl download failed with exit code $LASTEXITCODE"
    }
  } else {
    Invoke-WebRequest -UseBasicParsing -Uri $CloudflaredUrl -OutFile $Cloudflared -TimeoutSec 120
  }

  if (-not (Test-Cloudflared)) {
    $size = 0
    if (Test-Path $Cloudflared) {
      $size = (Get-Item $Cloudflared).Length
    }
    Remove-Item -Path $Cloudflared -Force -ErrorAction SilentlyContinue
    throw "Downloaded cloudflared is not executable. Bytes received: $size"
  }
}

function Read-ProviderUrl {
  param([string]$Name)
  $config = $ProviderConfig[$Name]
  $text = ""
  foreach ($path in @($config.Stderr, $config.Stdout)) {
    if (Test-Path $path) {
      $text += "`n" + (Get-Content -Path $path -Raw -ErrorAction SilentlyContinue)
    }
  }
  $matches = [regex]::Matches($text, $config.UrlPattern)
  if ($matches.Count -gt 0) {
    return $matches[$matches.Count - 1].Value.TrimEnd("/")
  }
  return $null
}

function Wait-ProviderUrl {
  param(
    [string]$Name,
    [int]$Seconds = 45
  )
  for ($i = 0; $i -lt $Seconds; $i++) {
    $url = Read-ProviderUrl -Name $Name
    if ($url) { return $url }
    Start-Sleep -Seconds 1
  }
  return $null
}

function Stop-MatchingProcess {
  param(
    [string]$Name,
    [string[]]$Patterns
  )
  Get-CimInstance Win32_Process | Where-Object {
    $commandLine = $_.CommandLine
    $_.Name -eq $Name -and ($Patterns | ForEach-Object { $commandLine -like $_ }) -notcontains $false
  } | ForEach-Object {
    Write-Host "stop old tunnel pid=$($_.ProcessId) $Name"
    Stop-Process -Id $_.ProcessId -Force
  }
}

function Start-CloudflareTunnel {
  if (-not (Test-Cloudflared)) {
    if (-not $InstallCloudflared -and $Provider -eq "auto") {
      throw "cloudflared is not installed; skip download in auto mode"
    }
    Install-CloudflaredBinary
  }

  $config = $ProviderConfig.cloudflare
  if ($Fresh) {
    Stop-MatchingProcess -Name "cloudflared.exe" -Patterns @("*tunnel*", "*http://127.0.0.1:$Port*")
    Remove-Item -Path $config.Stdout, $config.Stderr -Force -ErrorAction SilentlyContinue
  }

  $running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "cloudflared.exe" -and $_.CommandLine -like "*tunnel*" -and $_.CommandLine -like "*http://127.0.0.1:$Port*"
  })
  if ($running.Count -eq 0) {
    Remove-Item -Path $config.Stdout, $config.Stderr -Force -ErrorAction SilentlyContinue
    Start-Process `
      -FilePath $Cloudflared `
      -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$Port", "--no-autoupdate") `
      -WorkingDirectory $Root `
      -RedirectStandardOutput $config.Stdout `
      -RedirectStandardError $config.Stderr `
      -WindowStyle Hidden
    Write-Host "cloudflare tunnel starting"
  } else {
    Write-Host "cloudflare tunnel already running: $($running[0].ProcessId)"
  }

  $url = Wait-ProviderUrl -Name "cloudflare" -Seconds 60
  if (-not $url) { throw "Cloudflare tunnel did not return a URL" }
  return $url
}

function Start-LocalhostRunTunnel {
  $ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
  if (-not $ssh) { throw "ssh.exe is not available" }

  $config = $ProviderConfig.localhostrun
  if ($Fresh) {
    Stop-MatchingProcess -Name "ssh.exe" -Patterns @("*nokey@localhost.run*", "*80:127.0.0.1:$Port*")
    Remove-Item -Path $config.Stdout, $config.Stderr -Force -ErrorAction SilentlyContinue
  }

  $running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "ssh.exe" -and $_.CommandLine -like "*nokey@localhost.run*" -and $_.CommandLine -like "*80:127.0.0.1:$Port*"
  })
  if ($running.Count -eq 0) {
    Remove-Item -Path $config.Stdout, $config.Stderr -Force -ErrorAction SilentlyContinue
    $knownHosts = Join-Path $Work "localhost-run-known-hosts"
    Start-Process `
      -FilePath $ssh.Source `
      -ArgumentList @(
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=$knownHosts",
        "-o", "ServerAliveInterval=60",
        "-R", "80:127.0.0.1:$Port",
        "nokey@localhost.run"
      ) `
      -WorkingDirectory $Root `
      -RedirectStandardOutput $config.Stdout `
      -RedirectStandardError $config.Stderr `
      -WindowStyle Hidden
    Write-Host "localhost.run tunnel starting"
  } else {
    Write-Host "localhost.run tunnel already running: $($running[0].ProcessId)"
  }

  $url = Wait-ProviderUrl -Name "localhostrun" -Seconds 45
  if (-not $url) { throw "localhost.run tunnel did not return a URL" }
  return $url
}

function Start-Localtunnel {
  $npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
  if (-not $npx) {
    $npx = Get-Command npx.ps1 -ErrorAction SilentlyContinue
  }
  if (-not $npx) { throw "npx is not available" }

  $config = $ProviderConfig.localtunnel
  if ($Fresh) {
    Stop-MatchingProcess -Name "node.exe" -Patterns @("*localtunnel*", "*$Port*")
    Remove-Item -Path $config.Stdout, $config.Stderr -Force -ErrorAction SilentlyContinue
  }

  $running = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "node.exe" -and $_.CommandLine -like "*localtunnel*" -and $_.CommandLine -like "*$Port*"
  })
  if ($running.Count -eq 0) {
    Remove-Item -Path $config.Stdout, $config.Stderr -Force -ErrorAction SilentlyContinue
    $env:npm_config_cache = Join-Path $Tools "npm-cache"
    New-Item -ItemType Directory -Force -Path $env:npm_config_cache | Out-Null
    Start-Process `
      -FilePath $npx.Source `
      -ArgumentList @("--yes", "localtunnel", "--port", "$Port", "--local-host", "127.0.0.1") `
      -WorkingDirectory $Root `
      -RedirectStandardOutput $config.Stdout `
      -RedirectStandardError $config.Stderr `
      -WindowStyle Hidden
    Write-Host "localtunnel starting"
  } else {
    Write-Host "localtunnel already running: $($running[0].ProcessId)"
  }

  $url = Wait-ProviderUrl -Name "localtunnel" -Seconds 75
  if (-not $url) { throw "localtunnel did not return a URL" }
  return $url
}

function Test-PublicPage {
  param([string]$BaseUrl)
  $page = "$BaseUrl/worldcup-predictions.html"
  try {
    Invoke-WebRequest -UseBasicParsing $page -TimeoutSec 15 | Out-Null
    return $page
  } catch {
    Write-Host "public URL created but remote check is warming up: $page"
    return $page
  }
}

Set-Location $Root
& "$Root\start-site.ps1" -Port $Port -Bind "0.0.0.0"
Remove-Item -Path $UrlFile -Force -ErrorAction SilentlyContinue

$attempts = @()
if ($Provider -eq "cloudflare") {
  $attempts = @("cloudflare")
} elseif ($Provider -eq "localhostrun") {
  $attempts = @("localhostrun")
} elseif ($Provider -eq "localtunnel") {
  $attempts = @("localtunnel")
} else {
  $attempts = if (Test-Cloudflared -or $InstallCloudflared) {
    @("cloudflare", "localhostrun", "localtunnel")
  } else {
    @("localhostrun", "localtunnel", "cloudflare")
  }
}

$errors = @()
foreach ($attempt in $attempts) {
  try {
    Write-Host "try provider: $attempt"
    $base = switch ($attempt) {
      "cloudflare" { Start-CloudflareTunnel }
      "localhostrun" { Start-LocalhostRunTunnel }
      "localtunnel" { Start-Localtunnel }
    }
    $page = Test-PublicPage -BaseUrl $base
    Set-Content -Path $UrlFile -Value $page -Encoding UTF8
    Write-Output "ready public ($attempt): $page"
    Write-Output "phone/app: open this URL on any network while this computer is on:"
    Write-Output $page
    exit 0
  } catch {
    $message = "$attempt failed: $($_.Exception.Message)"
    $errors += $message
    Write-Host $message
  }
}

throw "No public tunnel provider succeeded.`n$($errors -join "`n")"

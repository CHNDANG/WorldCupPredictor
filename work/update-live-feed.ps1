param(
  [string]$MatchId = "esp-cpv",
  [string]$Status = "live",
  [int]$Minute = 0,
  [int]$HomeGoals = 0,
  [int]$AwayGoals = 0,
  [double]$HomeXg = 0,
  [double]$AwayXg = 0,
  [int]$HomeRedCards = 0,
  [int]$AwayRedCards = 0,
  [int]$Tempo = 0,
  [int]$MarketMove = 0,
  [string]$Note = "Manual live update"
)

$path = "C:\Users\Administrator\Documents\Codex\2026-06-14\new-chat\outputs\live-feed.json"
$feed = @{
  updatedAt = (Get-Date).ToUniversalTime().ToString("o")
  provider = "local-live-feed"
  matches = @(
    @{
      id = $MatchId
      status = $Status
      minute = $Minute
      homeGoals = $HomeGoals
      awayGoals = $AwayGoals
      homeXg = $HomeXg
      awayXg = $AwayXg
      homeRedCards = $HomeRedCards
      awayRedCards = $AwayRedCards
      tempo = $Tempo
      marketMove = $MarketMove
      note = $Note
    }
  )
}

$feed | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $path -Encoding UTF8
Write-Output $path

param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Root
)
$ErrorActionPreference = 'Stop'
$collector = Join-Path $PSScriptRoot 'collection_scheduler.py'
try {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python executable missing' }
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $log = Join-Path $Root 'task-output.log'
    Add-Content -LiteralPath $log -Encoding UTF8 -Value (([DateTime]::UtcNow.ToString('o')) + ' START')
    & $Python $collector --root $Root --start 2024-01-01 --symbols BTC ETH 2>&1 | Out-File -LiteralPath $log -Append -Encoding UTF8
    $result = $LASTEXITCODE
    Add-Content -LiteralPath $log -Encoding UTF8 -Value (([DateTime]::UtcNow.ToString('o')) + ' EXIT ' + $result)
    exit $result
} catch {
    Write-Error -ErrorRecord $_ -ErrorAction Continue
    exit 1
}

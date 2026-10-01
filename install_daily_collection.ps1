param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Root,
    [string]$TaskName = 'Price-Research-Daily'
)
$ErrorActionPreference = 'Stop'
$Python = (Resolve-Path -LiteralPath $Python).Path
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Expected Python executable' }
$Root = [IO.Path]::GetFullPath($Root)
$runner = Join-Path $PSScriptRoot 'run_daily_collection.ps1'
foreach ($value in @($Python, $Root, $runner)) {
    if ($value.Contains('"')) { throw 'Paths containing quotes are unsupported' }
}
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
# Never replace another task or alter its settings.
if (@($folder.GetTasks(1) | Where-Object { $_.Name -eq $TaskName }).Count) {
    throw "Task already exists: $TaskName"
}
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$escape = { param($value) [Security.SecurityElement]::Escape($value) }
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '" -Python "' + $Python + '" -Root "' + $Root + '"'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$boundary = [DateTime]::UtcNow.Date.ToString('yyyy-MM-dd') + 'T00:05:00Z'
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Price BTC/ETH offline research collection. No trading. UTC 00:05 daily and at user logon.</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger><StartBoundary>$boundary</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>
    <LogonTrigger><Enabled>true</Enabled><UserId>$(& $escape $user)</UserId></LogonTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>$(& $escape $user)</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable><Enabled>true</Enabled><Hidden>true</Hidden>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT15M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>$(& $escape $powershell)</Command><Arguments>$(& $escape $arguments)</Arguments><WorkingDirectory>$(& $escape $PSScriptRoot)</WorkingDirectory></Exec></Actions>
</Task>
"@
New-Item -ItemType Directory -Path $Root -Force | Out-Null
# TASK_CREATE=2, TASK_LOGON_INTERACTIVE_TOKEN=3: no stored credentials or elevation.
$task = $folder.RegisterTask($TaskName, $xml, 2, $user, $null, 3, $null)
$task.Xml | Set-Content -LiteralPath (Join-Path $Root 'scheduled-task.xml') -Encoding Unicode
[ordered]@{
    task_name = $TaskName; root = $Root; python = $Python; user = $user
    registered_at_utc = [DateTime]::UtcNow.ToString('o')
    schedule_utc = '00:05'; schedule_America_La_Paz = '20:05 (previous calendar day)'
    logon_type = 'InteractiveToken'; requires_user_logged_on = $true
    validation = 'NOT_VALIDATED'; execution_authorized = $false
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Root 'deployment.json') -Encoding UTF8
Write-Output "Registered $TaskName; daily UTC 00:05 and user logon; root: $Root"

param(
    [string]$RuntimeDir = (Join-Path $env:LOCALAPPDATA "GarminMcpTunnel")
)

$ErrorActionPreference = "Stop"
$version = "v0.0.11"
$expectedHash = "eb912c86c6ccde90cda805cb17009507176a656725cf86c36fabe1901a12e29b"
$downloadUrl = "https://github.com/openai/tunnel-client/releases/download/$version/tunnel-client-$version-windows-amd64.zip"
$tunnelId = "tunnel_6a7b0e9cf41c81918e14bc9d46db9922"
$cloudRunUrl = "https://garmin-mcp-smrc6iymhq-du.a.run.app"
$serviceAccount = "garmin-mcp-tunnel-local@garmin-work-collector.iam.gserviceaccount.com"
$taskName = "Garmin MCP Tunnel"

$repoRoot = Split-Path -Parent $PSScriptRoot
$proxySource = Join-Path $repoRoot "ops\tunnel_vm\cloud_run_auth_proxy.py"
$python = (Get-Command python.exe -ErrorAction Stop).Source
$gcloud = (Get-Command gcloud.cmd -ErrorAction Stop).Source

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
foreach ($listener in (Get-NetTCPConnection -State Listen -LocalPort 8080,8765 -ErrorAction SilentlyContinue)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($process.CommandLine -like "*$RuntimeDir*") {
        Stop-Process -Id $listener.OwningProcess -Force
    }
    else {
        throw "예상하지 못한 프로세스가 포트 $($listener.LocalPort)를 사용 중입니다."
    }
}
Start-Sleep -Seconds 1

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeDir "logs") | Out-Null
Copy-Item -LiteralPath $proxySource -Destination (Join-Path $RuntimeDir "cloud_run_auth_proxy.py") -Force

$archive = Join-Path $env:TEMP "tunnel-client-$version-windows-amd64.zip"
$extractDir = Join-Path $env:TEMP "tunnel-client-$version-windows-amd64"
Invoke-WebRequest -Uri $downloadUrl -OutFile $archive
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) {
    throw "tunnel-client SHA256 검증 실패"
}
if (Test-Path $extractDir) {
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}
Expand-Archive -LiteralPath $archive -DestinationPath $extractDir -Force
$binary = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "tunnel-client.exe" | Select-Object -First 1
if (-not $binary) {
    throw "tunnel-client.exe를 찾지 못했습니다."
}
Copy-Item -LiteralPath $binary.FullName -Destination (Join-Path $RuntimeDir "tunnel-client.exe") -Force
Remove-Item -LiteralPath $archive -Force
Remove-Item -LiteralPath $extractDir -Recurse -Force

$keyPath = (Join-Path $RuntimeDir "control-plane-api-key").Replace("\", "/")
$config = @"
config_version: 1
control_plane:
  tunnel_id: $tunnelId
  api_key: file:$keyPath
log:
  level: info
  format: json
health:
  listen_addr: 127.0.0.1:8080
admin_ui:
  open_browser: false
mcp:
  server_urls:
    - channel: main
      url: http://127.0.0.1:8765/mcp
"@
[IO.File]::WriteAllText((Join-Path $RuntimeDir "tunnel-client.yaml"), $config, [Text.UTF8Encoding]::new($false))

$escapedRuntimeDir = $RuntimeDir.Replace("'", "''")
$escapedPython = $python.Replace("'", "''")
$escapedGcloud = $gcloud.Replace("'", "''")
$runner = @"
`$ErrorActionPreference = "Stop"
`$runtimeDir = '$escapedRuntimeDir'
`$env:CLOUD_RUN_AUTH_MODE = 'gcloud'
`$env:CLOUD_RUN_BASE_URL = '$cloudRunUrl'
`$env:CLOUD_RUN_IMPERSONATE_SERVICE_ACCOUNT = '$serviceAccount'
`$env:GCLOUD_PATH = '$escapedGcloud'
`$proxyOut = Join-Path `$runtimeDir 'logs\proxy.out.log'
`$proxyErr = Join-Path `$runtimeDir 'logs\proxy.err.log'
`$tunnelLog = Join-Path `$runtimeDir 'logs\tunnel.log'
if (-not (Test-Path (Join-Path `$runtimeDir 'control-plane-api-key'))) { exit 2 }
`$proxy = Start-Process -FilePath '$escapedPython' -ArgumentList @((Join-Path `$runtimeDir 'cloud_run_auth_proxy.py')) -WindowStyle Hidden -PassThru -RedirectStandardOutput `$proxyOut -RedirectStandardError `$proxyErr
try {
    `$ready = `$false
    for (`$attempt = 0; `$attempt -lt 30; `$attempt++) {
        try {
            `$client = [Net.Sockets.TcpClient]::new('127.0.0.1', 8765)
            `$client.Dispose()
            `$ready = `$true
            break
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not `$ready) { throw 'Cloud Run auth proxy did not start' }
    Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 30 | Out-Null
    & (Join-Path `$runtimeDir 'tunnel-client.exe') run --config (Join-Path `$runtimeDir 'tunnel-client.yaml') *>> `$tunnelLog
    exit `$LASTEXITCODE
} finally {
    if (`$proxy -and -not `$proxy.HasExited) { Stop-Process -Id `$proxy.Id -Force }
}
"@
$runnerPath = Join-Path $RuntimeDir "run_tunnel.ps1"
[IO.File]::WriteAllText($runnerPath, $runner, [Text.UTF8Encoding]::new($false))

$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$action = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runnerPath`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "OpenAI Secure MCP Tunnel for Garmin" -Force | Out-Null

& (Join-Path $RuntimeDir "tunnel-client.exe") --version
$keyPath = Join-Path $RuntimeDir "control-plane-api-key"
if (Test-Path $keyPath) {
    Start-ScheduledTask -TaskName $taskName
    Write-Host "무료 Windows Tunnel 설치 및 시작 완료: $RuntimeDir"
}
else {
    Write-Host "무료 Windows Tunnel 설치 완료: $RuntimeDir"
    Write-Host "runtime key를 설치하기 전까지 작업은 시작되지 않습니다."
}

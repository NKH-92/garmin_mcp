param(
    [ValidateRange(1024, 65535)]
    [int]$ProxyPort = 18065
)

$ErrorActionPreference = "Stop"
$runtime = Join-Path $env:LOCALAPPDATA "GarminMcpTunnel"
$env:CLOUD_RUN_AUTH_MODE = "gcloud"
$env:CLOUD_RUN_BASE_URL = "https://garmin-mcp-smrc6iymhq-du.a.run.app"
$env:CLOUD_RUN_IMPERSONATE_SERVICE_ACCOUNT = "garmin-mcp-tunnel-local@garmin-work-collector.iam.gserviceaccount.com"
$env:GCLOUD_PATH = "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
$env:PROXY_LISTEN_PORT = [string]$ProxyPort
$python = (Get-Command python.exe -ErrorAction Stop).Source
$proxy = Start-Process -FilePath $python `
    -ArgumentList @((Join-Path $runtime "cloud_run_auth_proxy.py")) `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput (Join-Path $runtime "logs\diagnostic-proxy.out.log") `
    -RedirectStandardError (Join-Path $runtime "logs\diagnostic-proxy.err.log")
try {
    Start-Sleep -Seconds 2
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$ProxyPort/health" -UseBasicParsing -TimeoutSec 30
    Write-Output "PROXY_HEALTH_STATUS=$($response.StatusCode)"
    Write-Output "PROXY_HEALTH_BODY=$($response.Content)"
}
finally {
    if (-not $proxy.HasExited) {
        Stop-Process -Id $proxy.Id -Force
    }
}

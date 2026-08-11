param(
    [string]$RuntimeDir = (Join-Path $env:LOCALAPPDATA "GarminMcpTunnel"),
    [string]$TaskName = "Garmin MCP Tunnel"
)

$ErrorActionPreference = "Stop"
$secureKey = Read-Host "새 OpenAI Tunnel runtime key를 붙여넣으세요" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if (-not $plainKey.StartsWith("sk-")) {
        throw "OpenAI runtime key 형식이 아닙니다."
    }
    $keyFile = Join-Path $RuntimeDir "control-plane-api-key"
    [IO.File]::WriteAllText($keyFile, $plainKey, [Text.UTF8Encoding]::new($false))
    $account = "$env:USERDOMAIN\$env:USERNAME"
    & icacls.exe $keyFile /inheritance:r /grant:r "${account}:F" "*S-1-5-18:F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "runtime key 파일 ACL 설정에 실패했습니다."
    }
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $plainKey = $null
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $TaskName
Write-Host "runtime key 설치 및 Garmin Tunnel 시작 완료"

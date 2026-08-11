param(
    [string]$Project = "garmin-work-collector",
    [string]$Zone = "us-west1-b",
    [string]$Instance = "garmin-mcp-tunnel"
)

$ErrorActionPreference = "Stop"
$secureKey = Read-Host "새 OpenAI Tunnel runtime key를 붙여넣으세요" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    if (-not $plainKey.StartsWith("sk-")) {
        throw "OpenAI runtime key 형식이 아닙니다."
    }
    $remoteCommand = "sudo install -o root -g garmin-tunnel -m 0640 /dev/stdin /etc/garmin-mcp-tunnel/control-plane-api-key && sudo systemctl restart garmin-tunnel-client.service"
    $plainKey | & gcloud.cmd compute ssh $Instance --project $Project --zone $Zone --tunnel-through-iap --command $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "VM에 runtime key를 설치하지 못했습니다."
    }
}
finally {
    if ($ptr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
    $plainKey = $null
}

Write-Host "runtime key 설치 완료. 키 값은 파일이나 화면에 저장하지 않았습니다."

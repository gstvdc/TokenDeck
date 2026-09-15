$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\TokenDeckUsbBridge", [ref]$createdNew)
if (-not $createdNew) {
    Write-Host "A bridge TokenDeck ja esta em execucao."
    $mutex.Dispose()
    exit 0
}

try {
    $bridgeScript = (Resolve-Path "${PSScriptRoot}\daemon\usage_serial_bridge_windows.py").Path
    & "${PSScriptRoot}\daemon\.venv\Scripts\python.exe" $bridgeScript
    exit $LASTEXITCODE
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}

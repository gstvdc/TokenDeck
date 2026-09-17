$repoRoot = Split-Path $PSScriptRoot -Parent
$pio = Join-Path $env:USERPROFILE ".platformio\penv\Scripts\pio.exe"
& $pio run -d (Join-Path $repoRoot "firmware") --environment cyd_28 --target upload
exit $LASTEXITCODE

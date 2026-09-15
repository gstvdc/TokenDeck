$pio = Join-Path $env:USERPROFILE ".platformio\penv\Scripts\pio.exe"
& $pio run -d firmware --environment cyd_28 --target upload
exit $LASTEXITCODE

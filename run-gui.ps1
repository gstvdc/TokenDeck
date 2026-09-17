try {
    $pythonExe = "${PSScriptRoot}\daemon\.venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        $pythonExe = "python"
    }
    $guiScript = "${PSScriptRoot}\tokendeck_gui.py"
    $resolvedGui = (Resolve-Path $guiScript).Path
    & $pythonExe $resolvedGui
    exit $LASTEXITCODE
} catch {
    Write-Error $_
    exit 1
}

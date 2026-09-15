try {
    $pythonExe = "${PSScriptRoot}\daemon\.venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        $pythonExe = "python"
    }
    $guiScript = (Resolve-Path "${PSScriptRoot}\tokenmeter_gui.py").Path
    & $pythonExe $guiScript
    exit $LASTEXITCODE
} catch {
    Write-Error $_
    exit 1
}

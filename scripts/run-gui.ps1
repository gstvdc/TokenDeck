try {
    $repoRoot = Split-Path $PSScriptRoot -Parent
    $pythonExe = "${repoRoot}\daemon\.venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        $pythonExe = "python"
    }
    $guiScript = "${repoRoot}\tokendeck_gui.py"
    $resolvedGui = (Resolve-Path $guiScript).Path
    & $pythonExe $resolvedGui
    exit $LASTEXITCODE
} catch {
    Write-Error $_
    exit 1
}

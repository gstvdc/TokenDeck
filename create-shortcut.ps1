$WshShell = New-Object -ComObject WScript.Shell
$projectDir = $PSScriptRoot
if (-not $projectDir) {
    $projectDir = (Get-Location).Path
}

$pythonw = Join-Path $projectDir 'daemon\.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    $pythonw = 'pythonw.exe'
}

$guiPy = Join-Path $projectDir 'tokendeck_gui.py'
$icon = Join-Path $projectDir 'assets\tokendeck.ico'

# 1. Atalho na pasta do projeto
$projLnk = Join-Path $projectDir 'TokenDeck.lnk'
$s1 = $WshShell.CreateShortcut($projLnk)
$s1.TargetPath = $pythonw
$s1.Arguments = "`"$guiPy`""
$s1.WorkingDirectory = $projectDir
$s1.IconLocation = "$icon,0"
$s1.Description = 'TokenDeck Studio — Painel de Monitoramento de IA'
$s1.Save()
Write-Host "Atalho criado na pasta do projeto: $projLnk"

# 2. Atalho na Área de Trabalho (Desktop)
$desktop = [Environment]::GetFolderPath('Desktop')
if (Test-Path $desktop) {
    $desktopLnk = Join-Path $desktop 'TokenDeck.lnk'
    $s2 = $WshShell.CreateShortcut($desktopLnk)
    $s2.TargetPath = $pythonw
    $s2.Arguments = "`"$guiPy`""
    $s2.WorkingDirectory = $projectDir
    $s2.IconLocation = "$icon,0"
    $s2.Description = 'TokenDeck Studio — Painel de Monitoramento de IA'
    $s2.Save()
    Write-Host "Atalho criado na Area de Trabalho: $desktopLnk"
}

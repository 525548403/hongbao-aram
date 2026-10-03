# ARAM Score - installer (no admin required; installs to LocalAppData)
# Run via:  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'

$src     = Split-Path -Parent $MyInvocation.MyCommand.Definition
$appName = 'ARAM Score'
$target  = Join-Path $env:LOCALAPPDATA ('Programs\' + $appName)

if (-not (Test-Path $target)) {
    New-Item -ItemType Directory -Force -Path $target | Out-Null
}

# Copy main executable + README
Copy-Item (Join-Path $src 'aram_score.exe') `
    -Destination (Join-Path $target 'aram_score.exe') -Force
if (Test-Path (Join-Path $src 'README.txt')) {
    Copy-Item (Join-Path $src 'README.txt') `
        -Destination (Join-Path $target 'README.txt') -Force
}

# Guaranteed launcher: 启动红包乱斗.bat (no COM needed, always works)
$launcher = Join-Path $target '启动红包乱斗.bat'
@"
@echo off
"%~dp0aram_score.exe"
"@ | Set-Content -Path $launcher -Encoding ASCII

# Shortcuts via WScript.Shell (may be blocked in locked-down envs -> fallback)
function New-Shortcut($lnkPath, $desc) {
    $ws = New-Object -ComObject WScript.Shell
    $s  = $ws.CreateShortcut($lnkPath)
    $s.TargetPath       = Join-Path $target 'aram_score.exe'
    $s.WorkingDirectory = $target
    $s.Description       = $desc
    $s.Save()
}

$shortcutsOk = $true
try {
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    New-Shortcut (Join-Path $startMenu ($appName + '.lnk')) $appName
    $desktop = Join-Path $env:USERPROFILE 'Desktop'
    New-Shortcut (Join-Path $desktop ($appName + '.lnk')) $appName
} catch {
    $shortcutsOk = $false
    # Fallback: drop a launcher .bat on Desktop so the app is still reachable
    Copy-Item $launcher (Join-Path $env:USERPROFILE ('Desktop\' + $appName + '.bat')) -Force
}

Write-Host ''
Write-Host "Install finished. Program installed to: $target"
if ($shortcutsOk) {
    Write-Host "Shortcuts created in Start Menu and Desktop: '$appName'"
} else {
    Write-Host "Start Menu/Desktop shortcuts were blocked in this environment."
    Write-Host "Fallback: a '$appName.bat' launcher was placed on your Desktop."
}
Write-Host "Double-click the shortcut/launcher to run (auto-opens the scoring panel)."

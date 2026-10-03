$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$ws = New-Object -ComObject WScript.Shell
$startup = [System.Environment]::GetFolderPath('Startup')
$targetVbs = Join-Path $ScriptDir "start_silent.vbs"
$shortcutPath = Join-Path $startup "PromptAtelierWeb.lnk"

if (-not (Test-Path $targetVbs)) {
    throw "Target file not found: $targetVbs"
}

$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$targetVbs`""
$shortcut.WorkingDirectory = $ScriptDir
$shortcut.Description = "PromptAtelier Web Development Server"
$shortcut.Save()

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  [Success] PromptAtelier Web AutoStart Enabled!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "Shortcut : $shortcutPath" -ForegroundColor Yellow
Write-Host "Target   : $targetVbs" -ForegroundColor Yellow
Write-Host "Windows will silently launch the service upon next boot." -ForegroundColor Gray
Write-Host "=======================================================" -ForegroundColor Cyan

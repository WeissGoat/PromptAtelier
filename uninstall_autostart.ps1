$ErrorActionPreference = "Stop"
$startup = [System.Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startup "PromptAtelierWeb.lnk"

Write-Host "=======================================================" -ForegroundColor Cyan
if (Test-Path $shortcutPath) {
    Remove-Item -Force $shortcutPath
    Write-Host "  [Success] PromptAtelier Web AutoStart Shortcut Removed Successfully!" -ForegroundColor Green
} else {
    Write-Host "  [Info] PromptAtelier Web AutoStart Shortcut does not exist." -ForegroundColor Yellow
}
Write-Host "=======================================================" -ForegroundColor Cyan

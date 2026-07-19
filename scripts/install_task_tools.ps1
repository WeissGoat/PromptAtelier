param(
    [ValidateSet("install", "sync", "uninstall")]
    [string]$Mode = "install",
    [string]$Config = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$command = switch ($Mode) {
    "install" { "install-sendto" }
    "sync" { "sync-sendto" }
    "uninstall" { "uninstall-sendto" }
}
$arguments = @("run", "python", "-m", "tags_machine_core", "task-tools", $command)
if ($Config) {
    $arguments += @("--config", (Resolve-Path $Config).Path)
}

Push-Location $projectRoot
try {
    & uv @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

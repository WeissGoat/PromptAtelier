<#
Creates a Modal proxy token and stores it as a user environment variable
(default TM_COMFYUI_MODAL_TOKEN, read by comfyui.targets.modal.auth.token_env).
Modal shows the secret only once at creation; this script never prints it.

Run from the repository root:
  powershell -ExecutionPolicy Bypass -File deploy/comfyui/providers/modal_create_proxy_token.ps1
#>
param(
    [string]$Name = "tags-machine",
    [string]$EnvName = "TM_COMFYUI_MODAL_TOKEN"
)
$ErrorActionPreference = "Stop"

$output = modal workspace proxy-tokens create --name $Name --json
if ($LASTEXITCODE -ne 0) { throw "modal workspace proxy-tokens create failed" }
$token = ($output -join "`n") | ConvertFrom-Json
$tokenId = $token.'Modal-Key'
$tokenSecret = $token.'Modal-Secret'
if (-not $tokenId -or -not $tokenSecret) { throw "Unexpected output from modal; nothing was saved" }

[Environment]::SetEnvironmentVariable($EnvName, "$tokenId.$tokenSecret", "User")
Set-Item -Path "env:$EnvName" -Value "$tokenId.$tokenSecret"
Write-Host "Created proxy token '$Name' ($tokenId) and saved it to user environment variable $EnvName."
Write-Host "New terminals pick it up automatically; restart an already running web console."

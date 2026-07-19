param(
    [Parameter(Mandatory = $true)][ValidateSet("run", "launcher")][string]$Mode,
    [Parameter()][string]$OperationId = "",
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$InputPaths
)

$ErrorActionPreference = "Stop"
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $appDir "install.json"

try {
    $install = Get-Content -Raw -Encoding UTF8 -LiteralPath $manifestPath | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $install.pythonw_path)) {
        throw "Refactor Python 环境不存在：$($install.pythonw_path)"
    }
    $pythonPath = Join-Path (Split-Path -Parent $install.pythonw_path) "python.exe"
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "Refactor Python 环境不存在：$pythonPath"
    }

    $arguments = @("-m", "tags_machine_core", "task-tools", $Mode)
    if ($Mode -eq "run") {
        $arguments += $OperationId
    }
    if ($install.config_path) {
        $arguments += @("--config", $install.config_path)
    }
    $arguments += "--"
    $arguments += $InputPaths

    Push-Location $install.project_root
    try {
        # VBS 已经隐藏 PowerShell 窗口；使用 console Python 才能可靠读取退出码。
        & $pythonPath @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Refactor 任务工具执行失败，退出码：$LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        $_.Exception.Message,
        "Refactor 任务工具",
        "OK",
        "Error"
    ) | Out-Null
}

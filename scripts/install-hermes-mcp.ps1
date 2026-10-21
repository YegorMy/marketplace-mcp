#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectDir = "",
    [ValidateNotNullOrEmpty()]
    [string]$ServerName = "marketplaces",
    [ValidateNotNullOrEmpty()]
    [string]$UvBin = "uv"
)

$ErrorActionPreference = "Stop"
if (-not $ProjectDir) {
    $ProjectDir = Split-Path -Parent $PSScriptRoot
}
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "pyproject.toml") -PathType Leaf)) {
    throw "Project directory must contain pyproject.toml: $ProjectDir"
}

$UvCommand = Get-Command -Name $UvBin -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $UvCommand) {
    throw "uv is required. Install it first: https://docs.astral.sh/uv/"
}
$HermesCommand = Get-Command -Name hermes -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $HermesCommand) {
    throw "hermes CLI is required. Install Hermes and open a new terminal, then retry."
}
$UvPath = $UvCommand.Source

& $UvPath sync --frozen --project $ProjectDir
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed (exit code $LASTEXITCODE)."
}

$Configurator = Join-Path $ProjectDir "scripts/configure-hermes-mcp.py"
& $UvPath run --project $ProjectDir --with pyyaml python $Configurator "--project-dir=$ProjectDir" "--uv-bin=$UvPath" "--server-name=$ServerName"
if ($LASTEXITCODE -ne 0) {
    throw "Hermes configuration failed (exit code $LASTEXITCODE)."
}

& $HermesCommand.Source mcp test $ServerName
if ($LASTEXITCODE -ne 0) {
    throw "Hermes MCP test failed (exit code $LASTEXITCODE)."
}
Write-Host "Configured MCP server '$ServerName'. In Hermes run /reload-mcp or start a new chat."

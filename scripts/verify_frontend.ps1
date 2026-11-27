$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $ProjectRoot "frontend"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required. Install Node.js 20.19+ or 22.12+ first."
}

$NodeVersion = (& node --version).Trim().TrimStart("v")
$Major = [int]($NodeVersion.Split(".")[0])
$Minor = [int]($NodeVersion.Split(".")[1])
$SupportedNode = ($Major -eq 20 -and $Minor -ge 19) -or ($Major -eq 22 -and $Minor -ge 12) -or ($Major -ge 24)
if (-not $SupportedNode) {
    throw "Unsupported Node.js version $NodeVersion. Use Node.js 20.19+, 22.12+, or a supported later LTS release."
}

Push-Location $FrontendDir
try {
    Write-Host "`n========== MADAR FRONTEND VERIFICATION ==========" -ForegroundColor Cyan
    Write-Host "[1/3] Installing locked dependencies"
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }

    Write-Host "`n[2/3] ESLint"
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed." }

    Write-Host "`n[3/3] Production build"
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }

    Write-Host "`nFRONTEND VERIFICATION PASSED" -ForegroundColor Green
}
finally {
    Pop-Location
}

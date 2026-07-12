# NOVA Release Build Script
# Phase 14 § 1, M6 T-601
# Usage: .\scripts\build_release.ps1 -Version "1.0.0"

param(
    [Parameter(Mandatory=$true)]
    [string]$Version,

    [switch]$SkipTests = $false,
    [switch]$SkipClean = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Info { Write-Host "[BUILD] $args" -ForegroundColor Cyan }
function Write-Error { Write-Host "[ERROR] $args" -ForegroundColor Red }
function Write-Success { Write-Host "[OK] $args" -ForegroundColor Green }

$ProjectRoot = Split-Path $PSScriptRoot
$VenvPath = "$ProjectRoot\.venv.build"
$DistPath = "$ProjectRoot\dist"
$ReleasePath = "$ProjectRoot\dist\NOVA-v$Version"

try {
    Write-Info "Building NOVA v$Version..."

    # 1. Clean venv if needed
    if (-not $SkipClean -and (Test-Path $VenvPath)) {
        Write-Info "Removing old venv..."
        Remove-Item -Recurse -Force $VenvPath | Out-Null
    }

    # 2. Create fresh venv from lockfile
    Write-Info "Creating venv from uv.lock..."
    & uv venv "$VenvPath" --python 3.12 | Out-Null
    $PythonExe = "$VenvPath\Scripts\python.exe"

    # 3. Install dependencies
    Write-Info "Installing dependencies..."
    & uv sync --python "$PythonExe" --frozen | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

    # 4. Stamp version
    Write-Info "Stamping version $Version..."
    $VersionPy = @"
# NOVA version — stamped at build time by scripts/build_release.ps1
# DO NOT EDIT directly; regenerate via the build script.

__version__ = "$Version"
__version_info__ = ($(($Version -split '\.' | % {[int]$_}) -join ', '))
"@
    Set-Content -Path "$ProjectRoot\src\nova\_version.py" -Value $VersionPy -Encoding utf8

    # 5. Run full test suite (unless skipped)
    if (-not $SkipTests) {
        Write-Info "Running test suite (this may take a minute)..."
        & "$PythonExe" -m pytest --tb=short -q 2>&1 | Tee-Object -Variable TestOutput | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "Test suite failed (see output above)" }
        Write-Success "Tests passed"
    } else {
        Write-Info "Skipping tests (--SkipTests)"
    }

    # 6. Run PyInstaller
    Write-Info "Running PyInstaller..."
    & "$PythonExe" -m PyInstaller nova.spec --workpath="$ProjectRoot\.pyinstaller_build" --distpath="$DistPath" 2>&1 | Tee-Object -Variable BuildOutput | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (see output above)" }

    if (-not (Test-Path "$DistPath\NOVA")) {
        throw "PyInstaller did not produce NOVA\ directory at $DistPath\NOVA"
    }
    Write-Success "PyInstaller complete"

    # 7. Verify executable exists
    $ExePath = "$DistPath\NOVA\NOVA.exe"
    if (-not (Test-Path $ExePath)) {
        throw "NOVA.exe not found at $ExePath"
    }
    Write-Success "Executable verified: $ExePath"

    # 8. Create release archive
    Write-Info "Creating release archive..."
    $ZipPath = "$ProjectRoot\dist\NOVA-v$Version.zip"
    if (Test-Path $ZipPath) { Remove-Item $ZipPath }

    # Use PowerShell 7+ native zip if available, fall back to Compress-Archive
    if (Get-Command 7z -ErrorAction SilentlyContinue) {
        & 7z a -r $ZipPath "$DistPath\NOVA" | Out-Null
    } else {
        Compress-Archive -Path "$DistPath\NOVA" -DestinationPath $ZipPath -Force
    }

    if (-not (Test-Path $ZipPath)) {
        throw "Failed to create zip archive"
    }
    Write-Success "Archive created: $ZipPath"

    # 9. Generate checksums
    Write-Info "Generating checksums..."
    $ChecksumPath = "$ProjectRoot\dist\SHA256SUMS.txt"
    $Hash = (Get-FileHash -Path $ZipPath -Algorithm SHA256).Hash
    "$Hash  NOVA-v$Version.zip" | Out-File -Encoding utf8 $ChecksumPath
    Write-Success "Checksums written: $ChecksumPath"

    Write-Success "Release build complete!"
    Write-Info "Artifact: $ZipPath"
    Write-Info "Checksum: $ChecksumPath"
    Write-Info ""
    Write-Info "Next steps (Phase 14 §4):"
    Write-Info "  1. Run clean-VM smoke test (T-602)"
    Write-Info "  2. Verify download-unzip-run on a second machine"
    Write-Info "  3. Create GitHub Release with notes + checksums"

} catch {
    Write-Error $_
    exit 1
}

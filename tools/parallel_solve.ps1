Param(
  [int]$Stride = $env:NUMBER_OF_PROCESSORS,
  [int]$Limit = 10000000,
  [int]$Batch = 1000000,
  [string]$Out = "out"
)

# Collapsi local parallel solver runner (Windows, PowerShell)
# - Configures and builds native tools (solve_norm_db, collapsi_cpp)
# - Spawns N shard processes in parallel (one per CPU by default)
# - Merges and deduplicates the output into out\solved_norm.merged.db
# Usage:
#   pwsh -File .\tools\parallel_solve.ps1 [-Stride N] [-Limit L] [-Batch B] [-Out PATH]

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CpuCount {
  if ($env:NUMBER_OF_PROCESSORS) { return [int]$env:NUMBER_OF_PROCESSORS }
  else { return 1 }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$collapsiRoot = Split-Path -Parent $scriptRoot
$cppDir = Join-Path $collapsiRoot "cpp"
$buildDir = Join-Path $cppDir "build-ninja"
$solverExe = Join-Path $buildDir "solve_norm_db.exe"
$cppExe = Join-Path $buildDir "collapsi_cpp.exe"

Write-Host "[parallel_solve.ps1] Stride=$Stride Limit=$Limit Batch=$Batch Out=$Out"
Write-Host "[parallel_solve.ps1] Collapsi root: $collapsiRoot"

# Configure and build
$genArgs = @()
if (Get-Command ninja -ErrorAction SilentlyContinue) {
  $genArgs = @("-G","Ninja")
  Write-Host "[parallel_solve.ps1] Using Ninja generator"
} else {
  Write-Host "[parallel_solve.ps1] Ninja not found; using default CMake generator"
}

Write-Host "[parallel_solve.ps1] Configuring CMake..."
& cmake -S $cppDir -B $buildDir @genArgs -DCMAKE_BUILD_TYPE=Release

$parJobs = Get-CpuCount
Write-Host "[parallel_solve.ps1] Building native tools with -j $parJobs ..."
& cmake --build $buildDir --target solve_norm_db --config Release -- -j $parJobs
& cmake --build $buildDir --target collapsi_cpp --config Release -- -j $parJobs

# Export for optional Python usage
$env:COLLAPSI_CPP_EXE = (Resolve-Path $cppExe).Path
Write-Host "[parallel_solve.ps1] COLLAPSI_CPP_EXE=$($env:COLLAPSI_CPP_EXE)"

# Ensure output directory
if (-not (Test-Path $Out)) {
  New-Item -ItemType Directory -Force -Path $Out | Out-Null
}

# Launch shards
$procs = @()
Write-Host "[parallel_solve.ps1] Launching shard processes..."
for ($i=0; $i -lt $Stride; $i++) {
  $outFile = Join-Path $Out ("solved_norm.offset{0}.stride{1}.db" -f $i, $Stride)
  $args = @("--out", $outFile, "--stride", "$Stride", "--offset", "$i", "--limit", "$Limit", "--batch", "$Batch")
  $p = Start-Process -FilePath $solverExe -ArgumentList $args -PassThru
  $procs += $p
  Write-Host ("  shard {0}/{1} -> {2} (pid={3})" -f $i, $Stride, $outFile, $p.Id)
}

# Wait for all processes
Write-Host "[parallel_solve.ps1] Waiting for shards to complete..."
$failed = $false
foreach ($p in $procs) {
  try {
    Wait-Process -Id $p.Id
    $p.Refresh() | Out-Null
    if ($p.ExitCode -ne 0) {
      Write-Warning ("Process {0} exited with code {1}" -f $p.Id, $p.ExitCode)
      $failed = $true
    }
  } catch {
    Write-Warning ("Failed waiting for process {0}: {1}" -f $p.Id, $_.Exception.Message)
    $failed = $true
  }
}
if ($failed) {
  throw "One or more shard processes failed"
}

# Merge shards (binary-safe)
$merged = Join-Path $Out "solved_norm.merged.db"
$shards = Get-ChildItem -Path $Out -Filter "solved_norm.offset*.db" | Sort-Object Name
if (-not $shards -or $shards.Count -eq 0) {
  throw "No shard files found to merge in $Out"
}

Write-Host "[parallel_solve.ps1] Merging $($shards.Count) shard(s) into $merged ..."
# Binary-safe merge using FileStreams
$fsOut = [System.IO.File]::Open($merged, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try {
  foreach ($f in $shards) {
    $fsIn = [System.IO.File]::Open($f.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    try {
      $fsIn.CopyTo($fsOut)
    } finally {
      $fsIn.Dispose()
    }
  }
} finally {
  $fsOut.Dispose()
}

# Deduplicate merged DB (in place)
Write-Host "[parallel_solve.ps1] Deduplicating merged DB..."
& $solverExe --dedup $merged

Write-Host "[parallel_solve.ps1] DONE. Merged at $merged"

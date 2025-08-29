Param(
  [int]$Shards = [Environment]::ProcessorCount,
  [int]$PerShard,
  [int]$Total,
  [int]$Batch = 20000,
  [string]$OutDb = ".\data\solved_norm.db",
  [string]$PartsDir = ".\data\parts",
  [string]$LogsDir = ".\logs",
  [switch]$NoDedup,
  [switch]$NoCleanParts
)

# Resolve paths relative to repo root (parent of tools directory)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$root = [System.IO.Path]::GetFullPath((Join-Path $scriptDir ".."))
function Resolve-UnderRoot([string]$path){
  if([System.IO.Path]::IsPathRooted($path)){ return [System.IO.Path]::GetFullPath($path) }
  return [System.IO.Path]::GetFullPath((Join-Path $root $path))
}
$exe = [System.IO.Path]::GetFullPath((Join-Path $root "cpp\build-ninja\solve_norm_db.exe"))
if(-not (Test-Path $exe)){
  Write-Error ("solver not found: {0}" -f $exe)
  exit 1
}

if(-not $PerShard -and $Total){ $PerShard = [int][Math]::Ceiling($Total / [double]$Shards) }
if(-not $PerShard){ $PerShard = 1250 }

$absOut = Resolve-UnderRoot $OutDb
$absParts = Resolve-UnderRoot $PartsDir
$absLogs = Resolve-UnderRoot $LogsDir
New-Item -ItemType Directory -Force -Path $absParts | Out-Null
New-Item -ItemType Directory -Force -Path $absLogs | Out-Null

$recSize = 24
function Get-RecordCount([string]$path){
  if(-not (Test-Path $path)){ return 0 }
  $len = (Get-Item $path).Length
  return [int]([Math]::Floor($len / $recSize))
}

$startCount = Get-RecordCount $absOut
$t0 = Get-Date
$swTotal = [System.Diagnostics.Stopwatch]::StartNew()

Write-Output ("Launching shards: shards={0} perShard={1} batch={2}" -f $Shards,$PerShard,$Batch)
$procs = @()
$swShards = [System.Diagnostics.Stopwatch]::StartNew()
for($i=0;$i -lt $Shards;$i++){
  $part = Join-Path $absParts ("solved_norm.part{0}.db" -f $i)
  $log  = Join-Path $absLogs  ("shard{0}-{1}.log" -f $i,(Get-Date -Format "yyyyMMdd-HHmmss"))
  $args = @("--stride",$Shards,"--offset",$i,"--limit",$PerShard,"--batch",$Batch,"--out",$part,"--seen",$absOut)
  $p = Start-Process -FilePath $exe -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $log
  $procs += $p
}
Write-Output ("Waiting for {0} shards..." -f $procs.Count)
Wait-Process -Id ($procs | Select-Object -ExpandProperty Id)
$swShards.Stop()

if(-not (Test-Path $absOut)){
  New-Item -ItemType File -Path $absOut | Out-Null
}
$parts = Get-ChildItem -Path $absParts -Filter "*.db" | Sort-Object Name
$partsRecords = 0
foreach($p in $parts){ $partsRecords += Get-RecordCount $p.FullName }

Write-Output ("Merging {0} part files into {1}" -f $parts.Count,$absOut)
$swMerge = [System.Diagnostics.Stopwatch]::StartNew()
foreach($part in $parts){
  $in=[System.IO.File]::OpenRead($part.FullName)
  $out=[System.IO.File]::Open($absOut,[System.IO.FileMode]::Append,[System.IO.FileAccess]::Write,[System.IO.FileShare]::Read)
  try { $in.CopyTo($out) } finally { $in.Dispose(); $out.Dispose() }
}
$swMerge.Stop()

$dedupMs = 0
if(-not $NoDedup){
  Write-Output "Running dedup..."
  $swD = [System.Diagnostics.Stopwatch]::StartNew()
  & $exe --dedup $absOut
  $swD.Stop(); $dedupMs = $swD.ElapsedMilliseconds
}

$swClean = [System.Diagnostics.Stopwatch]::StartNew()
if(-not $NoCleanParts){
  Write-Output "Cleaning part files..."
  Get-ChildItem -Path $absParts -Filter "*.db" | Remove-Item -Force
}
$swClean.Stop()

$swTotal.Stop()
$endCount = Get-RecordCount $absOut
$added = $endCount - $startCount
$totalMs = $swTotal.ElapsedMilliseconds
$rate = if($totalMs -gt 0){ [Math]::Round(($added * 1000.0 / $totalMs),3) } else { 0 }

Write-Output ("metrics start={0} parts={1} end={2} added={3}" -f $startCount,$partsRecords,$endCount,$added)
Write-Output ("timings total_ms={0} shards_ms={1} merge_ms={2} dedup_ms={3} clean_ms={4} rate_per_s={5}" -f $totalMs,$swShards.ElapsedMilliseconds,$swMerge.ElapsedMilliseconds,$dedupMs,$swClean.ElapsedMilliseconds,$rate)
Write-Output "Done."



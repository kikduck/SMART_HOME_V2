# Lance les 4 benchmarks (A1, A2, B1, B2)
# Usage: .\run_all_parallel.ps1          -> sequentiel (recommandé, serveur 1 seul slot)
#        .\run_all_parallel.ps1 -Parallel -> parallele (risque 500 si serveur surchargé)
# Pre-requis: llama-server demarre sur port 8083 (avec -c 4096 recommandé pour éviter context exceeded)

param([switch]$Parallel)

$base = Split-Path -Parent $PSScriptRoot
Set-Location $base

$runs = @(
    @{ Cases = "benchmarks/cases_A1.jsonl"; State = $null; Out = "benchmarks/reports/2B_all_A1.json" },
    @{ Cases = "benchmarks/cases_A2.jsonl"; State = $null; Out = "benchmarks/reports/2B_all_A2.json" },
    @{ Cases = "benchmarks/cases_B1.jsonl"; State = "knowledge/home_state_B.json"; Out = "benchmarks/reports/2B_all_B1.json" },
    @{ Cases = "benchmarks/cases_B2.jsonl"; State = "knowledge/home_state_B.json"; Out = "benchmarks/reports/2B_all_B2.json" }
)

$commonArgs = @("--decompose", "--entity-filter", "--no-start-server")

if ($Parallel) {
    Write-Host "Lancement en PARALLELE (peut surcharger le serveur)..."
    $procs = @()
    foreach ($r in $runs) {
        $args = @("benchmarks/run_benchmark_v2.py", "--cases", $r.Cases) + $commonArgs + @("--output", $r.Out)
        if ($r.State) { $args += @("--home-state", $r.State) }
        $procs += Start-Process -FilePath "python" -ArgumentList $args -PassThru -WorkingDirectory $base -NoNewWindow
    }
    Write-Host "PIDs: $($procs.Id -join ', ')"
    $procs | Wait-Process
} else {
    Write-Host "Lancement SEQUENTIEL..."
    foreach ($r in $runs) {
        $args = @("benchmarks/run_benchmark_v2.py", "--cases", $r.Cases) + $commonArgs + @("--output", $r.Out)
        if ($r.State) { $args += @("--home-state", $r.State) }
        & python @args
    }
}

Write-Host "Termine. Rapports dans benchmarks/reports/2B_all_*.json"

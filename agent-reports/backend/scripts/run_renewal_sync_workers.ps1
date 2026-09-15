$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $PSScriptRoot
Set-Location $Backend
$env:PYTHONPATH = $Backend
$env:PYTHONUNBUFFERED = "1"

$splits = @(
    "C9:NEW",
    "C9:UC_D741T1,C9:UC_2K6PKD,C9:UC_4UL8U1",
    "C9:UC_J5K36J,C9:UC_POOVSR,C9:UC_AEF7BS,C9:UC_UU1TA3",
    "C9:UC_DFB2KB,C9:UC_B8A27G,C9:UC_CUSEPM,C9:UC_DO7BK8,C9:UC_QP6G66,C9:UC_D20ZZG,C9:UC_PPKS2U,C9:UC_ZI2JUI"
)

for ($i = 0; $i -lt 4; $i++) {
    $n = $i + 1
    $err = Join-Path $Backend "renewal-sync-w$n.err.log"
    $out = Join-Path $Backend "renewal-sync-w$n.log"
    Start-Process -WorkingDirectory $Backend -FilePath "python" `
        -ArgumentList @("scripts/bulk_link_renewal_deal_phones.py", "--stages", $splits[$i]) `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err `
        -WindowStyle Hidden
    Write-Host "worker $n stages: $($splits[$i])"
}

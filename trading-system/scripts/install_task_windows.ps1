<#
    윈도우 작업 스케줄러에 자동 실행을 등록합니다.

    사용법 (PowerShell 에서):
        cd trading-system
        powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1          # 미리보기
        powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Apply   # 등록
        powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Remove  # 삭제

    ── 왜 30분마다 하루 종일 도는가 ──
    미국은 서머타임이 있어서 ET 와 한국시간의 차이가 14시간과 16시간
    사이를 오갑니다. 한국시간으로 "밤 10시 30분"을 박아두면 1년에 두 번
    한 시간씩 어긋납니다.

    그래서 예약은 넉넉하게 걸고, 실제로 실행할지는 파이썬이 ET 를 직접
    보고 판단합니다(src/market_time.py). 시간대 밖이면 한 줄 찍고 즉시
    끝나므로 컴퓨터에 부담이 없습니다.

    ⚠️ 컴퓨터가 켜져 있고 잠들지 않아야 실행됩니다.
       제어판 > 전원 옵션에서 절전을 "안 함" 으로 두세요.
#>

param(
    [switch]$Apply,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$LogDir     = Join-Path $ProjectDir "output\logs"
$TaskPrefix = "TradingSystem"

# 가상환경이 있으면 그 파이썬을, 없으면 시스템 파이썬을 씁니다.
$VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if (-not $found) {
        Write-Error "python 을 찾지 못했습니다. 파이썬을 설치하고 PATH 에 추가해 주세요."
    }
    $PythonExe = $found.Source
}

$Tasks = @(
    @{ Name = "$TaskPrefix-ScanA"; Args = "-m src.cli scan-a"; Every = 30; Log = "scan_a.log" }
    @{ Name = "$TaskPrefix-ScanB"; Args = "-m src.cli scan-b"; Every = 60; Log = "scan_b.log" }
)

if ($Remove) {
    foreach ($t in $Tasks) {
        if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
            Write-Host "삭제: $($t.Name)"
        }
    }
    Write-Host "완료."
    exit 0
}

if (-not $Apply) {
    Write-Host "아래 작업이 등록됩니다. 실제 등록은 -Apply 를 붙이세요."
    Write-Host ""
    Write-Host "  파이썬 : $PythonExe"
    Write-Host "  폴더   : $ProjectDir"
    Write-Host "  로그   : $LogDir"
    Write-Host ""
    foreach ($t in $Tasks) {
        Write-Host ("  {0,-24} 평일 {1}분마다  →  {2}" -f $t.Name, $t.Every, $t.Args)
    }
    Write-Host ""
    Write-Host "  실제 실행 여부는 파이썬이 미국 동부시간을 보고 판단합니다."
    Write-Host "  (스캐너 A: ET 08:30~14:00 / 스캐너 B: ET 10:00~15:05, 평일만)"
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

foreach ($t in $Tasks) {
    $logPath = Join-Path $LogDir $t.Log
    # cmd /c 로 감싸야 표준출력을 로그 파일로 넘길 수 있습니다.
    $command = "`"$PythonExe`" $($t.Args) >> `"$logPath`" 2>&1"

    $action = New-ScheduledTaskAction -Execute "cmd.exe" `
        -Argument "/c $command" -WorkingDirectory $ProjectDir

    $trigger = New-ScheduledTaskTrigger -Daily -At "00:05"
    $trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "00:05" `
        -RepetitionInterval (New-TimeSpan -Minutes $t.Every) `
        -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 55)).Repetition

    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -DontStopOnIdleEnd `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -MultipleInstances IgnoreNew

    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
    }

    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
        -Settings $settings -Description "종목 자동 분석 시스템 — $($t.Args)" | Out-Null

    Write-Host "등록: $($t.Name)  (평일 $($t.Every)분마다)"
}

Write-Host ""
Write-Host "완료. 확인:  Get-ScheduledTask -TaskName '$TaskPrefix-*'"
Write-Host "로그 위치:   $LogDir"
Write-Host ""
Write-Host "⚠️ 컴퓨터가 켜져 있고 절전에 들어가지 않아야 실행됩니다."

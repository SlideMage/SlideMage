# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Starts every GitHub Actions runner of this computer for a signed release (docs/CODE_SIGNING.md): each folder
# C:\actions-runner, C:\actions-runner-2, ... that holds a configured runner gets its run.cmd started in a window of
# its own. Two runners let the Windows build and the Windows Presenter jobs run at the same time.
#
# Then it waits and closes them again (user, 2026-11-28): once a Release run that started after the runners has
# finished and no runner is busy, it stops the runners, which closes their windows. Without any Release run within
# -WaitForReleaseMinutes it closes them too. It needs the GitHub CLI (gh), logged in. Ctrl+C in this window stops the
# waiting and leaves the runners open; -KeepOpen does the same from the start.
#
#   pwsh packaging/start_signing_runners.ps1                  # start, wait for the release, close
#   pwsh packaging/start_signing_runners.ps1 -KeepOpen        # start only (close the windows yourself)
#   pwsh packaging/start_signing_runners.ps1 -StopOnly        # close running runners now
param(
    [switch] $KeepOpen,
    [switch] $StopOnly,
    [int] $WaitForReleaseMinutes = 120,
    [string] $Repository = 'SlideMage/SlideMage'
)
$ErrorActionPreference = 'Stop'

function Stop-Runners {
    # The listener of each runner folder and the run.cmd window around it.
    $listeners = Get-Process Runner.Listener -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like 'C:\actions-runner*' }
    $windows = Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'cmd.exe' -and $_.CommandLine -match 'actions-runner' }
    foreach ($listener in $listeners) { Stop-Process -Id $listener.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    foreach ($window in $windows) { Stop-Process -Id $window.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "closed $(@($listeners).Count) runner(s)"
}

if ($StopOnly) { Stop-Runners; return }

$folders = Get-ChildItem C:\ -Directory -Filter 'actions-runner*' |
    Where-Object { Test-Path (Join-Path $_.FullName '.runner') } | Sort-Object Name
if (-not $folders) { throw 'No configured runner in C:\actions-runner* (docs/CODE_SIGNING.md, "Runner").' }

$certificate = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -like '*Open Source Developer*' }
if (-not $certificate) {
    Write-Warning 'The signing certificate is not visible: log in to SimplySign Desktop first, or the signing steps fail.'
}
# The runners inherit this process's environment. Started from PowerShell 7, PSModulePath names PowerShell 7's
# modules, and the Windows PowerShell 5.1 that actions/setup-python unpacks with then loads PowerShell 7's
# Microsoft.PowerShell.Archive and fails ("Expand-Archive ... MethodCountCouldNotFindBest", found 2026-11-28). So the
# runners get the computer's and the user's own module path, as a fresh login has it.
# Only for the runners: this script's own waiting loop needs PowerShell 7's modules (ConvertFrom-Json), so the path is
# put back right after (v0.18.8's release: the loop failed silently and the runners never closed).
$ownModulePath = $env:PSModulePath
$env:PSModulePath = @([Environment]::GetEnvironmentVariable('PSModulePath', 'User'),
                      [Environment]::GetEnvironmentVariable('PSModulePath', 'Machine')) -ne $null -join ';'
$started = (Get-Date).ToUniversalTime()
try {
    foreach ($folder in $folders) {
        Start-Process -FilePath (Join-Path $folder.FullName 'run.cmd') -WorkingDirectory $folder.FullName
        Write-Host "started $($folder.Name)"
    }
} finally {
    $env:PSModulePath = $ownModulePath
}
if ($KeepOpen) { return }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Warning 'gh (GitHub CLI) is not installed: the runners stay open; close their windows after the release.'
    return
}

Write-Host "Waiting for a Release run of $Repository; the runners close when it is done (Ctrl+C: leave them open)."
$deadline = $started.AddMinutes($WaitForReleaseMinutes)
$seen = $false
$failures = 0
while ($true) {
    Start-Sleep -Seconds 30
    try {
        $runs = gh run list -R $Repository --workflow release.yml --limit 10 --json databaseId,status,createdAt |
            ConvertFrom-Json
        $busy = gh api "repos/$Repository/actions/runners" --jq '[.runners[] | select(.busy)] | length'
        $failures = 0
    } catch {
        # GitHub unreachable for a moment: ask again, but say so, and give up waiting after ten tries in a row.
        $failures++
        Write-Warning "Could not read the Release runs ($failures): $_"
        if ($failures -ge 10) {
            Write-Warning 'Giving up waiting: the runners stay open; close them with -StopOnly after the release.'
            return
        }
        continue
    }
    $ours = @($runs | Where-Object { ([datetime]$_.createdAt).ToUniversalTime() -ge $started.AddMinutes(-1) })
    if ($ours) { $seen = $true }
    $open = @($ours | Where-Object { $_.status -ne 'completed' })
    if ($seen -and -not $open -and [int]$busy -eq 0) {
        Write-Host "Release run(s) $(($ours.databaseId) -join ', ') finished."
        Stop-Runners
        return
    }
    if (-not $seen -and (Get-Date).ToUniversalTime() -gt $deadline) {
        Write-Host "No Release run within $WaitForReleaseMinutes minutes."
        Stop-Runners
        return
    }
}

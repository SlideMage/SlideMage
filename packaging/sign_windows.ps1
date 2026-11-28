# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Authenticode-signs Windows programs with SlideMage's Certum code signing certificate (task windows-code-signing,
# docs/CODE_SIGNING.md). release.yml runs it on the self-hosted runner "certum" when the repository variable
# SLIDEMAGE_CODE_SIGNING is "on": for SlideMage.exe (folder and single file), SlideMagePresenter.exe, and through
# Inno Setup's SignTool for SlideMage-Setup.exe and its uninstaller.
#
#   pwsh packaging/sign_windows.ps1 FILE...          sign each file, then verify it
#   pwsh packaging/sign_windows.ps1 -Check           only check the setup: signtool, the certificate, SimplySign
#
# The certificate lives in Certum's cloud (SimplySign). SimplySign Desktop, logged in on the runner's computer, makes
# it appear in the user's certificate store like one on a card; signtool finds it by its SHA-1 thumbprint, the
# repository variable SLIDEMAGE_SIGNING_CERT_SHA1 (not a secret: the certificate is public). No private key and no
# login code is ever on GitHub.
param(
    [switch] $Check,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]] $Files
)
$ErrorActionPreference = 'Stop'

$TimestampUrl = 'http://time.certum.pl'
$Thumbprint = ($env:SLIDEMAGE_SIGNING_CERT_SHA1 -replace '\s', '').ToUpperInvariant()

function Find-Signtool {
    $onPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    $found = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
    throw 'signtool.exe not found: install the Windows SDK''s "Signing Tools for Desktop Apps" (docs/CODE_SIGNING.md)'
}

if (-not $Thumbprint) {
    throw 'SLIDEMAGE_SIGNING_CERT_SHA1 is empty: set the repository variable to the certificate''s thumbprint'
}
$signtool = Find-Signtool
$certificate = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Thumbprint -eq $Thumbprint } | Select-Object -First 1
if (-not $certificate) {
    throw "The certificate $Thumbprint is not in the user's certificate store: is SimplySign Desktop running and " +
          'logged in (with a code from the SimplySign app) on this computer?'
}
if ($certificate.NotAfter -lt (Get-Date)) { throw "The certificate $Thumbprint expired on $($certificate.NotAfter)" }
Write-Host "signtool: $signtool"
Write-Host "certificate: $($certificate.Subject), valid until $($certificate.NotAfter)"
if ($Check) { exit 0 }
if (-not $Files) { throw 'no files to sign' }

foreach ($file in $Files) {
    $path = (Resolve-Path $file).Path
    $signed = $false
    # The timestamp server sometimes refuses a request; a signature without a timestamp would end with the
    # certificate, so a failed timestamp is retried, never skipped.
    for ($attempt = 1; $attempt -le 3 -and -not $signed; $attempt++) {
        & $signtool sign /sha1 $Thumbprint /fd sha256 /tr $TimestampUrl /td sha256 /d SlideMage /du https://slidemage.org $path
        if ($LASTEXITCODE -eq 0) { $signed = $true } else { Start-Sleep -Seconds (10 * $attempt) }
    }
    if (-not $signed) { throw "signing $path failed three times" }
    & $signtool verify /pa /tw $path
    if ($LASTEXITCODE -ne 0) { throw "the signature of $path does not verify" }
}

# Windows code signing

SlideMage's Windows programs are signed with a Certum "Open Source Code Signing in the Cloud" certificate
("Open Source Developer Stefan Palan", 365 days, ordered 2026-11-24, activated 2026-11-28). Windows then names the
publisher instead of "Unknown publisher", and SmartScreen builds a reputation for the signed files.

What gets signed, by `.github/workflows/release.yml` through `packaging/sign_windows.ps1`:

| File | Where |
|---|---|
| `SlideMage.exe` of the folder build | before `SlideMage-windows-folder.zip` and its `.sig` are made |
| `SlideMage.exe`, the single file | before `SlideMage-windows.zip` and its `.sig` |
| `SlideMage-Setup.exe` and its uninstaller | by Inno Setup's SignTool (`packaging/slidemage.iss`, `SignToolName`) |
| `SlideMagePresenter.exe` | before `SlideMagePresenter-windows.zip` |

Every signature gets a timestamp from Certum (`http://time.certum.pl`), so it stays valid after the certificate expires.
This is separate from the release signature (`<zip>.sig`, `src/slidemage/release_signing.py`), which the updater checks:
both are made, the Authenticode signature first.

## How it works

The private key never leaves Certum's cloud. **SimplySign Desktop**, logged in on a computer, makes the certificate
appear in that Windows user's certificate store as if it were on a smart card; `signtool` signs with it there. So the
Windows build jobs run on a **self-hosted GitHub Actions runner** on that computer (label `certum`), started by you
when you release. Neither GitHub nor the repository holds a key or a login code. Decided 2026-11-24: no automation of
the SimplySign login code, no `ssign`.

Two repository variables (Settings → Secrets and variables → Actions → **Variables**) control it:

| Variable | Value |
|---|---|
| `SLIDEMAGE_CODE_SIGNING` | `on` to sign; anything else or unset: the Windows jobs run on GitHub's runner, unsigned |
| `SLIDEMAGE_SIGNING_CERT_SHA1` | the certificate's thumbprint (public, not a secret) |

## Setting up a computer (the private PC, the work laptop)

The SimplySign Desktop licence covers one computer and one portable device, not both at the same time.

1. **SimplySign account** (once): Certum creates the account `info@slidemage.org` when it issues the certificate and
   mails how to set it up. Install the **SimplySign** app on your phone and connect it to the account: it shows the
   one-time codes SimplySign Desktop asks for.
2. **SimplySign Desktop**: download it from Certum's support pages (support.certum.eu, "SimplySign Desktop"), install,
   log in with `info@slidemage.org` and a code from the app. Check that the certificate is there, and note its
   thumbprint:

   ```powershell
   Get-ChildItem Cert:\CurrentUser\My | Where-Object Subject -like '*Open Source Developer*' | Format-List Subject, Thumbprint, NotAfter
   ```

3. **Tools**: Git, PowerShell 7 (`winget install Microsoft.PowerShell`), Inno Setup 6
   (`winget install JRSoftware.InnoSetup`; it installs for the current user, `%LOCALAPPDATA%\Programs\Inno Setup 6`,
   which the workflow finds), `signtool.exe` from the Windows SDK (the installer's feature
   "Windows SDK Signing Tools for Desktop Apps"; `winget install --id Microsoft.WindowsSDK.10.0.26100 --override
   "/features OptionId.SigningTools /quiet /norestart"` installs only that), and **Python 3.12 for the current user**
   (`winget install --id Python.Python.3.12 --scope user`, into `%LOCALAPPDATA%\Programs\Python\Python312`). On this
   runner the workflow does not use `actions/setup-python` (on the laptop its installer failed, 2026-11-28) but that
   Python, in a fresh virtual environment per job; keep it at 3.12, as on GitHub's runners. The Microsoft Store's
   Python does not do: sandboxed, another version, updated by the Store. (Windows PowerShell's script policy was set
   to RemoteSigned for the user on the laptop while trying `setup-python`; the workflow no longer needs it.)
4. **Runner**: on GitHub, SlideMage/SlideMage → Settings → Actions → Runners → **New self-hosted runner**, Windows,
   x64. Follow the shown commands into a folder of its own (e.g. `C:\actions-runner`) and give it the label
   `certum` when `config.cmd` asks for additional labels. Answer **no** to "run as service": a service runs as another
   Windows user, which does not see your SimplySign certificate. You start it yourself with `run.cmd` when you release.
   **A second runner on the same computer** (user, 2026-11-28): repeat this into `C:\actions-runner-2`, with a name of
   its own (e.g. `<computer>-2`) and the same label `certum`. A runner does one job at a time; with two, the Windows
   build and the Windows Presenter run at the same time (on one runner they wait for each other). Both use the same
   SimplySign login.
   Register both computers this way; whichever runners are running take the jobs.
5. **Variables** (once): set `SLIDEMAGE_SIGNING_CERT_SHA1` to the thumbprint from step 2, then
   `SLIDEMAGE_CODE_SIGNING` to `on`.

Check a computer before the first release: in PowerShell, in a SlideMage checkout,

```powershell
$env:SLIDEMAGE_SIGNING_CERT_SHA1 = '<thumbprint>'; .\packaging\sign_windows.ps1 -Check
```

## Each release

1. Log in to SimplySign Desktop (a code from the app).
2. Start the runners: `pwsh packaging/start_signing_runners.ps1` in a SlideMage checkout opens a window per runner
   folder (`C:\actions-runner*`); each says "Listening for Jobs". Use the script rather than `run.cmd` from a
   PowerShell 7 window: it starts the runners with Windows' own module path (inherited from PowerShell 7, that path
   makes the Windows PowerShell that installs Python fail with "Expand-Archive ... MethodCountCouldNotFindBest").
3. Push the tag as usual (`packaging/make_release.py`). The Windows jobs wait for the runners; the Linux and macOS
   jobs run on GitHub meanwhile. The Presenter is built only when it (or release.yml) changed since the previous
   release, so often only the Windows build comes to the laptop. Expect about a quarter of an hour; the first run on
   a runner takes longer (it installs Python and SlideMage's packages, kept for later runs).
4. Keep the computer awake until the Windows jobs are done. The script closes the runner windows by itself once the
   Release run has finished (or when none started within two hours; it needs `gh`, logged in). `-KeepOpen` leaves
   them open, `-StopOnly` closes running ones at once, Ctrl+C in the script's window stops the waiting.

The first Windows step, "Code signing ready", fails at once with a clear message when SimplySign Desktop is not
logged in or the thumbprint is wrong. A SimplySign session that ends during a run fails the signing step: log in
again and re-run the failed jobs.

Without the runner, a release can still go out unsigned: set `SLIDEMAGE_CODE_SIGNING` to `off` first.

## Safety

- The runner runs workflow code from this repository under your Windows account, with your SimplySign session. Only
  `release.yml` uses it, and that workflow runs only for tags and manual starts, never for pull requests, so code from
  a fork cannot reach it. Never add `certum` to `runs-on` in `ci.yml` or any workflow that runs for pull requests.
- The release job also passes the secret `SLIDEMAGE_RELEASE_SIGNING_KEY` to that computer, as it does to GitHub's
  runners.
- The setup's smoke test does not run on the signing runner (it would install and uninstall SlideMage for your Windows
  user); every unsigned run on GitHub's runner tests the same setup.

## Checking a signature

Right-click the file → Properties → Digital Signatures, or

```powershell
Get-AuthenticodeSignature .\SlideMage-Setup.exe | Format-List Status, SignerCertificate, TimeStamperCertificate
```

## Renewal

The certificate is valid for 365 days. Renew it in the Certum shop before it expires, then update
`SLIDEMAGE_SIGNING_CERT_SHA1` to the new thumbprint. Files signed before stay valid (timestamp).

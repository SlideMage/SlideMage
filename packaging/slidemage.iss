; SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
; SPDX-License-Identifier: GPL-3.0-or-later
;
; SlideMage-Setup.exe: installs SlideMage for the current user (no administrator rights) with what it needs to
; compile: MiKTeX and SlideMage's TeX packages, and Perl for latexmk. Built by release.yml with Inno Setup 6:
;
;   iscc /DAppVersion=0.18.6 /DSourceDir=..\dist\SlideMage-folder packaging\slidemage.iss
;   (signed, as release.yml does on the "certum" runner: /DSignToolName=certum
;    "/Scertum=pwsh.exe -NoProfile -ExecutionPolicy Bypass -File <repo>\packaging\sign_windows.ps1 $f"; docs/CODE_SIGNING.md)
;
; What it does, after listing it on the "Ready" page:
;   * SlideMage's folder build to %LOCALAPPDATA%\Programs\SlideMage, the folder SlideMage updates itself in. The
;     uninstaller lives beside it (UninstallFilesDir), not inside: SlideMage's updater replaces the app folder as a
;     whole, which would delete an uninstaller kept there.
;   * No TeX found: MiKTeX through winget (per user), automatic package installation switched on, then the packages
;     of packaging/tex-requirements.toml (slidemage-tex.iss). An existing MiKTeX only gets the packages it lacks
;     (miktex packages require); TeX Live is left alone and the missing files are named at the end.
;   * No Perl (on PATH, in Git for Windows, or a Strawberry Perl): portable Strawberry Perl, per user, from its
;     GitHub release, checked against the SHA-256 below. SlideMage finds it there (src/slidemage/tex_paths.py).
;   * No winget, or a download fails: the links to install by hand; SlideMage is installed anyway.
;   * Last: SlideMage.exe --self-test --compile (a deck per layout with a citation), log in the setup's temp folder.
; Running it again repairs or updates the installation; projects and settings (%APPDATA%\SlideMage) are never touched.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\SlideMage-folder"
#endif
#include "slidemage-tex.iss"

; Portable Strawberry Perl (GitHub release SP_54231_64bit; digest from the GitHub release API, 2026-11-27).
#define PerlUrl "https://github.com/StrawberryPerl/Perl-Dist-Strawberry/releases/download/SP_54231_64bit/strawberry-perl-5.42.3.1-64bit-portable.zip"
#define PerlSha256 "6a081a811781c30aca51dbc036afd93092af91e3297901f02c17043795a10690"
#define PerlDownloadMB "305"

[Setup]
AppId={{6F2B8C41-3D7A-4E59-9B1C-5A0E7D2F4C83}
AppName=SlideMage
AppVersion={#AppVersion}
AppVerName=SlideMage {#AppVersion}
AppPublisher=Stefan Palan, Jürgen Fleiß
AppPublisherURL=https://slidemage.org
AppSupportURL=https://github.com/SlideMage/SlideMage/issues
DefaultDirName={localappdata}\Programs\SlideMage
DisableDirPage=yes
DisableProgramGroupPage=yes
UninstallFilesDir={localappdata}\Programs\SlideMage-setup
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\out
OutputBaseFilename=SlideMage-Setup
SetupIconFile=..\src\slidemage\assets\icon.ico
UninstallDisplayIcon={app}\SlideMage.exe
UninstallDisplayName=SlideMage
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Tasks]
Name: desktopicon; Description: "Create a desktop icon"; Flags: unchecked
Name: miktex; Description: "Install MiKTeX (TeX for Windows, per user) and the TeX packages SlideMage needs"; Check: TexMissing
Name: texpackages; Description: "Add the TeX packages SlideMage needs to MiKTeX (only those missing)"; Check: MiktexPresent
Name: perl; Description: "Install Perl for latexmk (portable Strawberry Perl, a {#PerlDownloadMB} MB download)"; Check: PerlMissing

[InstallDelete]
; A repair or an update over an older version: no file of the old build stays behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SlideMage"; Filename: "{app}\SlideMage.exe"
Name: "{autodesktop}\SlideMage"; Filename: "{app}\SlideMage.exe"; Tasks: desktopicon

[UninstallDelete]
; Also what SlideMage's own updates left: files the setup did not install, and the updater's sibling folders.
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{app}.old"
Type: filesandordirs; Name: "{app}.update"

[Run]
Filename: "{app}\SlideMage.exe"; Description: "Start SlideMage"; Flags: postinstall nowait skipifsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;
  SelfTestMessage: String;

{ --- finding programs: PATH as the registry has it now, and the usual installation folders ------------------- }

function RegistryPath(): String;
var
  UserPath, SystemPath: String;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', UserPath) then UserPath := '';
  if not RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', SystemPath) then SystemPath := '';
  Result := UserPath + ';' + SystemPath;
end;

function KnownDirs(): String;
var
  Year: Integer;
begin
  Result := ExpandConstant('{localappdata}\Programs\MiKTeX\miktex\bin\x64') + ';' +
            ExpandConstant('{commonpf64}\MiKTeX\miktex\bin\x64') + ';' +
            ExpandConstant('{localappdata}\Programs\StrawberryPerl\perl\bin') + ';C:\Strawberry\perl\bin';
  for Year := 2035 downto 2020 do
    Result := Result + ';C:\texlive\' + IntToStr(Year) + '\bin\windows;C:\texlive\' + IntToStr(Year) + '\bin\win64';
end;

function FindProgram(Name: String): String;
var
  Dirs, Dir: String;
  Cut: Integer;
begin
  Result := '';
  Dirs := GetEnv('PATH') + ';' + RegistryPath() + ';' + KnownDirs() + ';';
  while Dirs <> '' do
  begin
    Cut := Pos(';', Dirs);
    Dir := Trim(Copy(Dirs, 1, Cut - 1));
    Delete(Dirs, 1, Cut);
    StringChangeEx(Dir, '"', '', True);
    if (Dir <> '') and FileExists(AddBackslash(Dir) + Name) then
    begin
      Result := AddBackslash(Dir) + Name;
      Exit;
    end;
  end;
end;

{ Git for Windows' perl, which MiKTeX's latexmk finds through SlideMage (compiler._find_git_perl_bin). }
function GitPerl(): String;
var
  Dir: String;
begin
  Result := '';
  Dir := ExtractFileDir(FindProgram('git.exe'));
  while (Dir <> '') and (Length(Dir) > 3) do
  begin
    if FileExists(Dir + '\usr\bin\perl.exe') then
    begin
      Result := Dir + '\usr\bin\perl.exe';
      Exit;
    end;
    Dir := ExtractFileDir(Dir);
  end;
end;

function TexMissing(): Boolean;
begin
  Result := FindProgram('lualatex.exe') = '';
end;

function MiktexPresent(): Boolean;
begin
  Result := (not TexMissing()) and (FindProgram('miktex.exe') <> '');
end;

function PerlMissing(): Boolean;
begin
  Result := (FindProgram('perl.exe') = '') and (GitPerl() = '');
end;

{ --- running programs ------------------------------------------------------------------------------------------ }

function RunLogged(Exe, Params, Status: String): Integer;
var
  LogFile: String;
  Code: Integer;
begin
  LogFile := ExpandConstant('{tmp}\setup-steps.log');
  WizardForm.StatusLabel.Caption := Status;
  if not Exec(ExpandConstant('{cmd}'), '/c ""' + Exe + '" ' + Params + ' >> "' + LogFile + '" 2>&1"', '',
              SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  Log(Exe + ' ' + Params + ' -> ' + IntToStr(Code));
  Result := Code;
end;

procedure InstallMiktex();
var
  Winget: String;
begin
  Winget := FindProgram('winget.exe');
  if Winget = '' then Winget := ExpandConstant('{localappdata}\Microsoft\WindowsApps\winget.exe');
  if FileExists(Winget) then
    RunLogged(Winget, 'install --id MiKTeX.MiKTeX --exact --silent --accept-source-agreements ' +
              '--accept-package-agreements --disable-interactivity', 'Installing MiKTeX (several minutes) ...');
  if FindProgram('miktex.exe') = '' then
    SuppressibleMsgBox('MiKTeX could not be installed automatically' + #13#10 +
      '(winget is missing or the installation failed).' + #13#10#13#10 +
      'Install it from https://miktex.org/download, then start SlideMage: it finds MiKTeX by itself.',
      mbInformation, MB_OK, IDOK);
end;

procedure AddMiktexPackages(Fresh: Boolean);
var
  Miktex, Initexmf: String;
begin
  Miktex := FindProgram('miktex.exe');
  if Miktex = '' then Exit;
  RunLogged(Miktex, 'packages update-package-database', 'Updating the MiKTeX package list ...');
  if Fresh then
  begin
    { Missing packages then install while compiling, without a question each time. }
    Initexmf := FindProgram('initexmf.exe');
    if Initexmf <> '' then
      RunLogged(Initexmf, '--set-config-value=[MPM]AutoInstall=1', 'Setting up MiKTeX ...');
  end;
  if RunLogged(Miktex, 'packages require {#MiktexPackages}', 'Installing the TeX packages SlideMage needs ...') <> 0 then
    SuppressibleMsgBox('Some TeX packages could not be installed now (see ' + ExpandConstant('{tmp}') +
      '\setup-steps.log).' + #13#10 + 'MiKTeX installs missing packages when SlideMage compiles.',
      mbInformation, MB_OK, IDOK);
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InstallPerl();
var
  Target: String;
  Code: Integer;
begin
  Target := ExpandConstant('{localappdata}\Programs\StrawberryPerl');
  DownloadPage.Clear;
  DownloadPage.Add('{#PerlUrl}', 'strawberry-perl-portable.zip', '{#PerlSha256}');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;   { checks the SHA-256 }
      ForceDirectories(Target);
      WizardForm.StatusLabel.Caption := 'Unpacking Perl ...';
      if not Exec(ExpandConstant('{sys}\tar.exe'), '-xf "' + ExpandConstant('{tmp}\strawberry-perl-portable.zip') +
                  '" -C "' + Target + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
        RaiseException('unpacking failed (' + IntToStr(Code) + ')');
    except
      SuppressibleMsgBox('Perl could not be installed: ' + GetExceptionMessage + #13#10#13#10 +
        'latexmk needs Perl. Install Strawberry Perl (https://strawberryperl.com) or Git for Windows ' +
        '(https://git-scm.com), then start SlideMage.', mbInformation, MB_OK, IDOK);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure RunSelfTest();
var
  Code: Integer;
  LogFile: String;
begin
  LogFile := ExpandConstant('{tmp}\..\SlideMage-selftest.log');
  WizardForm.StatusLabel.Caption := 'Compiling a test deck per layout (the first compile can take a few minutes) ...';
  if not Exec(ExpandConstant('{cmd}'), '/c ""' + ExpandConstant('{app}\SlideMage.exe') + '" --self-test --compile > "' +
              LogFile + '" 2>&1"', '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  case Code of
    0: SelfTestMessage := 'SlideMage compiled its test decks: everything it needs is installed.';
    2: SelfTestMessage := 'SlideMage is installed, but no TeX installation was found yet: it cannot compile ' +
                          'decks until MiKTeX is installed (https://miktex.org/download).';
  else
    SelfTestMessage := 'SlideMage is installed, but its test compile failed. Details: ' + LogFile;
  end;
end;

{ --- wizard -------------------------------------------------------------------------------------------------- }

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), 'Downloading Perl ...', @OnDownloadProgress);
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo,
  MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := 'SlideMage for this user only, no administrator rights:' + NewLine + Space + ExpandConstant('{app}') + NewLine;
  if MemoTasksInfo <> '' then Result := Result + NewLine + MemoTasksInfo + NewLine;
  if WizardIsTaskSelected('miktex') or WizardIsTaskSelected('texpackages') then
    Result := Result + NewLine + 'TeX packages (only those missing):' + NewLine + Space + '{#MiktexPackages}' + NewLine;
  if (not TexMissing()) and (FindProgram('miktex.exe') = '') then
    Result := Result + NewLine + 'Your TeX installation is not MiKTeX and is left as it is.' + NewLine;
  Result := Result + NewLine + 'Last, SlideMage compiles a test deck per layout to check the installation.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then Exit;
  if WizardIsTaskSelected('miktex') then
  begin
    InstallMiktex();
    AddMiktexPackages(True);
  end
  else if WizardIsTaskSelected('texpackages') then
    AddMiktexPackages(False);
  if WizardIsTaskSelected('perl') then InstallPerl();
  RunSelfTest();
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (SelfTestMessage <> '') then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 + SelfTestMessage;
end;

#ifndef StageDir
  #error StageDir required
#endif
#ifndef OutputDir
  #error OutputDir required
#endif
[Setup]
AppId={{449E71A8-A0E2-40BA-941F-36FD565F9387}
AppName=GO Structural Analysis for IngeTrazo
AppVersion=0.2.4
AppPublisher=GO Structural
DefaultDirName={localappdata}\GO Structural Analysis\installed
DefaultGroupName=GO Structural Analysis
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=GO-Structural-Analysis-v0.2.4-Windows-x64-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
SetupLogging=yes
UninstallDisplayName=GO Structural Analysis for IngeTrazo
InfoBeforeFile={#StageDir}\docs\START-HERE.txt
LicenseFile={#StageDir}\LICENSE.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "thai"; MessagesFile: "compiler:Languages\Thai.isl"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"
Source: "{#StageDir}\install-helper.ps1"; Flags: dontcopy

[Icons]
Name: "{group}\Quick Start"; Filename: "{app}\docs\START-HERE.txt"
Name: "{group}\Check Solver"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\install-helper.ps1"" -Mode Verify -Gui"; WorkingDir: "{app}"
Name: "{group}\Example Gallery"; Filename: "{app}\docs\artifacts\examples-v0.1.3\index.html"
Name: "{group}\Uninstall GO Structural Analysis"; Filename: "{uninstallexe}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\plugin\__pycache__"
Type: files; Name: "{app}\installation.json"
Type: files; Name: "{app}\solver-check.log"
Type: files; Name: "{app}\setup-error.log"

[Code]
function PluginDir(): String;
begin
  Result := ExpandConstant('{param:PluginDir|{userappdata}\ingetrazo\plugins\go_structural_analysis}');
end;

function RunHelper(Script, Mode, Root, Plugin: String; var ExitCode: Integer): Boolean;
begin
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + Script + '" -Mode ' + Mode +
    ' -InstallRoot "' + Root + '" -PluginRoot "' + Plugin + '"', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  ExtractTemporaryFile('install-helper.ps1');
  if (not RunHelper(ExpandConstant('{tmp}\install-helper.ps1'), 'Preflight', ExpandConstant('{app}'), PluginDir(), ExitCode)) or (ExitCode <> 0) then
    Result := 'Save your work and close IngeTrazo before installing. Setup installs only in user folders.'
  else Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ExitCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    if (not RunHelper(ExpandConstant('{app}\install-helper.ps1'), 'Install', ExpandConstant('{app}'), PluginDir(), ExitCode)) or (ExitCode <> 0) then
      RaiseException('Plugin setup or Solver verification failed. See setup-error.log in the installation folder.');
  end;
end;

function InitializeUninstall(): Boolean;
var ExitCode: Integer;
begin
  Result := RunHelper(ExpandConstant('{app}\install-helper.ps1'), 'Preflight', ExpandConstant('{app}'), PluginDir(), ExitCode) and (ExitCode = 0);
  if not Result then MsgBox('Save your work and close IngeTrazo before uninstalling. See setup-error.log.', mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var ExitCode: Integer;
begin
  if CurUninstallStep = usUninstall then
    if (not RunHelper(ExpandConstant('{app}\install-helper.ps1'), 'Uninstall', ExpandConstant('{app}'), PluginDir(), ExitCode)) or (ExitCode <> 0) then
      RaiseException('Plugin removal failed. See setup-error.log.');
end;

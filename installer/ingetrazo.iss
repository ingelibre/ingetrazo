; Inno Setup script for IngeTrazo.
;
; Builds a professional Windows installer: Spanish wizard, GPL license page,
; shortcuts, "Add or Remove Programs" entry and a clean uninstaller.
;
; Local build (needs Inno Setup 6+):
;     iscc /DMyAppVersion=0.2.0 installer\ingetrazo.iss
;
; CI build: see .github/workflows/build-windows.yml
;
; The AppId is a FIXED GUID — never change it between versions, or Windows
; treats every release as a different app and upgrades stop being clean.

#define MyAppName "IngeTrazo"
#define MyAppPublisher "Ing. Marco Sumari Tellez"
#define MyAppURL "https://ingetrazo.com"
#define MyAppExeName "ingetrazo.exe"

; MyAppVersion is injected from the build command with /DMyAppVersion=X.Y.Z
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
; FIXED AppId GUID — generated once for IngeTrazo. Changing it breaks upgrades.
AppId={{63D1C88D-591C-48C8-A13B-5E41810D05E4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL=https://github.com/tuxiasumari/ingetrazo/issues
AppUpdatesURL=https://github.com/tuxiasumari/ingetrazo/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Modelador 3D libre para ingenieria y arquitectura
VersionInfoProductName={#MyAppName}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Free software: the "license" page shows the GPL-3.0 text.
LicenseFile=..\LICENSE

OutputDir=..\dist
OutputBaseFilename=ingetrazo-setup-v{#MyAppVersion}

WizardStyle=modern
ShowLanguageDialog=no
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\resources\icons\ingetrazo.ico

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole PyInstaller one-dir bundle.
Source: "..\dist\ingetrazo\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Registry]
; .igz file association: double-click opens the document in IngeTrazo.
Root: HKA; Subkey: "Software\Classes\.igz"; ValueType: string; \
    ValueData: "IngeTrazo.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\IngeTrazo.Document"; ValueType: string; \
    ValueData: "Documento de IngeTrazo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\IngeTrazo.Document\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\IngeTrazo.Document\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

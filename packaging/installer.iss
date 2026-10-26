; Inno Setup 6 script for the HR Candidate Screening installer.
; Built by packaging\build.ps1 (needs dist\HRScreening.exe and dist\HR_User_Guide.pdf first):
;   ISCC.exe /DAppVersion=1.0.0 packaging\installer.iss
; Output: dist\HRScreening-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "HR Candidate Screening"
#define AppExe "HRScreening.exe"

[Setup]
; Never change AppId: Windows uses it to recognise upgrades of the same program.
AppId={{0BEB5633-4EF2-4114-B52B-8765B2388872}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
; Per-user install by default (no admin rights); the user may choose an all-users install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Close a running copy before upgrading.
CloseApplications=yes
OutputDir=..\dist
OutputBaseFilename=HRScreening-Setup-{#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\HR_User_Guide.pdf"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} - User Guide"; Filename: "{app}\HR_User_Guide.pdf"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Uninstalling removes the program only. Each user's settings, saved filters and log in
; %APPDATA%\HRScreeningTool, their API key in Credential Manager, and all screening results
; are kept (results contain candidate data and are managed by HR).

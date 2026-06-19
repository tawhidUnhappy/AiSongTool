; Inno Setup script for AiSongTool Windows installer
; Wraps the PyInstaller one-folder build into a standard Windows Setup.exe

#define MyAppName      "AiSongTool"
#define MyAppPublisher "AiSongTool contributors"
#define MyAppURL       "https://github.com/tawhidUnhappy/AiSongTool"
#define MyAppExeName   "aisongtool.exe"
; Version is injected at build time via /DMyAppVersion=... flag
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{A1B2C3D4-5E6F-7890-ABCD-1234567890AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output goes to the repo root so the workflow can easily find it
OutputDir=..\dist
OutputBaseFilename=AiSongTool-Setup-{#MyAppVersion}
SetupIconFile=..\packaging\icon.ico
UninstallDisplayIcon={app}\aisongtool.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Require admin so we can write to Program Files and add to system PATH
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "Create a &desktop shortcut";      GroupDescription: "Additional icons:"; Flags: unchecked
Name: "addtopath";      Description: "Add aisongtool to system &PATH"; GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
; Ship the entire one-folder PyInstaller output
Source: "..\dist\AiSongTool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AiSongTool";          Filename: "{app}\{#MyAppExeName}"; Parameters: "app"; Comment: "Open AiSongTool"
Name: "{group}\Uninstall AiSongTool"; Filename: "{uninstallexe}"
Name: "{commondesktop}\AiSongTool";  Filename: "{app}\{#MyAppExeName}"; Parameters: "app"; Comment: "Open AiSongTool"; Tasks: desktopicon

[Run]
; Offer to launch immediately after install
Filename: "{app}\{#MyAppExeName}"; Parameters: "app"; Description: "Launch AiSongTool now"; Flags: nowait postinstall skipifsilent

[Registry]
; Add to system PATH when the user ticked that task
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
  ValueType: expandsz; ValueName: "Path"; \
  ValueData: "{olddata};{app}"; \
  Check: NeedsAddPath('{app}'); Tasks: addtopath

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKLM,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

; DocForge native Windows installer. Compile on Windows with Inno Setup 6 or 7.
; The build-release.ps1 script must produce dist\DocForge first.
#define MyAppName "DocForge"
#define MyAppVersion "1.11.1"
#define MyAppID "{{c9bc4c6a-d1ab-4e12-8d34-c42ae7db01d9}"
[Setup]
AppId={#MyAppID}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=DocForge Project
DefaultDirName={localappdata}\DocForge
DefaultGroupName=DocForge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\DocForge.exe
SetupIconFile=..\docforge.ico
WizardImageFile=..\wizard-large.bmp
WizardSmallImageFile=..\wizard-small.bmp
OutputDir=..\..\dist\installer
OutputBaseFilename=DocForge-Setup-{#MyAppVersion}-win-x64
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no
LanguageDetectionMethod=none

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktop"; Description: "Создать ярлык DocForge на рабочем столе"; GroupDescription: "Дополнительные значки:"
Name: "zone"; Description: "Добавить значок зоны перетаскивания на рабочий стол"; GroupDescription: "Дополнительные значки:"

[Files]
Source: "..\..\dist\DocForge\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\DocForge"; Filename: "{app}\DocForge.exe"; Parameters: "gui"; WorkingDir: "{app}"; IconFilename: "{app}\DocForge.exe"
Name: "{userprograms}\DocForge Zone"; Filename: "{app}\DocForge.exe"; Parameters: "dropzone"; WorkingDir: "{app}"; IconFilename: "{app}\docforge-zone.ico"
Name: "{userdesktop}\DocForge"; Filename: "{app}\DocForge.exe"; Parameters: "gui"; WorkingDir: "{app}"; Tasks: desktop
Name: "{userdesktop}\DocForge Zone"; Filename: "{app}\DocForge.exe"; Parameters: "dropzone"; WorkingDir: "{app}"; IconFilename: "{app}\docforge-zone.ico"; Tasks: zone

[Registry]
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\DocForgeEdit"; ValueType: string; ValueData: "Edit PDF with DocForge"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\DocForgeEdit\command"; ValueType: string; ValueData: """{app}\DocForge.exe"" edit ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\DocForgeToPDF"; ValueType: string; ValueData: "Convert to PDF with DocForge"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\DocForgeToPDF\command"; ValueType: string; ValueData: """{app}\DocForge.exe"" convert --to pdf ""%1"""; Flags: uninsdeletekey

[Run]
Filename: "{app}\DocForge.exe"; Parameters: "gui"; WorkingDir: "{app}"; Description: "Открыть DocForge"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var ExistingBootstrap: string;
begin
  ExistingBootstrap := ExpandConstant('{localappdata}\DocForge\venv313\Scripts\python.exe');
  Result := not FileExists(ExistingBootstrap);
  if not Result then
    MsgBox('Existing Python-based DocForge detected. Update it with START-HERE.cmd from the ZIP release. ' +
      'The standalone EXE installer is a separate distribution channel; mixing both can corrupt updates.',
      mbError, MB_OK);
end;

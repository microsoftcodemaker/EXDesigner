; Inno Setup script (PRD 2.4). Build after PyInstaller:  iscc packaging\installer.iss
; Per-user install, no admin rights (PRD A1).
#define AppName "DfR Toolkit"
#define AppVersion "0.1.0"
#define Publisher "EXDesigner"
#define SourceDir "..\dist\DfRToolkit"

[Setup]
AppId={{B7E1F6B2-3C5D-4F3A-9C7B-DFR0TOOLKIT01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=DfRToolkit-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\DfRToolkit.exe

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\DfRToolkit.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\DfRToolkit.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\DfRToolkit.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

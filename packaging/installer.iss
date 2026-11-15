#ifndef AppVersion
  #define AppVersion "0.1.2"
#endif
#define AppName "Firmware Color Studio"

[Setup]
AppId={{C04861C9-66C1-4EF1-AF1B-912E8E014138}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Yunhyok
AppPublisherURL=https://github.com/yunhyok/firmware-color-studio
AppSupportURL=https://github.com/yunhyok/firmware-color-studio/issues
DefaultDirName={localappdata}\Programs\Firmware Color Studio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=FirmwareColorStudio-{#AppVersion}-windows-x64-setup
SetupIconFile=..\src\firmware_color_studio\resources\app.ico
UninstallDisplayIcon={app}\FirmwareColorStudio.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\FirmwareColorStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\FirmwareColorStudio.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\FirmwareColorStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FirmwareColorStudio.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

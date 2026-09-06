#define MyAppName "Lim0n4ikzGames Clicker"
#define MyAppVersion "2.0"
#define MyAppPublisher "Lim0n4ikzGames"
#define MyAppExeName "Lim0n4ikzGamesClicker.exe"

[Setup]
AppId={{A8D4A4D4-3F73-4C91-9A8D-2D3B4E0E2A20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Lim0n4ikzGamesClicker
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=Lim0n4ikzGamesClickerSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\Lim0n4ikzGamesClicker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "profiles.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent


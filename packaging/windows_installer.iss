; Inno Setup script: Windows installer of the desktop program.
; Built by .github/workflows/release.yml after PyInstaller:
;   iscc /DAppVersion=<version of ta_morpho/__init__.py> packaging\windows_installer.iss
; Installs for the current user (no administrator rights needed).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C1F0D7E-2B6A-4C8E-9C4B-7A2E5D3F1A90}
AppName=TA-Morpho
AppVersion={#AppVersion}
AppPublisher=David Singer
DefaultDirName={autopf}\TA-Morpho
DefaultGroupName=TA-Morpho
PrivilegesRequired=lowest
OutputDir=..\installers
OutputBaseFilename=TA-Morpho-{#AppVersion}-Windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\ta_morpho\gui\assets\icon.ico
UninstallDisplayIcon={app}\TA-Morpho.exe

[Files]
Source: "..\dist\TA-Morpho\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
; The shortcuts use the icon built into TA-Morpho.exe (PyInstaller 6 puts the
; data files under _internal\, so a path to icon.ico would depend on its layout).
Name: "{group}\TA-Morpho"; Filename: "{app}\TA-Morpho.exe"
Name: "{userdesktop}\TA-Morpho"; Filename: "{app}\TA-Morpho.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\TA-Morpho.exe"; Description: "Start TA-Morpho"; Flags: nowait postinstall skipifsilent

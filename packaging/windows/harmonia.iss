; Inno Setup 6 script for the Windows installer. packaging/windows/build.sh
; passes AppVersion, FileVersion, SourceDir (the PyInstaller bundle), IconFile
; and LicenseFile on the ISCC command line.

#ifndef AppVersion
  #error AppVersion must be defined
#endif

[Setup]
AppId={{6F0B7C55-2E7A-4C1B-9B7E-6A1D3F2C8E41}
AppName=Harmonia
AppVersion={#AppVersion}
AppVerName=Harmonia {#AppVersion}
AppPublisher=Harmonia Contributors
AppPublisherURL=https://github.com/maylton/harmonia-player
AppSupportURL=https://github.com/maylton/harmonia-player/issues
VersionInfoVersion={#FileVersion}
DefaultDirName={autopf}\Harmonia
DefaultGroupName=Harmonia
DisableProgramGroupPage=yes
; Installs for all users by default; the dialog lets a user without admin
; rights install only for themselves.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#LicenseFile}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Harmonia.exe
OutputBaseFilename=Harmonia-{#AppVersion}-x86_64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Harmonia"; Filename: "{app}\Harmonia.exe"; AppUserModelID: "io.github.harmonia.Harmonia"
Name: "{autodesktop}\Harmonia"; Filename: "{app}\Harmonia.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Harmonia.exe"; Description: "{cm:LaunchProgram,Harmonia}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The GStreamer plugin cache is rebuilt on the next start; the session,
; library and downloads in %APPDATA% and %LOCALAPPDATA% stay with the user.
Type: files; Name: "{localappdata}\Harmonia\gstreamer-registry.bin"

; Inno Setup script for NetMeter. Built by .github/workflows/build.yml:
;   NETMETER_VERSION    e.g. 2.1.0 or 2.1.0-dev.12   (shown to people)
;   NETMETER_NUMVERSION e.g. 2.1.0.12                (Windows file version, numbers only)

#define AppVersion GetEnv("NETMETER_VERSION")
#define NumVersion GetEnv("NETMETER_NUMVERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0-local"
#endif
#if NumVersion == ""
  #define NumVersion "0.0.0.0"
#endif

[Setup]
AppId={{9B0C3F4E-5D2A-4E7B-9C1D-6A2F8E4B7C30}
AppName=NetMeter
AppVersion={#AppVersion}
AppVerName=NetMeter {#AppVersion}
AppPublisher=NetMeter
AppPublisherURL=https://github.com/Ady1999/Net-meter
AppSupportURL=https://github.com/Ady1999/Net-meter/issues
VersionInfoVersion={#NumVersion}
; per-user install: no admin rights needed
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\NetMeter
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist
OutputBaseFilename=NetMeter-Setup-{#AppVersion}
SetupIconFile=..\netmeter.ico
UninstallDisplayIcon={app}\NetMeter.exe
UninstallDisplayName=NetMeter
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "autostart"; Description: "Start NetMeter when I sign in to Windows"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\NetMeter.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\plugin-examples\*"; DestDir: "{app}\plugin-examples"; Flags: ignoreversion
Source: "..\skin-examples\*"; DestDir: "{app}\skin-examples"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\NetMeter"; Filename: "{app}\NetMeter.exe"
Name: "{userdesktop}\NetMeter"; Filename: "{app}\NetMeter.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "NetMeter"; ValueData: """{app}\NetMeter.exe"" --startup"; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\NetMeter.exe"; Description: "Start NetMeter now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /im NetMeter.exe /f"; Flags: runhidden; RunOnceId: "StopNetMeter"

[Code]
// NetMeter lives in the tray, so close it before files are replaced.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /im NetMeter.exe /f', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

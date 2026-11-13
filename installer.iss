; CigarMonitor 用户级安装脚本（Inno Setup 6）
; 固定 AppId，后续版本沿用，以便识别为同一应用并就地升级。
#define MyAppName "CigarMonitor"
#define MyAppVersion "1.1.2"
#define MyAppPublisher "hoho77777"
#define MyAppExe "CigarMonitor.exe"

[Setup]
AppId={{08D59AA6-F4C8-4DB9-87C6-68A77E4C55AC}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; 用户级安装：免 UAC，安装在当前用户可写目录，应用内整包自动更新可静默成功。
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\CigarMonitor
DefaultGroupName=CigarMonitor
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=CigarMonitor_v1.1.2_setup
SetupIconFile=assets\cigar.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 用户数据位于 {localappdata}\CigarMonitor，与安装目录 {localappdata}\Programs\CigarMonitor 不同，
; 卸载仅删除安装目录，数据与设置自动保留。

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "附加选项:"

[Files]
Source: "dist\CigarMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\CigarMonitor"; Filename: "{app}\{#MyAppExe}"
Name: "{userdesktop}\CigarMonitor"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Flags: nowait postinstall skipifsilent

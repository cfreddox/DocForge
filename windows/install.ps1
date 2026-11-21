# DocForge Python maintenance recovery 1.11.3 (app 1.11.0) for Windows x64.
# ASCII-only source for compatibility with Windows PowerShell 5.1/ANSI consoles.
# Python and Pandoc are fetched. Native Office PDF engine is a pip wheel.
# Internet is required for an initial installation unless cache files exist.
param([switch]$NoLaunch)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Target = Join-Path $env:LOCALAPPDATA 'DocForge'
$Cache = Join-Path $env:LOCALAPPDATA 'DocForge-InstallCache'
$PythonHome = Join-Path $Target 'runtime\python313'
$PythonExe = Join-Path $PythonHome 'python.exe'
$VenvExe = Join-Path $Target 'venv313\Scripts\python.exe'
$PandocExe = Join-Path $Target 'tools\pandoc\pandoc.exe'
$Paths = New-Object 'System.Collections.Generic.List[string]'
$DownloadSources = @{
    Python = 'https://www.python.org/ftp/python/3.13.12/python-3.13.12-amd64.exe'
    Pandoc = 'https://github.com/jgm/pandoc/releases/download/3.14/pandoc-3.14-windows-x86_64.zip'
}

function Say([string] $message) {
    Write-Host ('[DocForge] ' + $message) -ForegroundColor Cyan
}

function Ensure-Dir([string] $where) {
    if (-not (Test-Path -LiteralPath $where -PathType Container)) {
        New-Item -ItemType Directory -Path $where -Force | Out-Null
    }
}

function Download-File([string] $address, [string] $file, [long] $minimum) {
    if ((Test-Path -LiteralPath $file -PathType Leaf) -and
        ((Get-Item -LiteralPath $file).Length -ge $minimum)) {
        Say ('Using cached file: ' + [IO.Path]::GetFileName($file))
        return
    }
    Say ('Downloading: ' + [IO.Path]::GetFileName($file))
    $temp = $file + '.download'
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    try {
        Invoke-WebRequest -Uri $address -OutFile $temp -UseBasicParsing -TimeoutSec 1800 -MaximumRedirection 8
        if (-not (Test-Path -LiteralPath $temp -PathType Leaf) -or
            ((Get-Item -LiteralPath $temp).Length -lt $minimum)) {
            throw 'Downloaded file is incomplete or is not the expected installer.'
        }
        Move-Item -LiteralPath $temp -Destination $file -Force
    } finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Run-Checked([string] $command, [string[]] $arguments) {
    & $command @arguments
    if ($LASTEXITCODE -ne 0) {
        throw ('Command failed (' + $LASTEXITCODE + '): ' + $command + ' ' + ($arguments -join ' '))
    }
}


function Test-Python([string] $executable, [string] $probe) {
    if ([string]::IsNullOrWhiteSpace($executable)) { return $false }
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { return $false }
    try {
        $output = & $executable $probe 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }
        return [bool](@($output | Where-Object { $_ -like 'DOCFORGE_PYTHON=*' }).Count -gt 0)
    } catch { return $false }
}

function Find-Python([string] $probe, [string] $prefer, [string] $venvPath) {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $candidates.Add($prefer)
    # Read the original base interpreter recorded by virtualenv, including
    # older DocForge installs and installations outside the default folders.
    $cfg = Join-Path $venvPath 'pyvenv.cfg'
    if (Test-Path -LiteralPath $cfg -PathType Leaf) {
        foreach ($line in (Get-Content -LiteralPath $cfg)) {
            if ($line -match '^\s*(home|executable)\s*=\s*(.+?)\s*$') {
                $base = $Matches[2].Trim().Trim('"')
                if ($Matches[1] -eq 'home') { $base = Join-Path $base 'python.exe' }
                $candidates.Add($base)
            }
        }
    }
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ([string]::IsNullOrEmpty($base)) { continue }
        foreach ($relative in @('Programs\Python\Python313\python.exe', 'Python313\python.exe',
                                 'Programs\Python\Python313-64\python.exe', 'Python313-64\python.exe')) {
            $candidates.Add((Join-Path $base $relative))
        }
    }
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        foreach ($keyName in @('3.13', '3.13-64')) {
            foreach ($prefix in @('Software\Python\PythonCore', 'Software\WOW6432Node\Python\PythonCore')) {
                $key = $hive + '\' + $prefix + '\' + $keyName + '\InstallPath'
                try {
                    $keyObj = Get-Item -LiteralPath $key -ErrorAction Stop
                    foreach ($rootPath in @($keyObj.GetValue(''), $keyObj.GetValue('ExecutablePath'))) {
                        if ([string]::IsNullOrWhiteSpace($rootPath)) { continue }
                        if ([IO.Path]::GetExtension($rootPath) -eq '.exe') { $candidates.Add([string]$rootPath) }
                        else { $candidates.Add((Join-Path $rootPath 'python.exe')) }
                    }
                } catch {}
            }
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Python -executable $candidate -probe $probe) { return $candidate }
    }
    # The Python Launcher often knows installations the registry search did
    # not find, including per-machine versions and nonstandard install paths.
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $result = & $launcher.Source -3.13 $probe 2>$null
            if ($LASTEXITCODE -eq 0) {
                foreach ($item in $result) {
                    if ($item -like 'DOCFORGE_PYTHON=*') {
                        $candidate = $item.Substring('DOCFORGE_PYTHON='.Length).Trim()
                        if (Test-Python -executable $candidate -probe $probe) { return $candidate }
                    }
                }
            }
        } catch {}
    }
    # PATH is the last resort. App execution aliases are rejected by probe.
    foreach ($cmd in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if (-not $cmd -or $cmd.Source -like '*\WindowsApps\*') { continue }
        if (Test-Python -executable $cmd.Source -probe $probe) { return $cmd.Source }
    }
    return $null
}


try {
    if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
        throw 'This package requires Windows 10/11 x64 and 64-bit PowerShell.'
    }
    $windows = [Environment]::OSVersion.Version
    if ($windows.Major -lt 10) { throw 'Windows 10 or Windows 11 is required.' }
    if ([string]::IsNullOrEmpty($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is missing.' }
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'docforge\core.py'))) {
        throw 'Incomplete DocForge archive. Extract the entire ZIP before running START-HERE.cmd.'
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Ensure-Dir $Target
    Ensure-Dir $Cache
    Ensure-Dir (Join-Path $Target 'tools')
    Say ('Installing/updating DocForge in: ' + $Target)

    # Try all verified interpreters before running the official CPython setup.
    # A previous silent install may have registered Python elsewhere and
    # returned success without installing it under the requested TargetDir.
    $Probe = Join-Path $Root 'windows\probe_python.py'
    if (-not (Test-Path -LiteralPath $Probe -PathType Leaf)) {
        throw 'Missing windows\probe_python.py. Extract the complete release archive.'
    }
    $haveVenv = $false
    if (Test-Python -executable $VenvExe -probe $Probe) {
        $haveVenv = $true
        Say 'Reusing existing verified DocForge Python environment.'
    }

    if (-not $haveVenv) {
        $candidate = Find-Python -probe $Probe -prefer $PythonExe -venvPath (Join-Path $Target 'venv313')
        if (-not $candidate) {
            $PythonSetup = Join-Path $Cache 'python-3.13.12-amd64.exe'
            Download-File $DownloadSources.Python $PythonSetup 25000000
            $signature = Get-AuthenticodeSignature -FilePath $PythonSetup
            if ($signature.Status -ne 'Valid') {
                throw 'Cached Python installer signature invalid. Delete only its cached EXE and retry.'
            }
            Say 'Installing Python 3.13 for DocForge (existing system Python is not modified).'
            Ensure-Dir (Split-Path -Parent $PythonHome)
            $pythonLog = Join-Path $Cache 'python-setup.log'
            $args = '/quiet InstallAllUsers=0 Include_launcher=0 Include_pip=1 Include_tcltk=1 Include_test=0 Include_doc=0 Include_dev=0 PrependPath=0 AssociateFiles=0 Shortcuts=0 TargetDir="' + $PythonHome + '" /log "' + $pythonLog + '"'
            $proc = Start-Process -FilePath $PythonSetup -ArgumentList $args -PassThru -Wait
            if (($proc.ExitCode -ne 0) -and ($proc.ExitCode -ne 3010)) {
                throw ('Python setup failed with code ' + $proc.ExitCode + '. Read ' + $pythonLog)
            }
            # Re-scan ALL installed Python registrations (including 64-bit
            # per-machine installs, launcher registrations and venv base path).
            $candidate = Find-Python -probe $Probe -prefer $PythonExe -venvPath (Join-Path $Target 'venv313')
            if (-not $candidate) {
                # no verified 64-bit Python 3.13 with Tkinter was found.
                # Python Installer may be registered already (WixBundleInstalled=1).
                # Installing with a new TargetDir then enters maintenance mode
                # and returns 0 without putting python.exe in that directory.
                # Repair the already registered CPython installation once.
                # This does not uninstall Python or remove DocForge user files.
                Say 'Python Setup is registered, but no usable interpreter was found.'
                Say 'Attempting one official Python Installer repair (existing installation).'
                $repairLog = Join-Path $Cache 'python-repair.log'
                $repairArgs = '/repair /quiet /norestart /log "' + $repairLog + '"'
                $repair = Start-Process -FilePath $PythonSetup -ArgumentList $repairArgs -PassThru -Wait
                Say ('Python repair exit code: ' + $repair.ExitCode)
                $candidate = Find-Python -probe $Probe -prefer $PythonExe -venvPath (Join-Path $Target 'venv313')
                if (-not $candidate) {
                    $diag = Join-Path $PSScriptRoot 'diagnose-python.ps1'
                    if (Test-Path -LiteralPath $diag -PathType Leaf) { & $diag }
                    throw ('Python repair did not produce a usable Python 3.13 x64 with Tkinter. ' +
                           'Repair code: ' + $repair.ExitCode + '. Logs: ' + $repairLog +
                           ' and DocForge-InstallCache\python-diagnostics.txt. ' +
                           'Your existing DocForge files were preserved.')
                }
            }
        }
        Say ('Selected verified Python: ' + $candidate)
        if (Test-Path -LiteralPath $VenvExe -PathType Leaf) {
            # Recreate the executable/venv configuration from a working
            # interpreter. Do not delete site-packages, user data or settings.
            Run-Checked $candidate @('-m', 'venv', '--upgrade', (Join-Path $Target 'venv313'))
        } else {
            Run-Checked $candidate @('-m', 'venv', (Join-Path $Target 'venv313'))
        }
        if (-not (Test-Python -executable $VenvExe -probe $Probe)) {
            throw 'DocForge venv was created but Python 3.13/Tkinter verification failed.'
        }
    }
    Say 'Installing application libraries automatically.'
    Run-Checked $VenvExe @('-m','pip','install','--disable-pip-version-check','--prefer-binary','--only-binary=:all:','-r',(Join-Path $Root 'windows\requirements-windows.txt'))
    # This is optional because layout reconstruction can use a basic fallback.
    try {
        Run-Checked $VenvExe @('-m','pip','install','--disable-pip-version-check','--prefer-binary','--only-binary=:all:','pdf2docx>=0.5.13,<0.6')
    } catch {
        Write-Warning 'Optional pdf2docx was not installed; the built-in PDF to Word method is available.'
    }

    # Pandoc is shipped as an official stand-alone release ZIP (no MSI, no PATH edits).
    if (-not (Test-Path -LiteralPath $PandocExe -PathType Leaf)) {
        $PandocZip = Join-Path $Cache 'pandoc-3.14-windows-x86_64.zip'
        Download-File $DownloadSources.Pandoc $PandocZip 10000000
        $unpack = Join-Path $Cache 'pandoc-unpack'
        if (Test-Path -LiteralPath $unpack) { Remove-Item -LiteralPath $unpack -Recurse -Force }
        Ensure-Dir $unpack
        Expand-Archive -LiteralPath $PandocZip -DestinationPath $unpack -Force
        $pandocBin = Get-ChildItem -LiteralPath $unpack -Recurse -Filter 'pandoc.exe' -File | Select-Object -First 1
        if ($null -eq $pandocBin) { throw 'Pandoc ZIP does not contain pandoc.exe.' }
        $pandocFolder = Split-Path -Parent $PandocExe
        Ensure-Dir $pandocFolder
        Copy-Item -Path (Join-Path $pandocBin.DirectoryName '*') -Destination $pandocFolder -Force -Recurse
    }
    Run-Checked $PandocExe @('--version')
    $Paths.Add((Split-Path -Parent $PandocExe))

    # No office suite, Windows Installer MSI, Microsoft Word or separate GTK setup.
    # The office2pdf wheel brings a self-contained native Rust PDF renderer.
    Say 'Checking the local Office-to-PDF renderer.'
    # Invoke a Python source file directly: Windows PowerShell 5.1 may strip
    # embedded quotation marks when forwarding a python -c string.
    Run-Checked $VenvExe @((Join-Path $Root 'windows\verify_renderer.py'))

    # Never replace code while the previous GUI or dropzone is using it.
    # CIM can be unavailable under restrictive policies; in that case continue
    # with guarded copy/rollback rather than failing clean installs.
    $runningApp = @()
    try {
        $runningApp = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction Stop |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains((Join-Path $Target 'launcher.py')) })
    } catch { $runningApp = @() }
    if ($runningApp.Count -gt 0) {
        throw 'Close all running DocForge windows and the drop zone before updating. Installed files were not changed.'
    }

    # Prepare code before touching any installed application. Keep Python, pandoc,
    # settings, user files and virtual environment stable across upgrades.
    $installedCode = Join-Path $Target 'docforge'
    $wasUpgrade = Test-Path -LiteralPath (Join-Path $installedCode '__init__.py')
    if ($wasUpgrade) { Say 'Existing DocForge detected: updating in place with rollback.' }
    else { Say 'Clean installation: creating DocForge application files.' }
    $stage = Join-Path $Target ('.staging-' + [Guid]::NewGuid().ToString('N'))
    $backup = Join-Path $Target ('code-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $backedUp = @()
    $deployed = @()
    $installFiles = @('docforge','assets','launcher.py','healthcheck.py','make_icon.py',
                      'Diagnose-DocForge.cmd','docforge.ico','docforge-zone.ico','docforge.cmd','binpaths.txt')
    try {
        Ensure-Dir $stage
        Copy-Item -LiteralPath (Join-Path $Root 'docforge') -Destination (Join-Path $stage 'docforge') -Recurse -Force
        Copy-Item -LiteralPath (Join-Path $Root 'assets') -Destination (Join-Path $stage 'assets') -Recurse -Force
        foreach ($name in @('launcher.py','healthcheck.py','make_icon.py','Diagnose-DocForge.cmd',
                             'docforge.ico','docforge-zone.ico','docforge.cmd')) {
            $source = Join-Path (Join-Path $Root 'windows') $name
            Copy-Item -LiteralPath $source -Destination (Join-Path $stage $name) -Force
        }
        [IO.File]::WriteAllLines((Join-Path $stage 'binpaths.txt'), $Paths.ToArray(), ([System.Text.UTF8Encoding]::new($false)))
        Say 'Validating new application code before replacement.'
        Run-Checked $VenvExe @('-m','compileall','-q',(Join-Path $stage 'docforge'))
        # Back up every file that is modified, not just Python modules.
        Ensure-Dir $backup
        foreach ($name in $installFiles) {
            $original = Join-Path $Target $name
            if (Test-Path -LiteralPath $original) {
                Move-Item -LiteralPath $original -Destination (Join-Path $backup $name) -Force
                $backedUp += $name
            }
        }
        foreach ($name in $installFiles) {
            $incoming = Join-Path $stage $name
            if (Test-Path -LiteralPath $incoming) {
                Move-Item -LiteralPath $incoming -Destination (Join-Path $Target $name) -Force
                $deployed += $name
            }
        }
        Say 'Running the complete post-update document conversion smoke test.'
        Run-Checked $VenvExe @((Join-Path $Target 'healthcheck.py'))
        [IO.File]::WriteAllText((Join-Path $Target 'installed-version.txt'), '1.11.0', ([System.Text.UTF8Encoding]::new($false)))
        Say ('Application verified. Recovery copy: ' + $backup)
    } catch {
        Say 'Update failed. Rolling back only files actually changed.'
        foreach ($name in $deployed) {
            $dest = Join-Path $Target $name
            if (Test-Path -LiteralPath $dest) {
                Remove-Item -LiteralPath $dest -Recurse -Force
            }
        }
        foreach ($name in $backedUp) {
            $old = Join-Path $backup $name
            if (Test-Path -LiteralPath $old) {
                Move-Item -LiteralPath $old -Destination (Join-Path $Target $name) -Force
            }
        }
        throw
    } finally {
        if (Test-Path -LiteralPath $stage) {
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }

    # Current-user shell integration, compatible with non-admin Windows setups.
    Say 'Creating shortcuts and Explorer context menu entries.'
    $shortcutTool = New-Object -ComObject WScript.Shell
    $guiExe = Join-Path $Target 'venv313\Scripts\pythonw.exe'
    $script = Join-Path $Target 'launcher.py'
    $menuRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    $shortcut = $shortcutTool.CreateShortcut((Join-Path $menuRoot 'DocForge.lnk'))
    $shortcut.TargetPath = $guiExe
    $shortcut.Arguments = ('"' + $script + '" gui')
    $shortcut.WorkingDirectory = $Target
    $shortcut.Description = 'DocForge - local document conversion and PDF editor'
    $shortcut.IconLocation = (Join-Path $Target 'docforge.ico')
    $shortcut.Save()
    $desktop = [Environment]::GetFolderPath('Desktop')
    if (-not [string]::IsNullOrEmpty($desktop)) {
        $shortcut = $shortcutTool.CreateShortcut((Join-Path $desktop 'DocForge.lnk'))
        $shortcut.TargetPath = $guiExe
        $shortcut.Arguments = ('"' + $script + '" gui')
        $shortcut.WorkingDirectory = $Target
        $shortcut.IconLocation = (Join-Path $Target 'docforge.ico')
        $shortcut.Save()
    }
    $zoneShortcut = $shortcutTool.CreateShortcut((Join-Path $menuRoot 'DocForge Zone.lnk'))
    $zoneShortcut.TargetPath = $guiExe
    $zoneShortcut.Arguments = ('"' + $script + '" dropzone')
    $zoneShortcut.WorkingDirectory = $Target
    $zoneShortcut.Description = 'DocForge floating drag-and-drop conversion zone'
    $zoneShortcut.IconLocation = (Join-Path $Target 'docforge-zone.ico')
    $zoneShortcut.Save()
    if (-not [string]::IsNullOrEmpty($desktop)) {
        $desktopZone = $shortcutTool.CreateShortcut((Join-Path $desktop 'DocForge Zone.lnk'))
        $desktopZone.TargetPath = $guiExe
        $desktopZone.Arguments = ('"' + $script + '" dropzone')
        $desktopZone.WorkingDirectory = $Target
        $desktopZone.IconLocation = (Join-Path $Target 'docforge-zone.ico')
        $desktopZone.Save()
    }
    $trayShortcut = $shortcutTool.CreateShortcut((Join-Path $menuRoot 'DocForge Tray.lnk'))
    $trayShortcut.TargetPath = $guiExe
    $trayShortcut.Arguments = ('"' + $script + '" tray')
    $trayShortcut.WorkingDirectory = $Target
    $trayShortcut.IconLocation = (Join-Path $Target 'docforge.ico')
    $trayShortcut.Save()
    $cmdPath = Join-Path $Target 'docforge.cmd'
    $formats = @{
        '.md' = @('pdf','docx','txt');
        '.txt' = @('pdf','md','docx');
        '.docx' = @('pdf','md','txt');
        '.pdf' = @('md','docx','txt')
    }
    foreach ($ext in $formats.Keys) {
        foreach ($fmt in $formats[$ext]) {
            $key = 'HKCU:\Software\Classes\SystemFileAssociations\' + $ext + '\shell\DocForgeTo' + $fmt
            New-Item -Path $key -Force | Out-Null
            Set-Item -Path $key -Value ('DocForge to ' + $fmt.ToUpper())
            New-Item -Path ($key + '\command') -Force | Out-Null
            Set-Item -Path ($key + '\command') -Value ('"' + $cmdPath + '" convert --to ' + $fmt + ' "%1"')
        }
    }
    $editKey = 'HKCU:\Software\Classes\SystemFileAssociations\.pdf\shell\DocForgeEdit'
    New-Item -Path $editKey -Force | Out-Null
    Set-Item -Path $editKey -Value 'Edit PDF with DocForge'
    New-Item -Path ($editKey + '\command') -Force | Out-Null
    Set-Item -Path ($editKey + '\command') -Value ('"' + $cmdPath + '" edit "%1"')

    Say 'SUCCESS. Open DocForge from the Desktop or Start Menu.'
    Say ('Installed location: ' + $Target)
    if (-not $NoLaunch) {
        Start-Process -FilePath $guiExe -ArgumentList ('"' + $script + '" gui') -WorkingDirectory $Target | Out-Null
    }
    exit 0
} catch {
    Write-Host ''
    Write-Host ('[DocForge ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('Source: ' + $_.InvocationInfo.PositionMessage) -ForegroundColor DarkYellow
    Write-Host 'You do NOT need to manually install Python. Check internet access and rerun START-HERE.cmd.' -ForegroundColor Yellow
    exit 1
}

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [string]$EvidenceDir = "dist/installer-qa",
    [int]$StartupTimeoutSeconds = 180,
    [int]$ExitTimeoutSeconds = 120,
    [int]$UninstallTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$script:failures = 0
$checks = New-Object System.Collections.Generic.List[object]
$evidence = [ordered]@{
    started_at  = (Get-Date).ToUniversalTime().ToString("o")
    installer   = $null
    install     = [ordered]@{}
    uninstall   = [ordered]@{}
    checks      = $checks
    passed      = $false
    finished_at = $null
}

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail = "")
    $entry = [ordered]@{ name = $Name; passed = $Passed; detail = $Detail; at = (Get-Date).ToUniversalTime().ToString("o") }
    $checks.Add([pscustomobject]$entry) | Out-Null
    $status = if ($Passed) { "PASS" } else { "FAIL" }
    Write-Host "[$status] $Name $Detail"
    if (-not $Passed) { $script:failures++ }
}

function Wait-Until {
    param([scriptblock]$Condition, [int]$TimeoutSeconds, [int]$IntervalMilliseconds = 500)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Milliseconds $IntervalMilliseconds
    }
    return [bool](& $Condition)
}

function Resolve-RegistryPath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    $text = $Value.Trim()
    if ($text.StartsWith('"')) {
        $closing = $text.IndexOf('"', 1)
        if ($closing -gt 1) { return $text.Substring(1, $closing - 1).Trim() }
        return $text.Trim('"').Trim()
    }
    $argument = $text.IndexOf(" /")
    if ($argument -gt 0) { return $text.Substring(0, $argument).Trim() }
    return $text
}

function Invoke-CloseRequest {
    param([int]$ProcessId)
    Start-Process -FilePath "taskkill.exe" -ArgumentList @("/PID", "$ProcessId") -Wait -PassThru | Out-Null
}

function Get-UninstallEntries {
    $roots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    $found = @()
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($key in Get-ChildItem -Path $root -ErrorAction SilentlyContinue) {
            $props = Get-ItemProperty -Path $key.PSPath -ErrorAction SilentlyContinue
            if ($null -eq $props) { continue }
            if ($props.DisplayName -and $props.DisplayName -like "*FM Tactics Lab*") {
                $found += [pscustomobject]@{
                    Key             = $key.PSPath
                    DisplayName     = $props.DisplayName
                    InstallLocation = $props.InstallLocation
                    UninstallString = $props.UninstallString
                    DisplayVersion  = $props.DisplayVersion
                }
            }
        }
    }
    $found
}

function Get-AppProcess {
    Get-Process -Name "fm27lab-desktop" -ErrorAction SilentlyContinue
}

function Get-SidecarProcess {
    Get-Process -Name "fm27lab-sidecar" -ErrorAction SilentlyContinue
}

function Find-Endpoint {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "com.severuszh.fm27lab\agent\endpoint.json"))
        foreach ($dir in Get-ChildItem -Path $env:LOCALAPPDATA -Directory -ErrorAction SilentlyContinue) {
            $candidates.Add((Join-Path $dir.FullName "agent\endpoint.json"))
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Invoke-SilentInstaller {
    param([string]$Path, [string[]]$Arguments)
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru -Wait
    return $process.ExitCode
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Fm27WindowControl {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    public static IntPtr FindVisibleWindow(int processId) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            uint owner;
            GetWindowThreadProcessId(hWnd, out owner);
            if (owner == (uint)processId && IsWindowVisible(hWnd)) {
                found = hWnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
"@

$installed = Get-UninstallEntries
Add-Check -Name "installer exists" -Passed (Test-Path $InstallerPath) -Detail $InstallerPath
if (-not (Test-Path $InstallerPath)) {
    $evidence.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
    $evidence | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $EvidenceDir "evidence.json") -Encoding utf8
    exit 1
}
$installer = (Resolve-Path $InstallerPath).Path
$evidence.installer = $installer
try {
    Add-Check -Name "no stale install before install" -Passed ($installed.Count -eq 0) -Detail ("{0} entries" -f $installed.Count)

    $installExit = Invoke-SilentInstaller -Path $installer -Arguments @("/S")
    Add-Check -Name "silent install exit code" -Passed ($installExit -eq 0) -Detail ("exit={0}" -f $installExit)

    $hasEntry = Wait-Until -Condition { (Get-UninstallEntries).Count -gt 0 } -TimeoutSeconds 60
    Add-Check -Name "uninstall registry entry created" -Passed $hasEntry
    $entries = Get-UninstallEntries
    $installDir = $null
    if ($entries.Count -gt 0) {
        $entry = $entries[0]
        $evidence.install = [ordered]@{
            display_name     = $entry.DisplayName
            display_version  = $entry.DisplayVersion
            install_location = $entry.InstallLocation
            uninstall_string = $entry.UninstallString
            registry_key     = $entry.Key
        }
        $location = Resolve-RegistryPath $entry.InstallLocation
        if ($location -and (Test-Path -LiteralPath $location)) {
            $installDir = $location
        } elseif ($entry.UninstallString) {
            $uninstallerPath = Resolve-RegistryPath $entry.UninstallString
            if ($uninstallerPath -and (Test-Path -LiteralPath $uninstallerPath)) {
                $installDir = Split-Path -Parent $uninstallerPath
            }
        }
    }
    Add-Check -Name "install directory resolved" -Passed ($null -ne $installDir) -Detail "$installDir"
    $evidence.install["directory"] = $installDir

    if ($installDir) {
        $desktopExe = Join-Path $installDir "fm27lab-desktop.exe"
        $sidecarExe = Join-Path $installDir "sidecar\fm27lab-sidecar.exe"
        $sidecarInternal = Join-Path $installDir "sidecar\_internal"
        $uninstaller = Join-Path $installDir "uninstall.exe"
        Add-Check -Name "desktop executable installed" -Passed (Test-Path $desktopExe) -Detail $desktopExe
        Add-Check -Name "sidecar executable installed" -Passed (Test-Path $sidecarExe) -Detail $sidecarExe
        Add-Check -Name "sidecar payload keeps _internal" -Passed (Test-Path $sidecarInternal) -Detail $sidecarInternal
        $pythonDlls = @(Get-ChildItem -Path $sidecarInternal -Filter "python*.dll" -ErrorAction SilentlyContinue)
        Add-Check -Name "sidecar payload keeps python runtime" -Passed ($pythonDlls.Count -gt 0) -Detail ("{0} dll" -f $pythonDlls.Count)
        $migration = Join-Path $sidecarInternal "fm27lab\adapters\storage_sqlite\migrations\001_init.sql"
        Add-Check -Name "sidecar payload keeps migrations" -Passed (Test-Path $migration) -Detail $migration
        Add-Check -Name "uninstaller installed" -Passed (Test-Path $uninstaller) -Detail $uninstaller

        if (Test-Path $desktopExe) {
            $app = Start-Process -FilePath $desktopExe -PassThru
            $sidecarStarted = Wait-Until -Condition { $null -ne (Get-SidecarProcess) } -TimeoutSeconds $StartupTimeoutSeconds
            Add-Check -Name "sidecar starts with the desktop shell" -Passed $sidecarStarted -Detail ("timeout={0}s" -f $StartupTimeoutSeconds)
            $endpointSeen = Wait-Until -Condition { $null -ne (Find-Endpoint) } -TimeoutSeconds $StartupTimeoutSeconds
            $endpointPath = Find-Endpoint
            Add-Check -Name "sidecar writes endpoint.json" -Passed ($null -ne $endpointPath) -Detail "$endpointPath"
            if ($endpointPath) {
                $endpointData = Get-Content -Path $endpointPath -Raw | ConvertFrom-Json
                $tokenLength = 0
                if ($endpointData.token) { $tokenLength = $endpointData.token.Length }
                $evidence.install["endpoint"] = [ordered]@{
                    path         = $endpointPath
                    url          = $endpointData.url
                    token_length = $tokenLength
                }
                Add-Check -Name "endpoint exposes loopback url and token" -Passed ([bool]$endpointData.url -and [bool]$endpointData.token)
            }

            $app.Refresh()
            $handle = $app.MainWindowHandle
            if ($handle -eq [IntPtr]::Zero) {
                $handle = [Fm27WindowControl]::FindVisibleWindow($app.Id)
            }
            if ($handle -ne [IntPtr]::Zero) {
                [Fm27WindowControl]::SendMessage($handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
                $closed = Wait-Until -Condition { $null -eq (Get-AppProcess) } -TimeoutSeconds $ExitTimeoutSeconds
                if (-not $closed) {
                    Invoke-CloseRequest -ProcessId $app.Id
                    $closed = Wait-Until -Condition { $null -eq (Get-AppProcess) } -TimeoutSeconds 30
                }
                $evidence.install["window_close"] = "wm_close"
                Add-Check -Name "desktop shell exits on window close" -Passed $closed -Detail ("handle={0} timeout={1}s" -f $handle, $ExitTimeoutSeconds)
            } else {
                Invoke-CloseRequest -ProcessId $app.Id
                $closed = Wait-Until -Condition { $null -eq (Get-AppProcess) } -TimeoutSeconds 30
                $evidence.install["window_close"] = "close_request"
                Add-Check -Name "desktop shell exits on close request" -Passed $closed -Detail "no window handle"
            }
            if ($null -ne (Get-AppProcess)) {
                Get-AppProcess | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }

            $noSidecar = Wait-Until -Condition { $null -eq (Get-SidecarProcess) } -TimeoutSeconds $ExitTimeoutSeconds
            Add-Check -Name "sidecar exits after shell exit" -Passed $noSidecar -Detail ("timeout={0}s" -f $ExitTimeoutSeconds)
            if ($null -ne (Get-SidecarProcess)) {
                Get-SidecarProcess | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
            }
            if ($endpointPath) {
                $endpointRemoved = Wait-Until -Condition { -not (Test-Path $endpointPath) } -TimeoutSeconds 30
                Add-Check -Name "endpoint.json removed on exit" -Passed $endpointRemoved
            }
        }

        if (Test-Path $uninstaller) {
            $uninstallExit = Invoke-SilentInstaller -Path $uninstaller -Arguments @("/S")
            Add-Check -Name "silent uninstall started" -Passed ($uninstallExit -eq 0) -Detail ("exit={0}" -f $uninstallExit)
            $exeRemoved = Wait-Until -Condition { -not (Test-Path $desktopExe) } -TimeoutSeconds $UninstallTimeoutSeconds
            Add-Check -Name "desktop executable removed by uninstaller" -Passed $exeRemoved -Detail ("timeout={0}s" -f $UninstallTimeoutSeconds)
            $sidecarRemoved = Wait-Until -Condition { -not (Test-Path $sidecarExe) } -TimeoutSeconds 60
            Add-Check -Name "sidecar payload removed by uninstaller" -Passed $sidecarRemoved
            $registryRemoved = Wait-Until -Condition { (Get-UninstallEntries).Count -eq 0 } -TimeoutSeconds $UninstallTimeoutSeconds
            Add-Check -Name "uninstall registry entry removed" -Passed $registryRemoved
            $residualProcesses = @(Get-AppProcess) + @(Get-SidecarProcess)
            Add-Check -Name "no residual processes after uninstall" -Passed ($residualProcesses.Count -eq 0) -Detail ("{0} processes" -f $residualProcesses.Count)
            $dirRemoved = Wait-Until -Condition { -not (Test-Path $installDir) } -TimeoutSeconds 60
            $evidence.uninstall = [ordered]@{
                install_directory_removed  = $dirRemoved
                desktop_executable_removed = $exeRemoved
                sidecar_payload_removed    = $sidecarRemoved
                registry_entry_removed     = $registryRemoved
            }
            Add-Check -Name "install directory removed by uninstaller" -Passed $dirRemoved
        }
    }

} catch {
    Add-Check -Name "verification completed without exception" -Passed $false -Detail $_.Exception.Message
} finally {
    $evidence.passed = ($script:failures -eq 0)
    $evidence.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
    $evidence | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $EvidenceDir "evidence.json") -Encoding utf8
    Write-Host ("checks={0} failures={1}" -f $checks.Count, $script:failures)
}
if ($script:failures -gt 0) { exit 1 }
exit 0

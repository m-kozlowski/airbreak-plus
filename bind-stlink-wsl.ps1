param(
    [string]$BusId = "7-2",
    [string]$ExpectedVidPid = "0483:3748",
    [string]$Distro = ""
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) {
    Write-Error "usbipd was not found. Install usbipd-win, then run this script again."
}

$usbipdList = usbipd list
$deviceLine = $usbipdList | Where-Object { $_ -match "^\s*$([regex]::Escape($BusId))\s+$([regex]::Escape($ExpectedVidPid))\s+" }

if (-not $deviceLine) {
    Write-Host $usbipdList
    Write-Error "Could not find ST-Link device $ExpectedVidPid at bus ID $BusId. Check the current bus ID with: usbipd list"
}

Write-Host "Found device: $deviceLine"

if (-not (Test-IsAdministrator)) {
    Write-Warning "usbipd bind may require an elevated PowerShell prompt. If this fails, re-run PowerShell as Administrator."
}

Write-Host "Binding bus ID $BusId..."
usbipd bind --busid $BusId

$attachArgs = @("attach", "--wsl", "--busid", $BusId)
if ($Distro.Trim().Length -gt 0) {
    $attachArgs += @("--distribution", $Distro)
}

Write-Host "Attaching bus ID $BusId to WSL..."
usbipd @attachArgs

Write-Host "Done. In WSL, verify with: lsusb"
Write-Host "Then run: sudo openocd -f interface/stlink.cfg -f tcl/airsense.cfg"
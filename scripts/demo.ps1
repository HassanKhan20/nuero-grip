# NeuroGrip demo launcher: ONE app = headband (via the S3 hand board) + webcam + robot hand.
#   powershell -ExecutionPolicy Bypass -File scripts\demo.ps1            (defaults below)
#   powershell -ExecutionPolicy Bypass -File scripts\demo.ps1 -Port COM5 -Control intent
# Stops any running NeuroGrip app first: two apps fight over the webcam and the serial port.
param(
    [string]$Port = "COM4",          # ESP32-S3 hand board
    [string]$Control = "mirror",     # mirror = robot copies your hand while you focus | intent = focus closes a grip
    [int]$Level = 1,                 # 1 = lowest trigger
    [int]$Camera = 0,
    [int]$WebPort = 5000
)
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'app\.py' } |
    ForEach-Object { Write-Host "Stopping old app (pid $($_.ProcessId))"; Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 800

# API keys saved with setx live in the user environment; a terminal opened before that won't have them
foreach ($k in 'NVIDIA_API_KEY', 'GEMINI_API_KEY', 'MONGODB_URI') {
    if (-not [Environment]::GetEnvironmentVariable($k, 'Process')) {
        $v = [Environment]::GetEnvironmentVariable($k, 'User')
        if ($v) { Set-Item "env:$k" $v }
    }
    Write-Host ("  {0,-15} {1}" -f $k, $(if ([Environment]::GetEnvironmentVariable($k, 'Process')) { 'set' } else { 'NOT SET' }))
}
$env:NG_MODE = "hardware"; $env:NG_SERIAL_PORT = $Port; $env:NG_INTENT_SITES = "temple"
$env:NG_CONTROL = $Control; $env:NG_LEVEL = "$Level"; $env:NG_CAMERA = "$Camera"; $env:PORT = "$WebPort"

Write-Host ""
Write-Host "NeuroGrip  ->  http://localhost:$WebPort/mind   (login therapist / therapist)"
Write-Host "  Z = zero (relaxed)   C = calibrate   M = mirror my hand   G = focus-to-grip"
Write-Host ""
Set-Location $root
& $py app.py

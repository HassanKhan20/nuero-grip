# NeuroGrip hand + camera launcher: the robot hand copies your hand on the webcam. No headband needed.
#   powershell -ExecutionPolicy Bypass -File scripts\handcam.ps1                 (hand on COM4, always copying)
#   powershell -ExecutionPolicy Bypass -File scripts\handcam.ps1 -Port COM5 -Hold   (copies only while Space is held)
# The hand board must be on laptop USB (it is also the serial link). It connects whenever it is plugged in.
param(
    [string]$Port = "COM4",          # ESP32-S3 hand board
    [switch]$Hold,                   # copy only while "Hold to try" / Space is held (shows the effort gate)
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

foreach ($k in 'NVIDIA_API_KEY', 'GEMINI_API_KEY', 'MONGODB_URI') {
    if (-not [Environment]::GetEnvironmentVariable($k, 'Process')) {
        $v = [Environment]::GetEnvironmentVariable($k, 'User')
        if ($v) { Set-Item "env:$k" $v }
    }
}
$env:NG_MODE = "camera"; $env:NG_HAND_PORT = $Port; $env:NG_CONTROL = "mirror"
$env:NG_ALWAYS_ON = $(if ($Hold) { "0" } else { "1" }); $env:NG_CAMERA = "$Camera"; $env:PORT = "$WebPort"

Write-Host ""
Write-Host "NeuroGrip hand + camera  ->  http://localhost:$WebPort   (login therapist / therapist)"
Write-Host ("  robot hand on {0}, camera {1}, {2}" -f $Port, $Camera, $(if ($Hold) { "copies while Space is held" } else { "always copying" }))
Write-Host ""
Set-Location $root
& $py app.py

# Day 4 test: face enroll -> check -> scan with selfie. Run from the backend folder, server running:
#   powershell -ExecutionPolicy Bypass -File .\test_day4.ps1
# Needs 4 photos in a folder called "testphotos" next to this script:
#   me1.jpg    clear front-facing selfie of YOU (used to enroll)
#   me2.jpg    another selfie of YOU (different light/angle)
#   other.jpg  a photo of a DIFFERENT person (one face only)
#   noface.jpg a photo with no face (a wall, a landscape)

$base = "http://localhost:8000"
$teacherEmail = "teacher@test.com"
$studentEmail = "student@test.com"
$password = "password123"
$photos = Join-Path $PSScriptRoot "testphotos"

foreach ($name in @("me1.jpg", "me2.jpg", "other.jpg", "noface.jpg")) {
    if (-not (Test-Path (Join-Path $photos $name))) {
        Write-Host "Missing photo: $photos\$name" -ForegroundColor Red
        exit 1
    }
}

function Call($method, $path, $token, $body) {
    $params = @{ Method = $method; Uri = "$base$path"; Headers = @{} }
    if ($token) { $params.Headers["Authorization"] = "Bearer $token" }
    if ($body) { $params.ContentType = "application/json"; $params.Body = ($body | ConvertTo-Json) }
    try {
        $data = Invoke-RestMethod @params
        return @{ Status = "2xx"; Data = $data }
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        return @{ Status = "$code"; Data = $_.ErrorDetails.Message }
    }
}

# Multipart upload with curl.exe (ships with Windows 10/11)
function FormPost($path, $token, $fields, $photoName) {
    $out = Join-Path $env:TEMP "resp_day4.json"
    if (Test-Path $out) { Remove-Item $out }
    $curlArgs = @("-s", "-o", $out, "-w", "%{http_code}", "-X", "POST", "$base$path", "-H", "Authorization: Bearer $token")
    foreach ($k in $fields.Keys) { $curlArgs += @("-F", "$k=$($fields[$k])") }
    $curlArgs += @("-F", ("selfie=@" + (Join-Path $photos $photoName)))
    $code = & curl.exe @curlArgs
    $body = ""
    if (Test-Path $out) { $body = (Get-Content $out -Raw).Trim() }
    return @{ Status = "$code"; Data = $body }
}

function Login($email) {
    try {
        $r = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -Body @{ username = $email; password = $password }
        return $r.access_token
    } catch {
        Write-Host "Login failed for $email : $($_.ErrorDetails.Message)" -ForegroundColor Red
        exit 1
    }
}

function Show($label, $expected, $r) {
    $ok = ($r.Status -eq $expected) -or ($expected -eq "201" -and $r.Status -eq "2xx")
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("{0,-30} got {1,-4} expected {2,-4} {3}" -f $label, $r.Status, $expected, $r.Data) -ForegroundColor $color
}

$T = Login $teacherEmail
$S = Login $studentEmail
$studentId = (Call "GET" "/auth/me" $S $null).Data.id
Write-Host "Logged in. Student id = $studentId" -ForegroundColor Cyan

# Start clean: teacher resets the student's face (404 just means nothing was enrolled)
Call "DELETE" "/face/$studentId" $T $null | Out-Null
# Since Day 5, scans must come from the student's registered phone. Register a test phone.
Call "DELETE" "/device/$studentId" $T $null | Out-Null
$deviceId = "powershell-test-phone-1"
Call "POST" "/device/bind" $S @{ device_id = $deviceId; device_name = "PowerShell test" } | Out-Null

Write-Host "--- Face enrollment ---" -ForegroundColor Cyan
Show "enroll with no-face photo"  "400" (FormPost "/face/enroll" $S @{} "noface.jpg")
Show "enroll me1.jpg"             "201" (FormPost "/face/enroll" $S @{} "me1.jpg")
Show "enroll again"               "409" (FormPost "/face/enroll" $S @{} "me2.jpg")

Write-Host "--- Face check (no attendance marked) ---" -ForegroundColor Cyan
Show "check me2.jpg (same person)"   "200" (FormPost "/face/check" $S @{} "me2.jpg")
Show "check other.jpg (different)"   "200" (FormPost "/face/check" $S @{} "other.jpg")
Write-Host "  ^ me2 should say match:true (high score), other should say match:false (low score)"

Write-Host "--- Scan with selfie ---" -ForegroundColor Cyan
$cls = @((Call "GET" "/classes/mine" $T $null).Data)[0]
foreach ($sess in @((Call "GET" "/sessions/active" $T $null).Data)) {
    if ($sess.id) { Call "POST" "/sessions/$($sess.id)/end" $T $null | Out-Null }
}
$sid = (Call "POST" "/sessions/start" $T @{ classroom_id = $cls.id }).Data.id
$token = (Call "GET" "/sessions/$sid/qr" $T $null).Data.token
$fields = @{ qr_token = $token; latitude = $cls.latitude; longitude = $cls.longitude; accuracy_m = 10; device_id = $deviceId }

Show "scan with other.jpg"        "403" (FormPost "/attendance/scan" $S $fields "other.jpg")
Show "scan with no-face photo"    "400" (FormPost "/attendance/scan" $S $fields "noface.jpg")
Show "scan with me2.jpg"          "201" (FormPost "/attendance/scan" $S $fields "me2.jpg")
Show "scan again"                 "409" (FormPost "/attendance/scan" $S $fields "me2.jpg")

Write-Host "Teacher's attendance list:" -ForegroundColor Cyan
(Call "GET" "/sessions/$sid/attendance" $T $null).Data | ConvertTo-Json -Depth 4
Call "POST" "/sessions/$sid/end" $T $null | Out-Null
Write-Host "Done." -ForegroundColor Cyan

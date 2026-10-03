# Runs the whole Day 3 flow for you: login -> start session -> QR -> scan tests.
# Run from the backend folder while the server is running:
#   powershell -ExecutionPolicy Bypass -File .\test_day3.ps1

$base = "http://localhost:8000"
$teacherEmail = "teacher@test.com"
$studentEmail = "student@test.com"
$password = "password123"

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
    $detail = if ($r.Data -is [string]) { $r.Data } else { "" }
    Write-Host ("{0,-28} got {1,-4} expected {2,-4} {3}" -f $label, $r.Status, $expected, $detail) -ForegroundColor $color
}

$T = Login $teacherEmail
$S = Login $studentEmail
Write-Host "Logged in as teacher and student." -ForegroundColor Cyan

# Find the teacher's class (first one)
$cls = @((Call "GET" "/classes/mine" $T $null).Data)[0]
Write-Host "Class: id=$($cls.id) name=$($cls.name) lat=$($cls.latitude) lng=$($cls.longitude) radius=$($cls.radius_m) m"

# End any open sessions, then start a fresh one
foreach ($s in @((Call "GET" "/sessions/active" $T $null).Data)) {
    if ($s.id) { Call "POST" "/sessions/$($s.id)/end" $T $null | Out-Null }
}
$start = Call "POST" "/sessions/start" $T @{ classroom_id = $cls.id }
$sid = $start.Data.id
Write-Host "Started session id=$sid" -ForegroundColor Cyan

# Get a QR token
$qr = (Call "GET" "/sessions/$sid/qr" $T $null).Data
$token = $qr.token
Write-Host "Got QR token (valid $($qr.expires_in) s): $($token.Substring(0, 20))..." -ForegroundColor Cyan

function Scan($lat, $lng, $acc) {
    return Call "POST" "/attendance/scan" $S @{ qr_token = $token; latitude = $lat; longitude = $lng; accuracy_m = $acc }
}

$lat = [double]$cls.latitude
$lng = [double]$cls.longitude
Show "too far (+1 km)"      "403" (Scan ($lat + 0.01) $lng 10)
Show "weak GPS (500 m)"     "400" (Scan $lat $lng 500)
Show "valid scan"           "201" (Scan $lat $lng 10)
Show "scan again"           "409" (Scan $lat $lng 10)

Write-Host "Teacher's attendance list:" -ForegroundColor Cyan
(Call "GET" "/sessions/$sid/attendance" $T $null).Data | ConvertTo-Json -Depth 4

Write-Host "Waiting 31 s for the QR to expire..." -ForegroundColor Cyan
Start-Sleep -Seconds 31
Show "expired QR" "400" (Scan $lat $lng 10)

Call "POST" "/sessions/$sid/end" $T $null | Out-Null
Show "scan after session ended" "400" (Scan $lat $lng 10)
Write-Host "Done." -ForegroundColor Cyan

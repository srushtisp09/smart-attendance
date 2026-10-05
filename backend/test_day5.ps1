# Day 5 test: device binding + proxy-attendance attempts + fraud flags.
# Run from the backend folder with the server running:
#   powershell -ExecutionPolicy Bypass -File .\test_day5.ps1
# Needs testphotos\me1.jpg and testphotos\me2.jpg (two selfies of you, as for Day 4).
# It creates a second student account (student2@test.com) to play the "friend".

$base = "http://localhost:8000"
$password = "password123"
$photos = Join-Path $PSScriptRoot "testphotos"
foreach ($name in @("me1.jpg", "me2.jpg")) {
    if (-not (Test-Path (Join-Path $photos $name))) { Write-Host "Missing photo: $photos\$name" -ForegroundColor Red; exit 1 }
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

function FormPost($path, $token, $fields, $photoName) {
    $out = Join-Path $env:TEMP "resp_day5.json"
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
    $detail = if ($r.Data -is [string]) { $r.Data } else { "" }
    Write-Host ("{0,-36} got {1,-4} expected {2,-4} {3}" -f $label, $r.Status, $expected, $detail) -ForegroundColor $color
}

# ---- setup: teacher, student1 (you), student2 (the "friend") ----
$T = Login "teacher@test.com"
$S1 = Login "student@test.com"
Call "POST" "/auth/register" $null @{ name = "Friend Student"; email = "student2@test.com"; password = $password; role = "student" } | Out-Null
$S2 = Login "student2@test.com"
$id1 = (Call "GET" "/auth/me" $S1 $null).Data.id
$id2 = (Call "GET" "/auth/me" $S2 $null).Data.id
$cls = @((Call "GET" "/classes/mine" $T $null).Data)[0]
Call "POST" "/classes/join" $S2 @{ join_code = $cls.join_code } | Out-Null   # 409 if already joined: fine
Write-Host "Class $($cls.name). You = student $id1, friend = student $id2" -ForegroundColor Cyan

# clean slate
foreach ($id in @($id1, $id2)) { Call "DELETE" "/device/$id" $T $null | Out-Null }
Call "DELETE" "/face/$id1" $T $null | Out-Null
FormPost "/face/enroll" $S1 @{} "me1.jpg" | Out-Null
$phone1 = "phone-of-student-one-1"
$phone2 = "phone-of-friend-two-22"

Write-Host "--- Device binding ---" -ForegroundColor Cyan
Show "you register your phone"           "201" (Call "POST" "/device/bind" $S1 @{ device_id = $phone1; device_name = "My phone" })
Show "friend tries to register YOUR phone" "409" (Call "POST" "/device/bind" $S2 @{ device_id = $phone1 })
Show "friend registers own phone"        "201" (Call "POST" "/device/bind" $S2 @{ device_id = $phone2 })
Show "you try a second phone"            "409" (Call "POST" "/device/bind" $S1 @{ device_id = "another-phone-123456" })

Write-Host "--- Proxy attempts during a live session ---" -ForegroundColor Cyan
foreach ($sess in @((Call "GET" "/sessions/active" $T $null).Data)) {
    if ($sess.id) { Call "POST" "/sessions/$($sess.id)/end" $T $null | Out-Null }
}
$sid = (Call "POST" "/sessions/start" $T @{ classroom_id = $cls.id }).Data.id
$token = (Call "GET" "/sessions/$sid/qr" $T $null).Data.token
function Fields($device, $lat, $lng) {
    return @{ qr_token = $token; latitude = $lat; longitude = $lng; accuracy_m = 10; device_id = $device }
}
$lat = [double]$cls.latitude
$lng = [double]$cls.longitude

Show "friend scans for you with YOUR phone"   "403" (FormPost "/attendance/scan" $S2 (Fields $phone1 $lat $lng) "me2.jpg")
Show "you scan from an unregistered phone"    "403" (FormPost "/attendance/scan" $S1 (Fields "borrowed-phone-0000" $lat $lng) "me2.jpg")
Show "you scan from 1 km away"                "403" (FormPost "/attendance/scan" $S1 (Fields $phone1 ($lat + 0.01) $lng) "me2.jpg")
Show "you scan properly"                      "201" (FormPost "/attendance/scan" $S1 (Fields $phone1 $lat $lng) "me2.jpg")

Write-Host "--- What the teacher sees ---" -ForegroundColor Cyan
$flags = (Call "GET" "/sessions/$sid/flags" $T $null).Data
foreach ($f in @($flags)) {
    $color = if ($f.severity -eq "high") { "Red" } elseif ($f.severity -eq "medium") { "Yellow" } else { "Gray" }
    Write-Host ("[{0}] {1}: {2} - {3}" -f $f.severity.ToUpper(), $f.student_name, $f.flag, $f.detail) -ForegroundColor $color
}
$events = @((Call "GET" "/sessions/$sid/events" $T $null).Data)
Write-Host "Audit log has $($events.Count) events: $((($events | ForEach-Object { $_.outcome }) -join ', '))" -ForegroundColor Cyan

Call "POST" "/sessions/$sid/end" $T $null | Out-Null
Write-Host "Done." -ForegroundColor Cyan

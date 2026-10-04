# Smart Schedule & Attendance: Backend

FastAPI + PostgreSQL, run with Docker Compose.

## Run it
```powershell
cd backend
copy .env.example .env        # first time only; set a real SECRET_KEY
docker compose up --build     # first time (or when requirements.txt changes)
docker compose up             # every other time
```
Open http://localhost:8000/docs. Stop with Ctrl+C.
Reset the database completely: `docker compose down -v`.

## Day 1 checklist (auth, roles, classes)
Register teacher + student, login (Authorize button), create class, join with code,
teacher roster, student gets 403 on teacher-only endpoints.

## Day 2 checklist (sessions)
1. Teacher: `PATCH /classes/{id}` to set the real college latitude/longitude and radius
2. Teacher: `POST /sessions/start` with `{"classroom_id": 1}` -> 201, `is_active: true`
3. Start again -> 409 (only one active session per class)
4. Student: `GET /sessions/active` -> shows the session (the app uses this to show "Scan QR")
5. Student: `POST /sessions/start` -> 403
6. Teacher: `GET /sessions/{id}/attendance` -> empty list for now
7. Teacher: `POST /sessions/{id}/end` -> 200, `is_active: false`; ending again -> 409
8. Teacher: `GET /sessions/class/{id}` -> session history

## Day 3 checklist (rotating QR + scan with geofence)
1. Teacher: start a session, then `GET /sessions/{id}/qr` -> a `token` (valid 30 s). Press Execute again for a fresh one.
2. Student: `POST /attendance/scan` with `{"qr_token": "<token>", "latitude": <class lat>, "longitude": <class lng>, "accuracy_m": 10}` -> 201
3. Scan again -> 409 (already marked)
4. Wait 30+ s and scan with the old token -> 400 "QR code expired"
5. Use coordinates ~1 km away -> 403 "You are N m from the classroom"
6. `accuracy_m: 500` -> 400 "GPS signal too weak"
7. Teacher: `GET /sessions/{id}/attendance` -> lists the student with the distance
8. End the session, then scan -> 409

## Day 4 checklist (face enrollment + verification)
Put 4 photos in `backend/testphotos/` (this folder is git-ignored): me1.jpg, me2.jpg (two selfies of you),
other.jpg (a different person), noface.jpg (no face). Then run `powershell -ExecutionPolicy Bypass -File .\test_day4.ps1`.
Or by hand in /docs as the student: `POST /face/enroll` (upload me1.jpg) -> 201, enroll again -> 409,
`POST /face/check` with me2.jpg -> match true, with other.jpg -> match false,
`POST /attendance/scan` now takes form fields + a `selfie` file (other.jpg -> 403, me2.jpg -> 201).
Teacher can reset a student's face with `DELETE /face/{student_id}`.

## Roadmap
- Day 3 (done): rotating signed QR + scan endpoint with geofence check
- Day 4 (done): face enrollment/verification
- Day 5: device binding, anti-proxy tests, fraud flags
- Day 6-7: Flutter app

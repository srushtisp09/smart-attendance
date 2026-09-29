# Smart Schedule & Attendance: Backend

## Run it
```bash
cd backend
docker compose up -d                 # Postgres + Redis
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then set a real SECRET_KEY
uvicorn app.main:app --reload
```
Open http://localhost:8000/docs

## Day 1 test checklist (use /docs)
1. `POST /auth/register` as a teacher, then again as a student (different emails)
2. Click **Authorize** in /docs (username = email) and log in as the teacher
3. `POST /classes` with your college's lat/lng (get it from Google Maps: right-click > copy coordinates)
4. Note the `join_code` returned
5. Log in as the student, `POST /classes/join` with that code
6. Log back in as the teacher, `GET /classes/{id}/students` shows the student
7. Try `POST /classes` as the student: expect 403

## Roadmap
- Day 2: sessions table, teacher starts a session
- Day 3-4: rotating signed QR + geofence verification
- Day 5-6: face enrollment/verification, device binding

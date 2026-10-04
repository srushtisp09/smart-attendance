import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_role
from ..geo import haversine_m
from ..face import FaceError, cosine, embedding_from_image, from_bytes
from ..models import AttendanceRecord, ClassSession, Enrollment, FaceEmbedding, Role, User
from ..schemas import ScanOut
from ..security import decode_qr_token

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("/scan", response_model=ScanOut, status_code=201)
def scan(qr_token: str = Form(...),
         latitude: float = Form(..., ge=-90, le=90),
         longitude: float = Form(..., ge=-180, le=180),
         accuracy_m: float = Form(..., ge=0),   # the phone's own estimate of its GPS error, in metres
         selfie: UploadFile = File(...),
         db: Session = Depends(get_db),
         student: User = Depends(require_role(Role.student))):
    """Student scans the teacher's QR with a fresh selfie. Every check must pass before attendance is recorded."""
    # 1. QR must be genuine and fresh
    try:
        session_id = decode_qr_token(qr_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "QR code expired. Scan the new one on the screen.")
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid QR code")

    # 2. Session must still be open
    session = db.get(ClassSession, session_id)
    if not session or not session.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This session is not active")
    classroom = session.classroom

    # 3. Student must be enrolled in this class
    enrolled = db.scalar(select(Enrollment).where(
        Enrollment.student_id == student.id, Enrollment.classroom_id == classroom.id))
    if not enrolled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in this class")

    # 3b. Student must have enrolled their face (cheap check, so it comes before the heavy face work)
    stored_face = db.scalar(select(FaceEmbedding).where(FaceEmbedding.user_id == student.id))
    if not stored_face:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Enroll your face first (POST /face/enroll)")

    # 4. Only one mark per student per session
    already = db.scalar(select(AttendanceRecord).where(
        AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id))
    if already:
        raise HTTPException(status.HTTP_409_CONFLICT, "Attendance already marked for this session")

    # 5. Geofence: a poor GPS fix can't be trusted, then the student must be inside the radius
    if accuracy_m > settings.MAX_GPS_ACCURACY_M:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"GPS signal too weak (±{accuracy_m:.0f} m). Move near a window and retry.")
    distance = haversine_m(latitude, longitude, classroom.latitude, classroom.longitude)
    if distance > classroom.radius_m:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"You are {distance:.0f} m from the classroom (limit {classroom.radius_m} m)")

    # 6. Face: the selfie must match the enrolled face. This is the slowest step, so it runs last.
    try:
        selfie_embedding = embedding_from_image(selfie.file.read())
    except FaceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    score = cosine(from_bytes(stored_face.embedding), selfie_embedding)
    if score < settings.FACE_MATCH_THRESHOLD:
        # Deliberately no score in the message: it would help someone tune a fake. Use /face/check to test.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Face does not match the enrolled student")

    record = AttendanceRecord(session_id=session.id, student_id=student.id,
                              latitude=latitude, longitude=longitude, distance_m=round(distance, 1),
                              face_match_score=round(score, 3))
    db.add(record)
    try:
        db.commit()
    except IntegrityError:  # double-tap race: the unique constraint caught the second insert
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Attendance already marked for this session")
    db.refresh(record)
    return ScanOut(session_id=session.id, class_name=classroom.name,
                   marked_at=record.marked_at, distance_m=record.distance_m,
                   face_match_score=record.face_match_score) 
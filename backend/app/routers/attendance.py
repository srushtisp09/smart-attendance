import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_role
from ..face import FaceError, cosine, embedding_from_image, from_bytes
from ..geo import haversine_m
from ..models import (AttendanceRecord, ClassSession, DeviceBinding, Enrollment, FaceEmbedding,
                      Role, SecurityEvent, User)
from ..schemas import ScanOut
from ..security import decode_qr_token

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("/scan", response_model=ScanOut, status_code=201)
def scan(qr_token: str = Form(...),
         latitude: float = Form(..., ge=-90, le=90),
         longitude: float = Form(..., ge=-180, le=180),
         accuracy_m: float = Form(..., ge=0),   # the phone's own estimate of its GPS error, in metres
         device_id: str = Form(..., min_length=8, max_length=100),   # the ID registered with /device/bind
         selfie: UploadFile = File(...),
         db: Session = Depends(get_db),
         student: User = Depends(require_role(Role.student))):
    """Student scans the teacher's QR with a fresh selfie from their registered phone.
    Every check must pass. Every attempt, pass or fail, is written to the audit log."""
    seen = {"session_id": None, "distance_m": None, "face_score": None}

    def log(outcome: str):
        db.add(SecurityEvent(kind="scan", outcome=outcome, student_id=student.id, session_id=seen["session_id"],
                             device_id=device_id, latitude=latitude, longitude=longitude, accuracy_m=accuracy_m,
                             distance_m=seen["distance_m"], face_score=seen["face_score"]))

    def fail(outcome: str, code: int, detail: str):
        log(outcome)
        db.commit()
        raise HTTPException(code, detail)

    # 1. QR must be genuine and fresh
    try:
        session_id = decode_qr_token(qr_token)
    except jwt.ExpiredSignatureError:
        fail("qr_expired", status.HTTP_400_BAD_REQUEST, "QR code expired. Scan the new one on the screen.")
    except (jwt.PyJWTError, KeyError, ValueError):
        fail("qr_invalid", status.HTTP_400_BAD_REQUEST, "Invalid QR code")

    # 2. Session must still be open
    session = db.get(ClassSession, session_id)
    if not session or not session.is_active:
        fail("session_inactive", status.HTTP_409_CONFLICT, "This session is not active")
    seen["session_id"] = session.id
    classroom = session.classroom

    # 3. Student must be enrolled in this class
    enrolled = db.scalar(select(Enrollment).where(
        Enrollment.student_id == student.id, Enrollment.classroom_id == classroom.id))
    if not enrolled:
        fail("not_enrolled", status.HTTP_403_FORBIDDEN, "You are not enrolled in this class")

    # 3a. Must be the phone registered to this student
    binding = db.scalar(select(DeviceBinding).where(DeviceBinding.user_id == student.id))
    if not binding:
        fail("device_not_bound", status.HTTP_403_FORBIDDEN, "Register this device first (POST /device/bind)")
    if binding.device_id != device_id:
        fail("device_mismatch", status.HTTP_403_FORBIDDEN, "This account is registered to a different device")

    # 3b. Student must have enrolled their face (cheap check, so it comes before the heavy face work)
    stored_face = db.scalar(select(FaceEmbedding).where(FaceEmbedding.user_id == student.id))
    if not stored_face:
        fail("face_not_enrolled", status.HTTP_403_FORBIDDEN, "Enroll your face first (POST /face/enroll)")

    # 4. Only one mark per student per session
    already = db.scalar(select(AttendanceRecord).where(
        AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id))
    if already:
        fail("duplicate", status.HTTP_409_CONFLICT, "Attendance already marked for this session")

    # 5. Geofence: a poor GPS fix can't be trusted, then the student must be inside the radius
    if accuracy_m > settings.MAX_GPS_ACCURACY_M:
        fail("gps_weak", status.HTTP_400_BAD_REQUEST,
             f"GPS signal too weak (±{accuracy_m:.0f} m). Move near a window and retry.")
    distance = haversine_m(latitude, longitude, classroom.latitude, classroom.longitude)
    seen["distance_m"] = round(distance, 1)
    if distance > classroom.radius_m:
        fail("outside_geofence", status.HTTP_403_FORBIDDEN,
             f"You are {distance:.0f} m from the classroom (limit {classroom.radius_m} m)")

    # 6. Face: the selfie must match the enrolled face. This is the slowest step, so it runs last.
    try:
        selfie_embedding = embedding_from_image(selfie.file.read())
    except FaceError as e:
        fail("face_error", status.HTTP_400_BAD_REQUEST, str(e))
    score = cosine(from_bytes(stored_face.embedding), selfie_embedding)
    seen["face_score"] = round(score, 3)
    if score < settings.FACE_MATCH_THRESHOLD:
        # Deliberately no score in the message: it would help someone tune a fake. Use /face/check to test.
        fail("face_mismatch", status.HTTP_403_FORBIDDEN, "Face does not match the enrolled student")

    record = AttendanceRecord(session_id=session.id, student_id=student.id,
                              latitude=latitude, longitude=longitude, distance_m=seen["distance_m"],
                              face_match_score=seen["face_score"])
    db.add(record)
    log("success")
    try:
        db.commit()
    except IntegrityError:  # double-tap race: the unique constraint caught the second insert
        db.rollback()
        fail("duplicate", status.HTTP_409_CONFLICT, "Attendance already marked for this session")
    db.refresh(record)
    return ScanOut(session_id=session.id, class_name=classroom.name,
                   marked_at=record.marked_at, distance_m=record.distance_m,
                   face_match_score=record.face_match_score) 
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_role
from ..geo import haversine_m
from ..models import AttendanceRecord, ClassSession, Enrollment, Role, User
from ..schemas import ScanIn, ScanOut
from ..security import decode_qr_token

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("/scan", response_model=ScanOut, status_code=201)
def scan(data: ScanIn, db: Session = Depends(get_db),
         student: User = Depends(require_role(Role.student))):
    """Student scans the teacher's QR. Every check must pass before attendance is recorded."""
    # 1. QR must be genuine and fresh
    try:
        session_id = decode_qr_token(data.qr_token)
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

    # 4. Only one mark per student per session
    already = db.scalar(select(AttendanceRecord).where(
        AttendanceRecord.session_id == session.id, AttendanceRecord.student_id == student.id))
    if already:
        raise HTTPException(status.HTTP_409_CONFLICT, "Attendance already marked for this session")

    # 5. Geofence: a poor GPS fix can't be trusted, then the student must be inside the radius
    if data.accuracy_m > settings.MAX_GPS_ACCURACY_M:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"GPS signal too weak (±{data.accuracy_m:.0f} m). Move near a window and retry.")
    distance = haversine_m(data.latitude, data.longitude, classroom.latitude, classroom.longitude)
    if distance > classroom.radius_m:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"You are {distance:.0f} m from the classroom (limit {classroom.radius_m} m)")

    record = AttendanceRecord(session_id=session.id, student_id=student.id,
                              latitude=data.latitude, longitude=data.longitude, distance_m=round(distance, 1))
    db.add(record)
    try:
        db.commit()
    except IntegrityError:  # double-tap race: the unique constraint caught the second insert
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Attendance already marked for this session")
    db.refresh(record)
    return ScanOut(session_id=session.id, class_name=classroom.name,
                   marked_at=record.marked_at, distance_m=record.distance_m)
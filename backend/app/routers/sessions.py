from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models import AttendanceRecord, Classroom, ClassSession, Enrollment, Role, SecurityEvent, User
from ..config import settings
from ..schemas import AttendanceOut, EventOut, FlagOut, QrOut, SessionOut, SessionStart
from ..security import create_qr_token

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _owned_class(db: Session, class_id: int, teacher: User) -> Classroom:
    classroom = db.get(Classroom, class_id)
    if not classroom or classroom.teacher_id != teacher.id:
        # Same 404 for "missing" and "not yours", so nobody can probe which class ids exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    return classroom


def _owned_session(db: Session, session_id: int, teacher: User) -> ClassSession:
    session = db.get(ClassSession, session_id)
    if not session or session.classroom.teacher_id != teacher.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return session


@router.post("/start", response_model=SessionOut, status_code=201)
def start_session(data: SessionStart, db: Session = Depends(get_db),
                  teacher: User = Depends(require_role(Role.teacher))):
    """Teacher opens attendance for one of their classes."""
    _owned_class(db, data.classroom_id, teacher)
    already_active = db.scalar(select(ClassSession).where(
        ClassSession.classroom_id == data.classroom_id, ClassSession.ended_at.is_(None)))
    if already_active:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Session {already_active.id} is already active for this class. End it first.")
    session = ClassSession(classroom_id=data.classroom_id)
    db.add(session)
    try:
        db.commit()
    except IntegrityError:  # two "start" requests raced; the unique index caught the second one
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A session is already active for this class")
    db.refresh(session)
    return session


@router.post("/{session_id}/end", response_model=SessionOut)
def end_session(session_id: int, db: Session = Depends(get_db),
                teacher: User = Depends(require_role(Role.teacher))):
    """Teacher closes attendance. After this, scans for the session will be rejected (Day 3)."""
    session = _owned_session(db, session_id, teacher)
    if session.ended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session already ended")
    session.ended_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}/qr", response_model=QrOut)
def session_qr(session_id: int, db: Session = Depends(get_db),
               teacher: User = Depends(require_role(Role.teacher))):
    """The teacher's app calls this every ~15 s and shows the token as a QR code."""
    session = _owned_session(db, session_id, teacher)
    if not session.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session has ended")
    return QrOut(token=create_qr_token(session.id), expires_in=settings.QR_TOKEN_SECONDS)


@router.get("/active", response_model=list[SessionOut])
def active_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Teacher: their classes with an open session. Student: enrolled classes with an open session
    (this is what the app checks to decide whether to show the 'scan QR' button)."""
    q = select(ClassSession).join(Classroom, Classroom.id == ClassSession.classroom_id)\
        .where(ClassSession.ended_at.is_(None))
    if user.role == Role.teacher:
        q = q.where(Classroom.teacher_id == user.id)
    else:
        q = q.join(Enrollment, Enrollment.classroom_id == Classroom.id)\
             .where(Enrollment.student_id == user.id)
    return db.scalars(q.order_by(ClassSession.started_at.desc())).all()


@router.get("/class/{class_id}", response_model=list[SessionOut])
def class_sessions(class_id: int, db: Session = Depends(get_db),
                   teacher: User = Depends(require_role(Role.teacher))):
    """History of all sessions for one of the teacher's classes, newest first."""
    _owned_class(db, class_id, teacher)
    return db.scalars(select(ClassSession).where(ClassSession.classroom_id == class_id)
                      .order_by(ClassSession.started_at.desc())).all()


@router.get("/{session_id}/attendance", response_model=list[AttendanceOut])
def session_attendance(session_id: int, db: Session = Depends(get_db),
                       teacher: User = Depends(require_role(Role.teacher))):
    """Who has marked present in this session (empty until scanning is built on Day 3)."""
    _owned_session(db, session_id, teacher)
    return db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session_id)
                      .order_by(AttendanceRecord.marked_at)).all()


@router.get("/{session_id}/events", response_model=list[EventOut])
def session_events(session_id: int, db: Session = Depends(get_db),
                   teacher: User = Depends(require_role(Role.teacher))):
    """Audit log: every scan attempt for this session, passed or failed, oldest first."""
    _owned_session(db, session_id, teacher)
    return db.scalars(select(SecurityEvent).where(SecurityEvent.session_id == session_id)
                      .order_by(SecurityEvent.created_at, SecurityEvent.id)).all()


@router.get("/{session_id}/flags", response_model=list[FlagOut])
def session_flags(session_id: int, db: Session = Depends(get_db),
                  teacher: User = Depends(require_role(Role.teacher))):
    """Rule-based fraud flags for a session, so the teacher knows who to look at.
    (An ML anomaly detector can be layered on the same event log later.)"""
    _owned_session(db, session_id, teacher)
    events = db.scalars(select(SecurityEvent).where(SecurityEvent.session_id == session_id)
                        .order_by(SecurityEvent.id)).all()
    by_student = defaultdict(list)
    for e in events:
        by_student[e.student_id].append(e)

    flags: list[FlagOut] = []
    for student_id, evs in by_student.items():
        name = evs[0].student.name

        def add(flag, severity, detail):
            flags.append(FlagOut(student_id=student_id, student_name=name, flag=flag,
                                 severity=severity, detail=detail))

        face_fail = [e for e in evs if e.outcome == "face_mismatch"]
        if face_fail:
            best = max(e.face_score for e in face_fail if e.face_score is not None)
            add("face_mismatch", "high",
                f"{len(face_fail)} scan(s) where the selfie did not match this account (best score {best:.2f})")
        dev_fail = [e for e in evs if e.outcome in ("device_mismatch", "device_not_bound")]
        if dev_fail:
            add("unregistered_device", "high", f"{len(dev_fail)} scan(s) from a phone not registered to this student")
        far = [e for e in evs if e.outcome == "outside_geofence"]
        if far:
            closest = min(e.distance_m for e in far if e.distance_m is not None)
            add("outside_classroom", "medium", f"{len(far)} scan(s) from outside the classroom (closest {closest:.0f} m)")
        failures = [e for e in evs if e.outcome not in ("success", "duplicate")]
        if len(failures) >= 3:
            add("repeated_failures", "medium", f"{len(failures)} failed scan attempts in this session")
        weak = [e for e in evs if e.outcome == "success" and e.face_score is not None
                and e.face_score < settings.FACE_MATCH_THRESHOLD + 0.05]
        if weak:
            add("borderline_face_match", "low",
                f"Accepted with a weak face score ({weak[0].face_score:.2f}); worth a quick look")

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(flags, key=lambda f: (order[f.severity], f.student_name)) 
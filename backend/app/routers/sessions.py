from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models import AttendanceRecord, Classroom, ClassSession, Enrollment, Role, User
from ..schemas import AttendanceOut, SessionOut, SessionStart

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


from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_role
from ..face import FaceError, cosine, embedding_from_image, from_bytes, to_bytes
from ..models import Classroom, Enrollment, FaceEmbedding, Role, User
from ..schemas import FaceCheckOut, FaceStatus

router = APIRouter(prefix="/face", tags=["face"])


def _stored(db: Session, user_id: int) -> FaceEmbedding | None:
    return db.scalar(select(FaceEmbedding).where(FaceEmbedding.user_id == user_id))


def _read_embedding(selfie: UploadFile):
    try:
        return embedding_from_image(selfie.file.read())
    except FaceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/status", response_model=FaceStatus)
def face_status(db: Session = Depends(get_db), student: User = Depends(require_role(Role.student))):
    return FaceStatus(enrolled=_stored(db, student.id) is not None)


@router.post("/enroll", response_model=FaceStatus, status_code=201)
def enroll(selfie: UploadFile = File(...), db: Session = Depends(get_db),
           student: User = Depends(require_role(Role.student))):
    """One-time face registration. Only the embedding is saved. A student can't re-enroll on their
    own (otherwise a friend could swap in their face); a teacher resets it via DELETE /face/{student_id}."""
    if _stored(db, student.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Face already enrolled. Ask your teacher to reset it.")
    embedding = _read_embedding(selfie)
    db.add(FaceEmbedding(user_id=student.id, embedding=to_bytes(embedding)))
    db.commit()
    return FaceStatus(enrolled=True)


@router.post("/check", response_model=FaceCheckOut)
def check(selfie: UploadFile = File(...), db: Session = Depends(get_db),
          student: User = Depends(require_role(Role.student))):
    """Compare a selfie with your enrolled face WITHOUT marking attendance (handy for testing)."""
    stored = _stored(db, student.id)
    if not stored:
        raise HTTPException(status.HTTP_409_CONFLICT, "Enroll your face first (POST /face/enroll)")
    score = cosine(from_bytes(stored.embedding), _read_embedding(selfie))
    return FaceCheckOut(score=round(score, 3), match=score >= settings.FACE_MATCH_THRESHOLD,
                        threshold=settings.FACE_MATCH_THRESHOLD)


@router.delete("/{student_id}", status_code=204)
def reset_face(student_id: int, db: Session = Depends(get_db),
               teacher: User = Depends(require_role(Role.teacher))):
    """Teacher removes a student's enrolled face (e.g. bad first photo). Only for students in the teacher's classes."""
    in_my_class = db.scalar(select(Enrollment).join(Classroom, Classroom.id == Enrollment.classroom_id)
                            .where(Enrollment.student_id == student_id, Classroom.teacher_id == teacher.id))
    stored = _stored(db, student_id)
    if not in_my_class or not stored:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No enrolled face found for that student")
    db.delete(stored)
    db.commit()
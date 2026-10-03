import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models import Classroom, Enrollment, Role, User
from ..schemas import ClassCreate, ClassOut, ClassUpdate, JoinIn, UserOut 
router = APIRouter(prefix="/classes", tags=["classes"])


def _new_join_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not db.scalar(select(Classroom).where(Classroom.join_code == code)):
            return code


@router.post("", response_model=ClassOut, status_code=201)
def create_class(data: ClassCreate, db: Session = Depends(get_db),
                 teacher: User = Depends(require_role(Role.teacher))):
    classroom = Classroom(**data.model_dump(), teacher_id=teacher.id, join_code=_new_join_code(db))
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom


@router.patch("/{class_id}", response_model=ClassOut)
def update_class(class_id: int, data: ClassUpdate, db: Session = Depends(get_db),
                 teacher: User = Depends(require_role(Role.teacher))):
    """Fix a class's name, geofence location or radius (e.g. replace placeholder coordinates)."""
    classroom = db.get(Classroom, class_id)
    if not classroom or classroom.teacher_id != teacher.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(classroom, field, value)
    db.commit()
    db.refresh(classroom)
    return classroom


@router.get("/mine", response_model=list[ClassOut])
def my_classes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == Role.teacher:
        q = select(Classroom).where(Classroom.teacher_id == user.id)
    else:
        q = (select(Classroom).join(Enrollment, Enrollment.classroom_id == Classroom.id)
             .where(Enrollment.student_id == user.id))
    return db.scalars(q).all()


@router.post("/join", response_model=ClassOut)
def join_class(data: JoinIn, db: Session = Depends(get_db),
               student: User = Depends(require_role(Role.student))):
    classroom = db.scalar(select(Classroom).where(Classroom.join_code == data.join_code.upper()))
    if not classroom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid join code")
    exists = db.scalar(select(Enrollment).where(
        Enrollment.student_id == student.id, Enrollment.classroom_id == classroom.id))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already enrolled")
    db.add(Enrollment(student_id=student.id, classroom_id=classroom.id))
    db.commit()
    return classroom


@router.get("/{class_id}/students", response_model=list[UserOut])
def roster(class_id: int, db: Session = Depends(get_db),
           teacher: User = Depends(require_role(Role.teacher))):
    classroom = db.get(Classroom, class_id)
    if not classroom or classroom.teacher_id != teacher.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    return db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id)
                      .where(Enrollment.classroom_id == class_id)).all()

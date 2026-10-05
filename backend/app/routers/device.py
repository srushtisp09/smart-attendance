from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..models import Classroom, DeviceBinding, Enrollment, Role, SecurityEvent, User
from ..schemas import BindIn, DeviceStatus

router = APIRouter(prefix="/device", tags=["device"])


def _status(binding: DeviceBinding | None) -> DeviceStatus:
    if not binding:
        return DeviceStatus(bound=False)
    return DeviceStatus(bound=True, device_name=binding.device_name, bound_at=binding.created_at)


@router.get("/status", response_model=DeviceStatus)
def device_status(db: Session = Depends(get_db), student: User = Depends(require_role(Role.student))):
    return _status(db.scalar(select(DeviceBinding).where(DeviceBinding.user_id == student.id)))


@router.post("/bind", response_model=DeviceStatus)
def bind_device(data: BindIn, response: Response, db: Session = Depends(get_db),
                student: User = Depends(require_role(Role.student))):
    """Register this phone to the student's account. One phone per student, one student per phone."""
    mine = db.scalar(select(DeviceBinding).where(DeviceBinding.user_id == student.id))
    if mine:
        if mine.device_id == data.device_id:
            return _status(mine)  # same phone again: fine
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Your account is already bound to another device. Ask your teacher to reset it.")
    taken = db.scalar(select(DeviceBinding).where(DeviceBinding.device_id == data.device_id))
    if taken:
        # Someone is trying to use a phone that belongs to another student: log it for the teacher.
        db.add(SecurityEvent(kind="device_bind", outcome="device_conflict", student_id=student.id,
                             device_id=data.device_id))
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "This device is already registered to another student.")
    binding = DeviceBinding(user_id=student.id, device_id=data.device_id, device_name=data.device_name)
    db.add(binding)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This device is already registered to another student.")
    db.refresh(binding)
    response.status_code = status.HTTP_201_CREATED
    return _status(binding)


@router.delete("/{student_id}", status_code=204)
def reset_device(student_id: int, db: Session = Depends(get_db),
                 teacher: User = Depends(require_role(Role.teacher))):
    """Teacher unbinds a student's phone (lost or new phone). Only for students in the teacher's classes."""
    in_my_class = db.scalar(select(Enrollment).join(Classroom, Classroom.id == Enrollment.classroom_id)
                            .where(Enrollment.student_id == student_id, Classroom.teacher_id == teacher.id))
    binding = db.scalar(select(DeviceBinding).where(DeviceBinding.user_id == student_id))
    if not in_my_class or not binding:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No registered device found for that student")
    db.delete(binding)
    db.commit()
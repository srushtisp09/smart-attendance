from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import Role


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt limit is 72 bytes
    role: Role = Role.student
    roll_no: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    role: Role
    roll_no: str | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ClassCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=50, ge=10, le=500)


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    join_code: str
    teacher_id: int
    latitude: float
    longitude: float
    radius_m: int
    created_at: datetime


class JoinIn(BaseModel):
    join_code: str
class ClassUpdate(BaseModel):
    """All fields optional: send only what you want to change."""
    name: str | None = Field(default=None, min_length=2, max_length=150)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=10, le=500)


class SessionStart(BaseModel):
    classroom_id: int


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    classroom_id: int
    class_name: str
    started_at: datetime
    ended_at: datetime | None
    is_active: bool


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student: UserOut
    marked_at: datetime
    distance_m: float | None
    face_match_score: float | None
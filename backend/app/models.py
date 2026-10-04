import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.student)
    roll_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Classroom(Base):
    """A course/section taught by one teacher. Holds the geofence for QR attendance."""
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    join_code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    teacher: Mapped[User] = relationship()
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="classroom")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "classroom_id", name="uq_student_class"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    student: Mapped[User] = relationship()
    classroom: Mapped[Classroom] = relationship(back_populates="enrollments")


class ClassSession(Base):
    """One actual lecture. The teacher starts it (attendance opens) and ends it (attendance closes)."""
    __tablename__ = "class_sessions"
    __table_args__ = (
        # Database-level guarantee: at most ONE active (not yet ended) session per class.
        Index("uq_one_active_session_per_class", "classroom_id", unique=True,
              postgresql_where=text("ended_at IS NULL"), sqlite_where=text("ended_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(ForeignKey("classrooms.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    classroom: Mapped[Classroom] = relationship()
    records: Mapped[list["AttendanceRecord"]] = relationship(back_populates="session")

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def class_name(self) -> str:
        return self.classroom.name


class AttendanceRecord(Base):
    """One student marked present in one session. The location and face columns are filled in on Days 3-5."""
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_one_mark_per_session"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    session: Mapped[ClassSession] = relationship(back_populates="records")
    student: Mapped[User] = relationship()


class FaceEmbedding(Base):
    """A student's face as 512 numbers (float32). The photo itself is never stored."""
    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship() 
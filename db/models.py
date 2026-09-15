import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, Float, JSON, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_candidate_org_email"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    education: Mapped[str | None] = mapped_column(String(255), nullable=True)
    experience: Mapped[float | None] = mapped_column(Float, nullable=True)
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tech_stack: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    resume_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resume_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))

    sessions: Mapped[list["Session"]] = relationship(back_populates="candidate")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id"))
    current_step: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    candidate: Mapped["Candidate"] = relationship(back_populates="sessions")
    questions: Mapped[list["GeneratedQuestion"]] = relationship(back_populates="session")
    messages: Mapped[list["Message"]] = relationship(back_populates="session")


class GeneratedQuestion(Base):
    __tablename__ = "generated_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    technology: Mapped[str] = mapped_column(String(80))
    question_text: Mapped[str] = mapped_column(Text)
    difficulty_tier: Mapped[str] = mapped_column(String(20))
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    correctness_score: Mapped[int | None] = mapped_column(nullable=True)
    reasoning_score: Mapped[int | None] = mapped_column(nullable=True)
    communication_score: Mapped[int | None] = mapped_column(nullable=True)
    score_justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["Session"] = relationship(back_populates="questions")

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    is_pasted: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    session: Mapped["Session"] = relationship(back_populates="messages")

class Recruiter(Base):
    __tablename__ = "recruiters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    password_salt: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    role: Mapped[str] = mapped_column(String(20), default="recruiter")  # "admin" | "recruiter"

class SessionLog(Base):
    __tablename__ = "session_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    event_type: Mapped[str] = mapped_column(String(20))  # "step_transition" | "error" | "info"
    detail: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class InviteToken(Base):
    __tablename__ = "invite_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recruiters.id"), nullable=True)
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recruiters.id", ondelete="SET NULL"), nullable=True)
    used_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    used_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    used_user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recruiters.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))


class RecruiterSession(Base):
    __tablename__ = "recruiter_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recruiters.id", ondelete="SET NULL"), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    email_attempted: Mapped[str] = mapped_column(String(255))
    success: Mapped[bool] = mapped_column(Boolean)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "logout" | "expired" | "invalidated"


class MCQQuestion(Base):
    __tablename__ = "mcq_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    technology: Mapped[str] = mapped_column(String(80))
    difficulty_tier: Mapped[str] = mapped_column(String(20))  # fundamentals | applied | advanced
    format: Mapped[str] = mapped_column(String(30))  # debugging_triage | architecture_tradeoff | spot_the_bug | systems_at_scale | decisional_judgment
    question_text: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)  # [{"id": ..., "text": ...}, ...]
    correct_option_id: Mapped[str] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class MCQAssessment(Base):
    __tablename__ = "mcq_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress | completed
    current_question_index: Mapped[int] = mapped_column(default=0)
    tab_switch_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class MCQAnswer(Base):
    __tablename__ = "mcq_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mcq_assessments.id"))
    question_index: Mapped[int] = mapped_column()
    question_type: Mapped[str] = mapped_column(String(20))  # technical | behavioral | open_text
    pool_question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mcq_questions.id"), nullable=True)
    question_text: Mapped[str] = mapped_column(Text)
    options_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    selected_option_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
    text_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    difficulty_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    question_started_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    time_taken_seconds: Mapped[int | None] = mapped_column(nullable=True)
    tab_switch_count: Mapped[int] = mapped_column(default=0)
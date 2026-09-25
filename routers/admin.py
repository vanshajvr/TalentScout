import uuid
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Recruiter, InviteToken, Organization, Candidate
from utils.auth import require_admin, hash_password, issue_token
import re
import secrets

from datetime import datetime, timedelta

from utils.validators import is_valid_email
from utils.rate_limit import check_rate_limit

from utils.schemas import AuthResponse

router = APIRouter(prefix="/admin")
class OrgSignupRequest(BaseModel):
    org_name: str = Field(max_length=60)
    name: str = Field(max_length=120)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


@router.post("/signup", response_model=AuthResponse)
def create_org_and_admin(body: OrgSignupRequest, request: Request, db: SQLASession = Depends(get_db)):
    ip = request.client.host if request.client else None
    check_rate_limit(f"admin_signup:{ip or 'unknown'}", max_requests=3, window_minutes=60)

    slug = re.sub(r"[^a-z0-9-]", "-", body.org_name.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="Please enter a valid organization name")
    if db.query(Organization).filter(Organization.slug == slug).first():
        raise HTTPException(status_code=400, detail="An organization with this name already exists")

    if not is_valid_email(body.email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    existing = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    # Org and admin are created together in one transaction — if anything fails between
    # them, neither is persisted, instead of leaving an orphan Organization row behind
    # (which previously happened whenever email validation or the duplicate-account
    # check failed after the org had already been committed on its own).
    org = Organization(name=body.org_name, slug=slug)
    db.add(org)
    db.flush()  # assigns org.id without committing yet

    password_hash = hash_password(body.password)
    recruiter = Recruiter(
        name=body.name, email=body.email, password_hash=password_hash,
        org_id=org.id, role="admin",
    )
    db.add(recruiter)
    db.commit()
    db.refresh(recruiter)
    db.refresh(org)

    token = issue_token(
        recruiter, db,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    return AuthResponse(token=token, name=recruiter.name)


@router.get("/team")
def list_team(db: SQLASession = Depends(get_db), admin: Recruiter = Depends(require_admin)):
    recruiters = db.query(Recruiter).filter(Recruiter.org_id == admin.org_id).all()
    return [
        {"id": str(r.id), "name": r.name, "email": r.email, "role": r.role,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in recruiters
    ]


class RemoveRecruiterRequest(BaseModel):
    recruiter_id: str


@router.post("/team/remove")
def remove_recruiter(
    body: RemoveRecruiterRequest,
    db: SQLASession = Depends(get_db),
    admin: Recruiter = Depends(require_admin),
):
    try:
        target_id = uuid.UUID(body.recruiter_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recruiter_id")

    target = db.get(Recruiter, target_id)
    if target is None or target.org_id != admin.org_id:
        raise HTTPException(status_code=404, detail="Recruiter not found")

    if target.role == "admin":
        remaining_admins = db.query(Recruiter).filter(
            Recruiter.org_id == admin.org_id, Recruiter.role == "admin", Recruiter.id != target.id
        ).count()
        if remaining_admins == 0:
            raise HTTPException(status_code=400, detail="Can't remove the last admin in this org")

    if target_id == admin.id:
        raise HTTPException(status_code=400, detail="You can't remove your own account")

    db.delete(target)
    db.commit()
    return {"removed": True}

class InviteTokenResponse(BaseModel):
    code: str


class CreateInviteRequest(BaseModel):
    expires_in_days: int | None = None


@router.post("/invite", response_model=InviteTokenResponse)
def create_invite_token(
    body: CreateInviteRequest = CreateInviteRequest(),
    db: SQLASession = Depends(get_db),
    admin: Recruiter = Depends(require_admin),
):
    code = secrets.token_urlsafe(12)
    expires_at = (
        datetime.utcnow() + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None else None
    )
    token_row = InviteToken(code=code, org_id=admin.org_id, created_by=admin.id, expires_at=expires_at)
    db.add(token_row)
    db.commit()
    return InviteTokenResponse(code=code)


class RevokeInviteRequest(BaseModel):
    code: str


@router.post("/invite/revoke")
def revoke_invite_token(
    body: RevokeInviteRequest,
    db: SQLASession = Depends(get_db),
    admin: Recruiter = Depends(require_admin),
):
    token_row = db.query(InviteToken).filter(
        InviteToken.code == body.code, InviteToken.org_id == admin.org_id
    ).first()
    if token_row is None:
        raise HTTPException(status_code=404, detail="Invite code not found")

    token_row.revoked_at = datetime.utcnow()
    token_row.revoked_by = admin.id
    db.commit()
    return {"revoked": True}


@router.get("/invites")
def list_invites(db: SQLASession = Depends(get_db), admin: Recruiter = Depends(require_admin)):
    tokens = db.query(InviteToken).filter(InviteToken.org_id == admin.org_id).order_by(InviteToken.created_at.desc()).all()
    now = datetime.utcnow()
    return [
        {
            "code": t.code, "created_at": t.created_at.isoformat() if t.created_at else None,
            "used": t.used_at is not None,
            "used_by_name": t.used_by_name,
            "used_at": t.used_at.isoformat() if t.used_at else None,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "expired": t.expires_at is not None and t.used_at is None and now > t.expires_at,
            "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
        }
        for t in tokens
    ]

class UpdateRoleRequest(BaseModel):
    recruiter_id: str
    new_role: str


@router.post("/team/role")
def update_recruiter_role(
    body: UpdateRoleRequest,
    db: SQLASession = Depends(get_db),
    admin: Recruiter = Depends(require_admin),
):
    if body.new_role not in ("admin", "recruiter"):
        raise HTTPException(status_code=400, detail="Invalid role")

    try:
        target_id = uuid.UUID(body.recruiter_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recruiter_id")

    if target_id == admin.id:
        # Changing your own role — especially demoting yourself — immediately
        # revokes your own session with no warning. Matches the same
        # unconditional block already used for self-removal below: this isn't
        # something to allow with a warning, it's disabled outright. An admin
        # who wants to step down needs another admin to do it for them.
        raise HTTPException(status_code=400, detail="You can't change your own role")

    target = db.get(Recruiter, target_id)
    if target is None or target.org_id != admin.org_id:
        raise HTTPException(status_code=404, detail="Recruiter not found")

    target.role = body.new_role
    db.commit()
    return {"id": str(target.id), "role": target.role}

@router.get("/overview")
def admin_overview(db: SQLASession = Depends(get_db), admin: Recruiter = Depends(require_admin)):
    org = db.get(Organization, admin.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    team_count = db.query(Recruiter).filter(Recruiter.org_id == admin.org_id).count()
    candidate_count = db.query(Candidate).filter(Candidate.org_id == admin.org_id).count()
    now = datetime.utcnow()
    pending_invites = db.query(InviteToken).filter(
        InviteToken.org_id == admin.org_id,
        InviteToken.used_at.is_(None),
        InviteToken.revoked_at.is_(None),
        (InviteToken.expires_at.is_(None)) | (InviteToken.expires_at > now),
    ).count()
    return {
        "org_name": org.name, "org_slug": org.slug,
        "team_count": team_count, "candidate_count": candidate_count,
        "pending_invites": pending_invites,
    }
import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Recruiter, InviteToken, Organization, Candidate
from utils.auth import require_admin, hash_password, issue_token
import re
import secrets

from datetime import datetime

from utils.validators import is_valid_email

from utils.schemas import AuthResponse

router = APIRouter(prefix="/admin")
class OrgSignupRequest(BaseModel):
    org_name: str
    name: str
    email: str
    password: str


@router.post("/signup", response_model=AuthResponse)
def create_org_and_admin(body: OrgSignupRequest, db: SQLASession = Depends(get_db)):

    slug = re.sub(r"[^a-z0-9-]", "-", body.org_name.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="Please enter a valid organization name")
    if db.query(Organization).filter(Organization.slug == slug).first():
        raise HTTPException(status_code=400, detail="An organization with this name already exists")

    org = Organization(name=body.org_name, slug=slug)
    db.add(org)
    db.commit()
    db.refresh(org)

    if not is_valid_email(body.email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    existing = db.query(Recruiter).filter(Recruiter.email == body.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    password_hash, salt = hash_password(body.password)
    recruiter = Recruiter(
        name=body.name, email=body.email, password_hash=password_hash,
        password_salt=salt, org_id=org.id, role="admin",
    )
    db.add(recruiter)
    db.commit()
    db.refresh(recruiter)

    token = secrets.token_urlsafe(32)
    token = issue_token(str(recruiter.id))    
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

    if target_id == admin.id:
        raise HTTPException(status_code=400, detail="You can't remove your own account")

    target = db.get(Recruiter, target_id)
    if target is None or target.org_id != admin.org_id:
        raise HTTPException(status_code=404, detail="Recruiter not found")

    if target.role == "admin":
        remaining_admins = db.query(Recruiter).filter(
            Recruiter.org_id == admin.org_id, Recruiter.role == "admin", Recruiter.id != target.id
        ).count()
        if remaining_admins == 0:
            raise HTTPException(status_code=400, detail="Can't remove the last admin in this org")

    db.delete(target)
    db.commit()
    return {"removed": True}


class InviteTokenResponse(BaseModel):
    code: str


@router.post("/invite", response_model=InviteTokenResponse)
def create_invite_token(db: SQLASession = Depends(get_db), admin: Recruiter = Depends(require_admin)):
    code = secrets.token_urlsafe(12)
    token_row = InviteToken(code=code, org_id=admin.org_id, created_by=admin.id)
    db.add(token_row)
    db.commit()
    return InviteTokenResponse(code=code)


@router.get("/invites")
def list_invites(db: SQLASession = Depends(get_db), admin: Recruiter = Depends(require_admin)):
    tokens = db.query(InviteToken).filter(InviteToken.org_id == admin.org_id).order_by(InviteToken.created_at.desc()).all()
    used_ids = {t.used_by for t in tokens if t.used_by}
    used_recruiters = {
        r.id: r.name for r in db.query(Recruiter).filter(Recruiter.id.in_(used_ids)).all()
    } if used_ids else {}
    return [
        {
            "code": t.code, "created_at": t.created_at.isoformat() if t.created_at else None,
            "used": t.used_by is not None,
            "used_by_name": used_recruiters.get(t.used_by) if t.used_by else None,
            "used_at": t.used_at.isoformat() if t.used_at else None,
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

    target = db.get(Recruiter, target_id)
    if target is None or target.org_id != admin.org_id:
        raise HTTPException(status_code=404, detail="Recruiter not found")

    if target.id == admin.id and body.new_role == "recruiter":
        remaining_admins = db.query(Recruiter).filter(
            Recruiter.org_id == admin.org_id, Recruiter.role == "admin", Recruiter.id != target.id
        ).count()
        if remaining_admins == 0:
            raise HTTPException(status_code=400, detail="Can't demote the last admin in this org")

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
    pending_invites = db.query(InviteToken).filter(
        InviteToken.org_id == admin.org_id, InviteToken.used_by.is_(None)
    ).count()
    return {
        "org_name": org.name, "org_slug": org.slug,
        "team_count": team_count, "candidate_count": candidate_count,
        "pending_invites": pending_invites,
    }
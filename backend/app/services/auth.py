from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import CompanyProfile, User
from app.services.niche import LEGACY_IT_KEYWORDS, TRANSPORT_PROFILE_KEYWORDS, TRANSPORT_PROFILE_OKPD

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return int(payload["sub"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if creds is None:
        return None
    try:
        user_id = decode_token(creds.credentials)
    except HTTPException:
        # Stale/invalid JWT must not break public endpoints
        return None
    return db.get(User, user_id)


def get_current_user(user: User | None = Depends(get_current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


def ensure_default_admin(db: Session) -> User:
    user = db.query(User).filter(User.email == settings.default_admin_email).one_or_none()
    if user:
        profile = db.query(CompanyProfile).filter(CompanyProfile.user_id == user.id).one_or_none()
        if profile:
            existing_kw = {str(k).lower() for k in (profile.keywords or [])}
            # Migrate only legacy IT/construction profiles — never clobber custom edits
            if not existing_kw or existing_kw & {k.lower() for k in LEGACY_IT_KEYWORDS}:
                profile.company_name = profile.company_name or "Грузоперевозки / рефрижератор"
                profile.okpd_prefixes = TRANSPORT_PROFILE_OKPD
                profile.keywords = TRANSPORT_PROFILE_KEYWORDS
                db.commit()
        return user
    user = User(
        email=settings.default_admin_email,
        password_hash=hash_password(settings.default_admin_password),
        name="Admin",
        is_admin=True,
    )
    db.add(user)
    db.flush()
    db.add(
        CompanyProfile(
            user_id=user.id,
            company_name="Грузоперевозки / рефрижератор",
            okpd_prefixes=TRANSPORT_PROFILE_OKPD,
            regions=["Москва", "Московская область", "Санкт-Петербург", "Краснодарский край"],
            keywords=TRANSPORT_PROFILE_KEYWORDS,
            min_price=50_000,
            max_price=30_000_000,
        )
    )
    db.commit()
    db.refresh(user)
    return user

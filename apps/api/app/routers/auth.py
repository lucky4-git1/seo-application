from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import schemas, services
from app.database import get_db
from app.ratelimit import AUTH_LIMIT, limiter
from app.security import get_current_user

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=schemas.UserOut, status_code=201)
@limiter.limit(AUTH_LIMIT)
def register(request: Request, body: schemas.RegisterIn, db: Session = Depends(get_db)):
    return services.register(db, email=body.email, password=body.password, display_name=body.display_name)


@router.post("/auth/login", response_model=schemas.TokenOut)
@limiter.limit(AUTH_LIMIT)
def login(request: Request, body: schemas.LoginIn, db: Session = Depends(get_db)):
    _, token = services.login(db, email=body.email, password=body.password)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/auth/logout", status_code=204)
def logout():
    # Stateless JWT MVP: client discards token. Server-side revocation list is a later phase.
    return None


@router.get("/auth/me", response_model=schemas.UserOut)
def me(user=Depends(get_current_user)):
    return user

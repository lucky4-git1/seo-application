"""Pydantic schemas — validation boundary (route <-> service)."""
from __future__ import annotations

import re
import uuid
from pydantic import BaseModel, EmailStr, Field, field_validator

# ---------- Auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    email_verified: bool

    model_config = {"from_attributes": True}


# ---------- Organizations ----------
class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    email: EmailStr
    role: str = Field(default="MEMBER")

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str) -> str:
        if v not in ("OWNER", "ADMIN", "MEMBER"):
            raise ValueError("role must be OWNER|ADMIN|MEMBER")
        return v


# ---------- Projects ----------
DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})*\.[a-z]{2,}$", re.IGNORECASE)

def normalize_domain(raw: str) -> str:
    d = raw.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    d = d.split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=3, max_length=253)
    country: str = Field(default="US", min_length=2, max_length=2)
    language: str = Field(default="en", min_length=2, max_length=10)
    device: str = Field(default="DESKTOP")
    competitors: list[str] = Field(default_factory=list)

    @field_validator("domain")
    @classmethod
    def norm_domain(cls, v: str) -> str:
        d = normalize_domain(v)
        if not DOMAIN_RE.match(d):
            raise ValueError("invalid domain")
        return d

    @field_validator("device")
    @classmethod
    def check_device(cls, v: str) -> str:
        if v not in ("DESKTOP", "MOBILE"):
            raise ValueError("device must be DESKTOP|MOBILE")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = Field(default=None, min_length=2, max_length=10)
    device: str | None = None
    competitors: list[str] | None = None
    is_archived: bool | None = None

    @field_validator("device")
    @classmethod
    def check_device(cls, v: str | None) -> str | None:
        if v is not None and v not in ("DESKTOP", "MOBILE"):
            raise ValueError("device must be DESKTOP|MOBILE")
        return v

    @field_validator("competitors")
    @classmethod
    def check_competitors(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = [normalize_domain(e) for e in v if e and e.strip()]
        if any(not DOMAIN_RE.match(d) for d in cleaned):
            raise ValueError("invalid competitor domain")
        return cleaned


class ProjectOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    domain: str
    country: str
    language: str
    device: str
    competitors: list[str] = []
    is_archived: bool

    model_config = {"from_attributes": True}


# ---------- Pagination ----------
class Page(BaseModel):
    items: list
    page: int
    page_size: int
    total: int

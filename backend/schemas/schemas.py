"""Pydantic request/response schemas."""
from typing import Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    employee_id: Optional[str] = None
    account_type: Optional[str] = None
    account_status: Optional[str] = None


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AccountCreateRequest(BaseModel):
    employee_id: str
    username: str
    password: str
    account_type: str = "Employee"
    account_status: str = "Active"


class AccountUpdateRequest(BaseModel):
    employee_id: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    account_type: Optional[str] = None
    account_status: Optional[str] = None

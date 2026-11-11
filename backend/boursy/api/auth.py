"""Single-user login with a password from the environment and a signed session cookie."""

import hmac
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

FAILED_LOGIN_DELAY_S = 1.0


class LoginIn(BaseModel):
    password: str


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/login")
def login(body: LoginIn, request: Request) -> dict:
    expected = request.app.state.settings.app_password
    if not expected:
        raise HTTPException(status_code=503, detail="BOURSY_APP_PASSWORD is not configured")
    if not hmac.compare_digest(body.password.encode(), expected.encode()):
        time.sleep(FAILED_LOGIN_DELAY_S)  # slow down guessing
        raise HTTPException(status_code=401, detail="Wrong password")
    request.session["user"] = "owner"
    return {"user": "owner"}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    return {"user": require_user(request)}

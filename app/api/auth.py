"""Authentication routes."""
import os
from datetime import datetime, timedelta
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.db.users import create_user, get_user_by_email, get_user_by_id, init_users_table

SECRET_KEY = os.getenv("SECRET_KEY", "vibe-check-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

router = APIRouter(prefix="/auth", tags=["auth"])
init_users_table()


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3)
    name: str = Field(..., min_length=1, max_length=60)
    password: str = Field(..., min_length=6)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    avatar_seed: int


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)]) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        return get_user_by_id(user_id)
    except (JWTError, ValueError, TypeError):
        return None


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest):
    hashed = hash_password(body.password)
    import random
    seed = random.randint(1, 70)
    user = create_user(body.email, body.name, hashed, seed)
    if not user:
        raise HTTPException(status_code=400, detail="Email already registered")
    token = create_access_token(user["id"])
    return TokenResponse(access_token=token, user={"id": user["id"], "email": user["email"], "name": user["name"], "avatar_seed": user["avatar_seed"]})


@router.post("/token", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()):
    user = get_user_by_email(form.username)
    if not user or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user["id"])
    return TokenResponse(access_token=token, user={"id": user["id"], "email": user["email"], "name": user["name"], "avatar_seed": user["avatar_seed"]})


@router.post("/login", response_model=TokenResponse)
async def login_json(body: dict):
    email = body.get("email", "")
    password = body.get("password", "")
    user = get_user_by_email(email)
    if not user or not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user["id"])
    return TokenResponse(access_token=token, user={"id": user["id"], "email": user["email"], "name": user["name"], "avatar_seed": user["avatar_seed"]})


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[dict | None, Depends(get_current_user)]):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return current_user

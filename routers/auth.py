from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
from auth_schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from database import get_db
from db_models import User
from dependencies import get_current_user
from security import (
    create_access_token,
    hash_password,
    verify_dummy,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = body.email.lower()
    conflict = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="An account with this email already exists",
    )

    if db.scalar(select(User).where(User.email == email)):
        raise conflict

    user = User(name=body.name, email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two simultaneous registrations with the same email
        db.rollback()
        raise conflict
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
    )

    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        verify_dummy(body.password)
        raise invalid
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        raise invalid

    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user,
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
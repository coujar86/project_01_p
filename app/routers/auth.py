from redis.asyncio import Redis
from fastapi import APIRouter, Request, Depends, Form, Response, status
from fastapi.responses import RedirectResponse
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.templates import templates
from app.db.database import get_db, get_redis
from app.db.schemas import UserCreate, UserLogin
from app.auth.dependencies import get_user_id, set_auth_cookies
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/signup")
async def signup_ui(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html", context={})


@router.post("/signup")
async def signup(
    name: str = Form(..., min_length=2, max_length=100),
    email: EmailStr = Form(...),
    password: str = Form(..., min_length=2, max_length=32),
    db: AsyncSession = Depends(get_db),
):
    await AuthService.signup(
        db, user=UserCreate(name=name, email=email, password=password)
    )
    return RedirectResponse("/blogs", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login")
async def login_ui(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})


@router.post("/login")
async def login(
    email: EmailStr = Form(...),
    password: str = Form(..., min_length=2, max_length=32),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    _, session_id = await AuthService.login(
        db, redis, user=UserLogin(email=email, password=password)
    )

    response = RedirectResponse("/blogs", status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(response, session_id)
    return response


@router.get("/logout")
async def logout(request: Request, redis: Redis = Depends(get_redis)):
    session_id = request.cookies.get("session_id")
    await AuthService.logout(redis, session_id)

    response = RedirectResponse("/blogs", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_id", path="/")
    return response

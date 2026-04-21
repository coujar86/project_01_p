from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    name: str
    password: str


class UserLogin(UserBase):
    password: str


class UserRead(UserBase):
    id: int
    name: str


class UserInDB(UserRead):
    password: str

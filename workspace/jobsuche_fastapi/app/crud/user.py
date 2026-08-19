# app/crud/user.py
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import select, update, delete
from app.models.user import User, Profile, SavedJobLink
from app.core.security import hash_password, verify_password
from typing import Optional, List

async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    result = await session.exec(select(User).where(User.email == email))
    return result.one_or_none()

async def create_user(session: AsyncSession, email: str, password: str, full_name: Optional[str]) -> User:
    hashed = hash_password(password)
    user = User(email=email, hashed_password=hashed, full_name=full_name)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Leeres Profil anlegen
    profile = Profile(user_id=user.id)
    session.add(profile)
    await session.commit()
    return user

async def authenticate_user(session: AsyncSession, email: str, password: str) -> Optional[User]:
    user = await get_user_by_email(session, email)
    if user and verify_password(password, user.hashed_password):
        return user
    return None

async def update_profile(session: AsyncSession, user_id: int, **kwargs):
    stmt = update(Profile).where(Profile.user_id == user_id).values(**kwargs)
    await session.exec(stmt)
    await session.commit()

async def get_profile(session: AsyncSession, user_id: int) -> Optional[Profile]:
    result = await session.exec(select(Profile).where(Profile.user_id == user_id))
    return result.one_or_none()

async def toggle_save_job(session: AsyncSession, user_id: int, job_id: int):
    """Bookmark / Entfernen eines Jobs."""
    link = await session.get(SavedJobLink, (user_id, job_id))
    if link:
        await session.delete(link)
    else:
        session.add(SavedJobLink(user_id=user_id, job_id=job_id))
    await session.commit()

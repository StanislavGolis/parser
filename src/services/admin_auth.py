# src/services/admin_auth.py
"""Админ-аккаунты: вход по email+паролю и восстановление пароля.

Админка исторически открывается общим токеном `ADMIN_TOKEN`. Чтобы доступ нельзя
было потерять, добавлены админ-аккаунты (список `ADMIN_EMAILS`): по email+паролю
панель получает тот же токен, а забытый пароль сбрасывается ссылкой из письма
либо командой на сервере (`python -m src.cli.admin set-password`).

Никаких новых зависимостей: пароли — PBKDF2 из `services/auth.py`, токены
восстановления — `secrets` + sha256.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.models import AdminPasswordReset, User, UserSession
from src.services import auth as auth_service

RESET_SUBJECT = "DREDGE: восстановление доступа в админку"


def is_admin_email(email: str) -> bool:
    """Разрешён ли адрес для входа в админку (allowlist ADMIN_EMAILS)."""
    return (email or "").strip().lower() in settings.admin_emails


def reset_link(base_url: str, token: str) -> str:
    """Ссылка на страницу сброса пароля."""
    return f"{base_url.rstrip('/')}/admin/reset?token={token}"


def reset_email_text(link: str, ttl_minutes: int) -> str:
    """Текст письма со ссылкой восстановления."""
    return (
        "Здравствуйте!\n\n"
        "Запрошено восстановление доступа в админку DREDGE.\n"
        f"Ссылка действует {ttl_minutes} мин и срабатывает один раз:\n\n"
        f"{link}\n\n"
        "Если это не вы — просто проигнорируйте письмо.\n"
    )


async def get_admin(session: AsyncSession, email: str) -> Optional[User]:
    """Админ-аккаунт по email (только адреса из allowlist)."""
    email = (email or "").strip().lower()
    if not email or not is_admin_email(email):
        return None
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def ensure_admin(
    session: AsyncSession, email: str, password: Optional[str] = None
) -> User:
    """Создаёт админ-аккаунт (или делает существующий админом).

    Вызывается CLI-командой и при запросе восстановления: адрес из `ADMIN_EMAILS`
    всегда должен существовать, иначе письмо уйдёт «в никуда».
    """
    email = (email or "").strip().lower()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            # Пароль-заглушка: вход возможен только после сброса/установки пароля
            password_hash=auth_service.hash_password(password or auth_service.new_token()),
            is_admin=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    if not user.is_admin:
        user.is_admin = True
    if password:
        user.password_hash = auth_service.hash_password(password)
    await session.commit()
    return user


async def create_reset_token(session: AsyncSession, user: User) -> str:
    """Одноразовый токен восстановления (в БД — только sha256, TTL из настроек)."""
    raw_token = auth_service.new_token()
    session.add(
        AdminPasswordReset(
            user_id=user.id,
            token_hash=auth_service.token_hash(raw_token),
            expires_at=datetime.utcnow()
            + timedelta(minutes=settings.ADMIN_RESET_TTL_MINUTES),
        )
    )
    await session.commit()
    return raw_token


async def consume_reset_token(
    session: AsyncSession,
    raw_token: str,
    new_password: str,
    *,
    promote_admin: bool = True,
) -> User:
    """Меняет пароль по одноразовой ссылке.

    Бросает `ValueError` с понятным текстом: ссылка неизвестна, просрочена или
    уже использована. После смены пароля все сессии пользователя удаляются.

    `promote_admin=False` — ссылка выдана обычному посетителю из админки: права
    админа не выдаём (иначе любой сброс пароля повышал бы в админы).
    """
    token_hash = auth_service.token_hash(raw_token or "")
    result = await session.execute(
        select(AdminPasswordReset).where(AdminPasswordReset.token_hash == token_hash)
    )
    reset = result.scalar_one_or_none()
    if reset is None or reset.used_at is not None:
        raise ValueError("Ссылка недействительна — запросите новую")
    if reset.expires_at < datetime.utcnow():
        raise ValueError("Срок действия ссылки истёк — запросите новую")

    user = await session.get(User, reset.user_id)
    if user is None:
        raise ValueError("Аккаунт не найден")

    user.password_hash = auth_service.hash_password(new_password)
    if promote_admin:
        user.is_admin = True
    reset.used_at = datetime.utcnow()
    # Прежние сессии — вон: ссылка восстановления могла попасть к посторонним
    await session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    await session.commit()
    return user


async def discard_reset_token(session: AsyncSession, raw_token: str) -> None:
    """Удаляет токен восстановления (например, если письмо не удалось отправить)."""
    await session.execute(
        delete(AdminPasswordReset).where(
            AdminPasswordReset.token_hash == auth_service.token_hash(raw_token or "")
        )
    )
    await session.commit()


def new_password(length: int = 16) -> str:
    """Случайный пароль без неоднозначных символов (для CLI)."""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%^*"
    import secrets as secrets_module

    return "".join(secrets_module.choice(alphabet) for _ in range(length))


def user_reset_link(base_url: str, token: str) -> str:
    """Ссылка смены пароля для посетителя (публичная страница /reset-password)."""
    return f"{base_url.rstrip('/')}/reset-password?token={token}"


def user_reset_email_text(link: str, ttl_minutes: int) -> str:
    """Текст письма со ссылкой смены пароля для аккаунта посетителя."""
    return (
        "Здравствуйте!\n\n"
        "Для вашего аккаунта на DREDGE запрошена смена пароля.\n"
        f"Ссылка действует {ttl_minutes} мин и срабатывает один раз:\n\n"
        f"{link}\n\n"
        "Если это не вы — просто проигнорируйте письмо.\n"
    )


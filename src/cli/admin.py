# src/cli/admin.py
"""Управление доступом в админку (запускать внутри контейнера api).

Это резервный путь восстановления: он работает даже если почта (SMTP) не
настроена или недоступна — достаточно SSH-доступа к серверу.

Примеры:
  docker compose -f docker-compose.prod.yml exec -T api python -m src.cli.admin list
  docker compose -f docker-compose.prod.yml exec -T api python -m src.cli.admin ensure
  docker compose -f docker-compose.prod.yml exec -T api \
      python -m src.cli.admin set-password --email admin@example.com
  docker compose -f docker-compose.prod.yml exec -T api \
      python -m src.cli.admin set-password --email admin@example.com --password 'СвойПароль'
"""
import argparse
import asyncio

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session_factory
from src.core.models import User
from src.services import admin_auth


async def cmd_list(_args: argparse.Namespace) -> int:
    """Показывает админов в БД и разрешённые адреса из ADMIN_EMAILS."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.is_admin.is_(True)).order_by(User.email)
        )
        admins = list(result.scalars().all())

    print("Админы в БД:")
    if admins:
        for user in admins:
            print(f"  • {user.email} (id={user.id})")
    else:
        print("  — нет")

    allowed = settings.admin_emails
    print(f"Разрешённые адреса (ADMIN_EMAILS): {', '.join(allowed) if allowed else '— не заданы'}")
    missing = [email for email in allowed if all(u.email != email for u in admins)]
    if missing:
        print(f"Не заведены в БД: {', '.join(missing)} → запустите `ensure`")
    return 0


async def cmd_ensure(_args: argparse.Namespace) -> int:
    """Заводит админ-аккаунты для всех адресов из ADMIN_EMAILS."""
    allowed = settings.admin_emails
    if not allowed:
        print("ADMIN_EMAILS пуст — сначала задайте адреса в .env")
        return 1
    async with async_session_factory() as session:
        for email in allowed:
            user = await admin_auth.ensure_admin(session, email)
            print(f"  ✓ {user.email} (id={user.id})")
    print(
        "Пароли не задавались: установите командой set-password "
        "(или запросите ссылку восстановления на сайте)."
    )
    return 0


async def cmd_set_password(args: argparse.Namespace) -> int:
    """Устанавливает (или сбрасывает) пароль админ-аккаунта."""
    email = (args.email or "").strip().lower()
    if not email:
        print("Укажите --email")
        return 1
    if not admin_auth.is_admin_email(email) and not args.force:
        print(f"{email} нет в ADMIN_EMAILS — добавьте адрес в .env или укажите --force")
        return 1

    password = args.password or admin_auth.new_password()
    async with async_session_factory() as session:
        user = await admin_auth.ensure_admin(session, email, password=password)

    print(f"Пароль установлен для {user.email}")
    if not args.password:
        print(f"Новый пароль: {password}")
        print("Сохраните его в менеджере паролей — больше он не показывается.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli.admin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="показать админов и разрешённые адреса")
    sub.add_parser("ensure", help="завести аккаунты для всех ADMIN_EMAILS")

    set_password = sub.add_parser("set-password", help="установить/сбросить пароль админа")
    set_password.add_argument("--email", required=True, help="адрес админ-аккаунта")
    set_password.add_argument("--password", help="пароль (если не указан — сгенерируется)")
    set_password.add_argument(
        "--force", action="store_true", help="разрешить адрес не из ADMIN_EMAILS"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handlers = {
        "list": cmd_list,
        "ensure": cmd_ensure,
        "set-password": cmd_set_password,
    }
    return asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    raise SystemExit(main())

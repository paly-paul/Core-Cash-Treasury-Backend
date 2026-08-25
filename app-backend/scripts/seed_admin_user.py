"""
Seed the database with an initial admin user.
Run once after migrations to create the first admin user.

Usage:
    python -m scripts.seed_admin_user <client_id>

Example:
    python -m scripts.seed_admin_user "00000000-0000-0000-0000-000000000000"
"""
import asyncio
import sys
import uuid
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.models.users import Users
from app.models.user_permission import UserPermission
from core_cash_shared.enums import Permission

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed_admin(client_id: str):
    """Create an initial admin user with all permissions."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Create admin user
        admin_password = "AdminPassword!2026"
        admin = Users(
            id=uuid.uuid4(),
            client_id=uuid.UUID(client_id),
            email="admin@candata.ai",
            password_hash=pwd_context.hash(admin_password),
            full_name="System Administrator",
            is_active=True,
            is_admin=True,
        )
        db.add(admin)
        await db.flush()

        # Grant all permissions
        for perm in Permission:
            db.add(UserPermission(
                client_id=uuid.UUID(client_id),
                user_id=admin.id,
                permission=perm.value,
                grant_type="grant",
                granted_by=admin.id,
                reason="System seed - initial admin setup",
            ))

        await db.commit()
        print(f"✓ Admin user created: {admin.email}")
        print(f"✓ Temporary password: {admin_password}")
        print(f"✓ All permissions granted: {len(list(Permission))} permissions")
        print(f"\n⚠️  Change the password immediately after first login!")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.seed_admin_user <client_id>")
        sys.exit(1)

    client_id = sys.argv[1]
    try:
        uuid.UUID(client_id)  # Validate UUID format
    except ValueError:
        print(f"Error: '{client_id}' is not a valid UUID")
        sys.exit(1)

    asyncio.run(seed_admin(client_id))

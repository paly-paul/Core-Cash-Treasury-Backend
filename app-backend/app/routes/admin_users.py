from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext

from app.database import get_db
from app.auth.dependencies import get_current_user, require_permission
from app.models.users import Users
from app.models.user_permission import UserPermission
from app.models.permission_template import PermissionTemplate
from core_cash_shared.schemas.auth import UserClaims
from core_cash_shared.enums import Permission
import structlog
import secrets

router = APIRouter(prefix="/api/admin/users", tags=["Admin Users"])
logger = structlog.get_logger()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    is_admin: bool = False


class CreateUserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    temporary_password: str
    is_admin: bool


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None


class GrantPermissionRequest(BaseModel):
    permission: str
    reason: str | None = None


class PermissionTemplateRequest(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]


@router.post("", status_code=201)
async def create_user(
    body: CreateUserRequest,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user. Auto-generates a temporary password."""
    # Check if email already exists for this client
    result = await db.execute(
        select(Users).where(
            Users.client_id == user.client_id,
            Users.email == body.email.lower()
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(409, detail={"code": "USER_EXISTS", "message": "Email already registered"})

    # Generate temporary password
    temp_password = secrets.token_urlsafe(16)
    password_hash = pwd_context.hash(temp_password)

    # Create user
    new_user = Users(
        client_id=user.client_id,
        email=body.email.lower(),
        password_hash=password_hash,
        full_name=body.full_name,
        is_admin=body.is_admin,
        created_by=user.sub,
    )
    db.add(new_user)
    await db.commit()

    logger.info("user_created", user_id=str(new_user.id), created_by=user.sub)

    return CreateUserResponse(
        id=str(new_user.id),
        email=new_user.email,
        full_name=new_user.full_name,
        temporary_password=temp_password,
        is_admin=new_user.is_admin,
    )


@router.get("")
async def list_users(
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """List all users for this client."""
    result = await db.execute(
        select(Users).where(Users.client_id == user.client_id)
    )
    users_list = result.scalars().all()

    return [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
            "last_login_at": u.last_login_at,
            "created_at": u.created_at,
        }
        for u in users_list
    ]


@router.get("/{user_id}")
async def get_user(
    user_id: str,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Get user details and their effective permissions."""
    result = await db.execute(
        select(Users).where(
            Users.client_id == user.client_id,
            Users.id == UUID(user_id)
        )
    )
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "User not found"})

    # Load permissions
    perm_result = await db.execute(
        select(UserPermission).where(
            UserPermission.client_id == user.client_id,
            UserPermission.user_id == UUID(user_id)
        )
    )
    permissions = perm_result.scalars().all()

    return {
        "id": str(target_user.id),
        "email": target_user.email,
        "full_name": target_user.full_name,
        "is_admin": target_user.is_admin,
        "is_active": target_user.is_active,
        "permissions": [
            {
                "permission": p.permission,
                "grant_type": p.grant_type,
                "granted_by": str(p.granted_by) if p.granted_by else None,
                "reason": p.reason,
                "expires_at": p.expires_at,
            }
            for p in permissions
        ],
    }


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Update user details."""
    result = await db.execute(
        select(Users).where(
            Users.client_id == user.client_id,
            Users.id == UUID(user_id)
        )
    )
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "User not found"})

    if body.full_name is not None:
        target_user.full_name = body.full_name
    if body.is_active is not None:
        target_user.is_active = body.is_active

    await db.commit()
    logger.info("user_updated", user_id=user_id, updated_by=user.sub)

    return {"message": "User updated"}


@router.post("/{user_id}/force-logout")
async def force_logout(
    user_id: str,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all refresh tokens for a user."""
    from app.services.permission_service import invalidate_permission_cache
    from app.models.refresh_token import RefreshToken
    from datetime import datetime

    # Revoke all active refresh tokens
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == UUID(user_id),
            RefreshToken.revoked_at == None
        )
    )
    tokens = result.scalars().all()
    for token in tokens:
        token.revoked_at = datetime.utcnow()

    # Invalidate permission cache
    invalidate_permission_cache(str(user.client_id), user_id)

    await db.commit()
    logger.info("force_logout", user_id=user_id, forced_by=user.sub)

    return {"message": "All sessions revoked"}


@router.post("/{user_id}/permissions")
async def grant_permission(
    user_id: str,
    body: GrantPermissionRequest,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Grant a permission to a user."""
    from app.services.permission_service import invalidate_permission_cache

    # Check user exists
    result = await db.execute(
        select(Users).where(
            Users.client_id == user.client_id,
            Users.id == UUID(user_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "User not found"})

    # Upsert permission grant
    perm_result = await db.execute(
        select(UserPermission).where(
            UserPermission.client_id == user.client_id,
            UserPermission.user_id == UUID(user_id),
            UserPermission.permission == body.permission
        )
    )
    perm = perm_result.scalar_one_or_none()

    if perm:
        perm.grant_type = "grant"
        perm.reason = body.reason
    else:
        perm = UserPermission(
            client_id=user.client_id,
            user_id=UUID(user_id),
            permission=body.permission,
            grant_type="grant",
            granted_by=UUID(user.sub),
            reason=body.reason,
        )
        db.add(perm)

    await db.commit()
    invalidate_permission_cache(str(user.client_id), user_id)
    logger.info("permission_granted", user_id=user_id, permission=body.permission, granted_by=user.sub)

    return {"message": f"Permission {body.permission} granted"}


@router.delete("/{user_id}/permissions/{permission}")
async def revoke_permission(
    user_id: str,
    permission: str,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a permission from a user."""
    from app.services.permission_service import invalidate_permission_cache

    # Check user exists
    result = await db.execute(
        select(Users).where(
            Users.client_id == user.client_id,
            Users.id == UUID(user_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "User not found"})

    # Upsert permission revoke
    perm_result = await db.execute(
        select(UserPermission).where(
            UserPermission.client_id == user.client_id,
            UserPermission.user_id == UUID(user_id),
            UserPermission.permission == permission
        )
    )
    perm = perm_result.scalar_one_or_none()

    if perm:
        perm.grant_type = "revoke"
    else:
        perm = UserPermission(
            client_id=user.client_id,
            user_id=UUID(user_id),
            permission=permission,
            grant_type="revoke",
            granted_by=UUID(user.sub),
        )
        db.add(perm)

    await db.commit()
    invalidate_permission_cache(str(user.client_id), user_id)
    logger.info("permission_revoked", user_id=user_id, permission=permission, revoked_by=user.sub)

    return {"message": f"Permission {permission} revoked"}


@router.post("/templates")
async def create_permission_template(
    body: PermissionTemplateRequest,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Create a named permission template."""
    template = PermissionTemplate(
        client_id=user.client_id,
        name=body.name,
        description=body.description,
        permissions=body.permissions,
        created_by=UUID(user.sub),
    )
    db.add(template)
    await db.commit()

    logger.info("template_created", template_id=str(template.id), created_by=user.sub)

    return {"id": str(template.id), "name": template.name}


@router.get("/templates")
async def list_permission_templates(
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """List all permission templates for this client."""
    result = await db.execute(
        select(PermissionTemplate).where(
            PermissionTemplate.client_id == user.client_id
        )
    )
    templates = result.scalars().all()

    return [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description,
            "permissions": t.permissions,
        }
        for t in templates
    ]


@router.post("/{user_id}/apply-template/{template_id}")
async def apply_template(
    user_id: str,
    template_id: str,
    user: UserClaims = Depends(require_permission(Permission.ADMIN_USER_PERMISSIONS)),
    db: AsyncSession = Depends(get_db),
):
    """Apply a permission template to a user."""
    from app.services.permission_service import invalidate_permission_cache

    # Load template
    result = await db.execute(
        select(PermissionTemplate).where(
            PermissionTemplate.client_id == user.client_id,
            PermissionTemplate.id == UUID(template_id)
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Template not found"})

    # Check user exists
    result = await db.execute(
        select(Users).where(
            Users.client_id == user.client_id,
            Users.id == UUID(user_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "User not found"})

    # Grant all permissions in template
    for perm in template.permissions:
        perm_result = await db.execute(
            select(UserPermission).where(
                UserPermission.client_id == user.client_id,
                UserPermission.user_id == UUID(user_id),
                UserPermission.permission == perm
            )
        )
        existing = perm_result.scalar_one_or_none()

        if existing:
            existing.grant_type = "grant"
        else:
            db.add(UserPermission(
                client_id=user.client_id,
                user_id=UUID(user_id),
                permission=perm,
                grant_type="grant",
                granted_by=UUID(user.sub),
                reason=f"Applied template: {template.name}",
            ))

    await db.commit()
    invalidate_permission_cache(str(user.client_id), user_id)
    logger.info("template_applied", user_id=user_id, template_id=template_id, applied_by=user.sub)

    return {"message": f"Template {template.name} applied"}

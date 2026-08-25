# Core Cash — Custom Auth Implementation Handoff
## Session 3: Full Auth Rebuild (RS256 JWT + Explicit Permissions)

**Branch:** `feature/custom-auth-permissions`  
**Commit:** `1c0e214`

---

## ✅ Completed Implementation

### 1. Core Authentication Layer
- **JWT Service** (`app-backend/app/services/jwt_service.py`)
  - RS256 token generation using private key (kept only in app-backend)
  - Access tokens (60 min): embed permissions for zero-DB-hit routing
  - Refresh tokens (30 day): cryptographically random, stored hashed for revocation
  - Token validation uses public key (shared with AI Backend)

- **Auth Service** (`app-backend/app/services/auth_service.py`)
  - Login: bcrypt password verification, uniform error messages
  - Logout: refresh token revocation
  - Refresh: token rotation + re-fetch permissions from DB (picks up admin changes)
  - Timing-attack resistant (dummy bcrypt check on invalid email)

### 2. Database Models
- **users** table: replaced Cognito fields with password auth
  - `password_hash` (bcrypt), `full_name`, `is_active`, `is_admin`, `mfa_*` fields
  - Timestamps: `created_at`, `updated_at`, `password_changed_at`, `last_login_at`
  - Audit: `created_by` (UUID of admin)
  - Unique constraint: (client_id, email)

- **refresh_tokens**: server-side storage for revocation support
  - Stores SHA-256 hash (never raw token)
  - Tracks: device_hint, ip_address, issued_at, expires_at, revoked_at
  - Supports: force-logout, device management, replay prevention via rotation

- **user_permissions**: explicit grant/revoke per user
  - No role defaults (all permissions explicit)
  - Fields: `grant_type` (grant|revoke), `reason`, `expires_at`, `granted_by`
  - Revokes take precedence over grants in permission resolution

- **permission_templates**: named permission bundles
  - Convenience only; pre-populate at user creation
  - Does NOT lock user to template (permissions can be changed after)
  - Changing template does NOT retroactively affect existing users

- **password_reset_tokens**: one-time password reset
  - Stored hashed, single-use, 1-hour expiry (configurable)
  - Links email flow to password change

### 3. Permission Model
- **Enum** (`shared/core_cash_shared/enums.py`)
  - 26 permissions defined (admin, view, edit, approve)
  - No role enum (removed entirely)

- **UserClaims** (`shared/core_cash_shared/schemas/auth.py`)
  - Replaces old role-based model
  - Fields: `sub`, `email`, `client_id`, `permissions: set[Permission]`
  - Methods: `has_permission()`, `has_any()`, `has_all()`

- **Permission Service** (`app-backend/app/services/permission_service.py`)
  - Loads grants/revokes from DB
  - 5-min memory cache per user (invalidated on admin changes)
  - Zero role defaults (only explicit grants applied)

### 4. API Routes

#### Auth Routes (`app-backend/app/routes/auth.py`)
- `POST /auth/login` → Returns JWT in HTTP-only cookies + user object
- `POST /auth/logout` → Revokes refresh token
- `POST /auth/refresh` → Issues new access + rotated refresh token
- `GET /auth/me` → Returns user + permissions list

#### Admin Routes (`app-backend/app/routes/admin_users.py`) — all require `ADMIN_USER_PERMISSIONS`
- `POST /api/admin/users` → Create user; auto-generate temporary password
- `GET /api/admin/users` → List users for client
- `GET /api/admin/users/{id}` → Get user + permissions + overrides
- `PUT /api/admin/users/{id}` → Update name/active status
- `POST /api/admin/users/{id}/force-logout` → Revoke all sessions
- `POST /api/admin/users/{id}/permissions` → Grant permission
- `DELETE /api/admin/users/{id}/permissions/{perm}` → Revoke permission
- `POST /api/admin/templates` → Create permission template
- `GET /api/admin/templates` → List templates
- `POST /api/admin/users/{id}/apply-template/{id}` → Apply template to user

### 5. Dependency Injection
- **App Backend** (`app-backend/app/auth/dependencies.py`)
  - `get_current_user()`: Validates RS256 JWT from cookie or Authorization header
  - `require_permission(*perms)`: Decorator for permission gating
  - Returns `UserClaims` (no DB hit on every request)

- **AI Backend** (`ai-backend/app/auth/dependencies.py`)
  - Uses public key to verify tokens (no private key needed)
  - Extracts permissions from JWT payload
  - Returns dict with user_id, email, client_id, permissions

### 6. Configuration
- **App Backend** (`app-backend/app/config.py`)
  - `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `JWT_ALGORITHM` (RS256)
  - `ACCESS_TOKEN_EXPIRE_MINUTES` (60), `REFRESH_TOKEN_EXPIRE_DAYS` (30)

- **AI Backend** (`ai-backend/app/config.py`)
  - `JWT_PUBLIC_KEY`, `JWT_ALGORITHM` only (no private key)

- **.env Files** (both services)
  - Keys stored with `\n` escape sequences for multi-line PEM format
  - Already in `.gitignore` (auth_private.pem, auth_public.pem)
  - Generated via: `openssl genrsa -out auth_private.pem 2048`

### 7. Database Migration
- **008_custom_auth_no_cognito.py**
  - Adds new columns to users (password_hash, mfa_*, timestamps, etc.)
  - Drops old columns (cognito_sub, role)
  - Creates 4 new tables (refresh_tokens, password_reset_tokens, user_permissions, permission_templates)
  - Includes down() for rollback

### 8. Development Tooling
- **Seed Script** (`app-backend/scripts/seed_admin_user.py`)
  - Creates initial admin user with all permissions
  - Usage: `python -m scripts.seed_admin_user "<client_uuid>"`
  - Generates temporary password printed to console

---

## ⚠️ Manual Setup Required (Before Running)

### 1. RSA Keys (Already Generated)
Keys are in repo root (`auth_private.pem`, `auth_public.pem`) and in `.gitignore`.
They were generated in the previous session but are NOT committed.

### 2. Environment Variables
Both .env files need the JWT keys. The keys are in repo root but .env files are not committed.

**For Local Development:**
```bash
# app-backend/.env and ai-backend/.env need:
JWT_PRIVATE_KEY="<contents-of-auth_private.pem-with-\n-escapes>"
JWT_PUBLIC_KEY="<contents-of-auth_public.pem-with-\n-escapes>"
```

The setup session already populated these. Verify they exist before running.

### 3. Database Migration
```bash
cd app-backend
alembic upgrade head
```

### 4. Seed Admin User
```bash
cd app-backend
python -m scripts.seed_admin_user "<client_id>"
# Example:
python -m scripts.seed_admin_user "00000000-0000-0000-0000-000000000000"
```

---

## 🔄 Design Decisions Recorded

| Decision | Choice | Rationale |
|----------|--------|-----------|
| JWT Algorithm | RS256 | Private key (app-backend only) + public key (both backends + caches) |
| Permissions in JWT | Yes (embedded) | Zero-DB-hit on /api/* requests; trade-off: 60-min max propagation |
| Refresh behavior | Re-read permissions | Token rotation picks up admin permission changes |
| Refresh token storage | Hashed in DB | Enables revocation, force-logout, multi-device tracking |
| Refresh token rotation | Yes | Old token revoked on each use → mitigates stolen token replay |
| Role concept | Removed | No default permission sets; all permissions explicit + auditable |
| Permission templates | Not enforced | Templates are convenience (pre-populate only); changing template does NOT affect existing users |
| Cache TTL | 5 minutes | Balance: DB load vs permission propagation latency |
| Password hashing | bcrypt | Industry standard with strong collision resistance |

---

## 📋 What's Not Yet Implemented

The following items are described in the original plan but NOT yet implemented:

1. **Password Reset Flow** (Step 11 in original plan)
   - `/auth/forgot-password` endpoint (sends email with token)
   - `/auth/reset-password` endpoint (consume token + set new password)
   - `PasswordResetToken` model is ready; routes not yet added

2. **MFA (Phase 2)**
   - `mfa_enabled` and `mfa_secret` columns exist in `users` table
   - TOTP validation logic not implemented

3. **Audit Logging Integration**
   - Calls to audit service in auth_service.py are stubbed (`pass`)
   - Should log: login_failed, user_created, permission_granted, force_logout, etc.

4. **Rate Limiting**
   - No rate limiting on login endpoint
   - Consider adding after initial testing

5. **AWS Secrets Manager Integration**
   - Plan says store `JWT_PRIVATE_KEY` in Secrets Manager for production
   - Currently loaded from `.env` (OK for dev/test)

6. **Email Service**
   - Password reset emails not wired
   - User creation notifications not wired
   - Scaffolding in place; SES or SendGrid integration needed

---

## 🧪 Testing Checklist

### Unit Tests (Not Yet Written)
- [ ] JWT token creation/validation
- [ ] Bcrypt password hashing and verification
- [ ] Permission resolution (grant/revoke logic)
- [ ] Refresh token rotation
- [ ] Template application

### Integration Tests (Not Yet Written)
- [ ] Login with valid credentials → get cookies
- [ ] Login with invalid email → uniform error
- [ ] Login with invalid password → uniform error
- [ ] Access token in Authorization header → works
- [ ] Access token in cookie → works
- [ ] Expired token → 401
- [ ] Refresh token rotation → old token revoked
- [ ] Permission gate on /api/admin/* → 403 without ADMIN_USER_PERMISSIONS
- [ ] Admin: create user, grant permission, list users

### Manual Smoke Tests (Before Merge)
```bash
# 1. Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@candata.ai","password":"AdminPassword!2026","client_id":"<id>"}'
# → Should return user + set cookies

# 2. Get current user (with cookie)
curl http://localhost:8000/auth/me \
  -b "access_token=<token>"
# → Should return user + permissions

# 3. Access protected route without token
curl http://localhost:8000/api/admin/users
# → Should return 401

# 4. Access protected route with insufficient permissions
curl http://localhost:8000/api/admin/users \
  -b "access_token=<user_token_without_admin_perm>"
# → Should return 403

# 5. Refresh token
curl -X POST http://localhost:8000/auth/refresh \
  -b "refresh_token=<token>"
# → Should return new access_token

# 6. Logout
curl -X POST http://localhost:8000/auth/logout \
  -b "refresh_token=<token>"
# → Should revoke token
```

---

## 📦 Files Created

**Models:**
- `app-backend/app/models/refresh_token.py`
- `app-backend/app/models/permission_template.py`
- `app-backend/app/models/password_reset_token.py`
- `app-backend/app/models/user_permission.py`

**Services:**
- `app-backend/app/services/jwt_service.py`
- `app-backend/app/services/auth_service.py`
- `app-backend/app/services/permission_service.py`

**Routes:**
- `app-backend/app/routes/auth.py`
- `app-backend/app/routes/admin_users.py`

**Shared:**
- `shared/core_cash_shared/schemas/auth.py`

**Database:**
- `app-backend/alembic/versions/008_custom_auth_no_cognito.py`

**Development:**
- `app-backend/scripts/seed_admin_user.py`

---

## 📝 Files Modified

**Core Configuration:**
- `app-backend/app/config.py` — replaced Cognito vars with JWT vars
- `app-backend/app/auth/dependencies.py` — replaced Cognito decode with RS256 decode
- `app-backend/app/auth/models.py` — (no changes; UserModel not used anymore)
- `app-backend/app/models/users.py` — replaced cognito_sub/role with password + auth fields
- `app-backend/app/main.py` — added auth + admin_users routers

**AI Backend:**
- `ai-backend/app/config.py` — replaced Cognito vars with JWT_PUBLIC_KEY only
- `ai-backend/app/auth/jwt.py` — replaced Cognito validate with RS256 public key validate
- `ai-backend/app/auth/dependencies.py` — replaced Cognito decode with RS256 decode

**Shared Library:**
- `shared/core_cash_shared/enums.py` — added Permission enum
- `shared/core_cash_shared/__init__.py` — export Permission

**Dependencies:**
- `app-backend/pyproject.toml` — added passlib[bcrypt], python-multipart
- `app-backend/.env.example` — replaced COGNITO_* with JWT_*
- `ai-backend/.env.example` — replaced COGNITO_* with JWT_*

**Dev Keys (Not Committed):**
- `auth_private.pem` (in .gitignore)
- `auth_public.pem` (in .gitignore)

---

## 🚀 Next Steps for Future Sessions

1. **Complete Password Reset Flow**
   - Add `/auth/forgot-password` endpoint
   - Add `/auth/reset-password` endpoint
   - Wire email service for password reset links

2. **Add Audit Logging**
   - Implement audit_service calls in auth_service.py
   - Log all permission changes, logins, logouts, etc.

3. **Write Integration Tests**
   - Test all auth flows (login, logout, refresh, permission gating)
   - Test admin endpoints (user creation, permission grants)

4. **Deploy Configuration**
   - Document how to store JWT_PRIVATE_KEY in AWS Secrets Manager
   - Add health check to verify JWT keys are loadable
   - Document key rotation procedure

5. **MFA Implementation** (Phase 2)
   - Implement TOTP validation in login
   - Add MFA setup/disable endpoints

6. **Session Management**
   - Add `/auth/sessions` endpoint to list active devices
   - Add endpoint to revoke sessions by device

---

## ⚡ How It All Fits Together

### Login Flow
```
1. User submits email + password
   → AuthService.login()
   → bcrypt.verify() password against users.password_hash
   → Load permissions from user_permissions table + cache
   → Create access token (RS256, embed permissions, 60 min)
   → Create refresh token (random, store hash in DB, 30 days)
   → Return tokens + user info in HTTP-only cookies
```

### Request Flow (Protected Route)
```
1. Request arrives at protected route
   → get_current_user() dependency
   → Extract token from cookie/Authorization header
   → jwt.decode() using public key (RS256)
   → Validate type=="access", not expired
   → Parse permissions from JWT payload
   → Return UserClaims (NO DB HIT)
   → require_permission() decorator checks permissions
   → Route handler executes
```

### Token Refresh Flow
```
1. Access token expires
   → Client calls POST /auth/refresh with refresh_token cookie
   → AuthService.refresh()
   → Validate refresh token hash in DB (check revoked_at, expires_at)
   → Load user (verify is_active)
   → RE-READ permissions from DB (picks up admin changes)
   → Revoke old refresh token
   → Issue new access + rotated refresh tokens
   → Return new tokens in cookies
```

### Permission Model
```
No Roles → Explicit Permissions

user_permissions rows:
  { user_id: X, permission: "view_cash_position", grant_type: "grant" }
  { user_id: X, permission: "edit_assumptions", grant_type: "grant" }
  { user_id: X, permission: "admin_user_permissions", grant_type: "revoke" } # Override

Resolution:
  1. Load all rows for user from DB
  2. Collect "revoke" permissions
  3. Add "grant" permissions minus "revoke" set
  4. Cache for 5 min
  5. Embed in JWT on login/refresh
```

---

## 📞 Questions or Issues?

This implementation follows the plan from Step 1–Step 12. Steps 13–14 (remove Cognito references, seed data) are partially done.

If running migrations or tests fails, verify:
1. RSA keys are in .env files (check both files have JWT_PRIVATE_KEY + JWT_PUBLIC_KEY)
2. Alembic migration runs without errors
3. Admin user is seeded before testing /api/admin/* routes

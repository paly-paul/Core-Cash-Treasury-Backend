from enum import Enum


class AccountStatus(str, Enum):
    GREEN = "Green"
    YELLOW = "Yellow"
    RED = "Red"


class JobType(str, Enum):
    CASH_POSITION = "cash_position"
    LIQUIDITY_RISK = "liquidity_risk"
    ACTION_RECOMMENDATION = "action_recommendation"
    VARIANCE_EXPLANATION = "variance_explanation"
    CFO_SUMMARY = "cfo_summary"
    TREASURY_CONTINUITY = "treasury_continuity"
    DAILY_BRIEFING = "daily_briefing"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class RefreshFrequency(str, Enum):
    DAILY = "Daily"
    WEEKLY = "Weekly"
    MONTHLY = "Monthly"
    MANUAL = "Manual"


class DataConfidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class RiskLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class Permission(str, Enum):
    """User permissions in the system."""
    # Admin permissions
    ADMIN_USER_PERMISSIONS = "admin_user_permissions"

    # View permissions
    VIEW_CASH_POSITION = "view_cash_position"
    VIEW_FORECAST = "view_forecast"
    VIEW_RECOMMENDATIONS = "view_recommendations"
    VIEW_VARIANCE = "view_variance"
    VIEW_CFO_SUMMARY = "view_cfo_summary"
    VIEW_LIQUIDITY_RISK = "view_liquidity_risk"
    VIEW_AUDIT_LOG = "view_audit_log"
    VIEW_FILE_IMPORTS = "view_file_imports"

    # Edit permissions
    EDIT_RECOMMENDATIONS = "edit_recommendations"
    EDIT_ASSUMPTIONS = "edit_assumptions"
    EDIT_INVESTMENTS = "edit_investments"
    EDIT_SYSTEM_CONFIG = "edit_system_config"

    # Approval permissions
    APPROVE_RECOMMENDATIONS = "approve_recommendations"
    APPROVE_ASSUMPTIONS = "approve_assumptions"

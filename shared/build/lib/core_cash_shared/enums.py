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

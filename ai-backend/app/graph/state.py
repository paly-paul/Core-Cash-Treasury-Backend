from datetime import datetime
from typing import Any, Dict, Optional, TypedDict


class AgentState(TypedDict):
    job_id: str
    client_id: str
    user_id: str
    requested_at: datetime
    # Agent outputs — None until that agent runs
    cash_position: Optional[Dict[str, Any]]
    liquidity_risk: Optional[Dict[str, Any]]
    forecast: Optional[Dict[str, Any]]
    action_recommendations: Optional[Dict[str, Any]]
    variance_explanation: Optional[Dict[str, Any]]
    treasury_continuity: Optional[Dict[str, Any]]
    cfo_summary: Optional[Dict[str, Any]]
    # Per-agent errors — pipeline continues unless hard dependency fails
    errors: Dict[str, str]

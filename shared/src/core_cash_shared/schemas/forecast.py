from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date as DateType


class ForecastDayRow(BaseModel):
    """Single day in forecast output."""
    forecast_date: DateType
    opening_balance_usd: Optional[float] = None  # None when blocked
    projected_inflows_usd: Optional[float] = None
    projected_outflows_usd: Optional[float] = None
    projected_closing_usd: Optional[float] = None  # None when blocked
    confidence_band_low_usd: Optional[float] = None
    confidence_band_high_usd: Optional[float] = None
    assumptions_applied: list[str] = []  # assumption IDs used


class ForecastResult(BaseModel):
    """Complete forecast run result."""
    forecast_run_id: str
    entity_id: str
    entity_name: str
    generated_at: str  # ISO datetime UTC
    horizon_days: int  # always 30 for MVP
    data_status: Literal["live", "partial", "blocked"]
    blocked_reason: Optional[str] = None  # set when data_status="blocked"
    opening_balance_usd: Optional[float] = None
    forecast_rows: list[ForecastDayRow] = []  # empty when blocked
    assumptions_used: int = 0
    assumptions_skipped: int = 0  # confidence_pct < 50
    forecast_accuracy_pct: Optional[float] = None  # None until variance runs
    notes: list[str] = []

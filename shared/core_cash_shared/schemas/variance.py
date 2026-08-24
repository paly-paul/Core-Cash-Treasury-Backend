from pydantic import BaseModel, Field
from typing import Optional
from datetime import date as DateType


class VarianceDriver(BaseModel):
    category: str
    actual_usd: float
    forecast_usd: float
    variance_usd: float
    one_off_flag: bool = False
    one_off_basis: Optional[str] = None


class VarianceExplanationResult(BaseModel):
    variance_id: str
    entity_id: str
    entity_name: str
    analysis_date: DateType
    actual_closing_usd: float
    forecast_closing_usd: float
    total_variance_usd: float
    variance_pct: float
    within_tolerance: bool
    forecast_accuracy_pct: float
    drivers: list[VarianceDriver]
    unexplained_variance_usd: float
    unexplained_variance_note: Optional[str] = None
    narrative: str
    data_status: str
    computed_at: str

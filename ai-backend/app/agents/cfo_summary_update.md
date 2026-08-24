# Agent 6 (CFO Summary) - Session 13 Update

## File: ai-backend/app/agents/cfo_summary.py

In Session 7, forecast_outlook was set to [].
Now that forecast_runs collection exists (Agent 2), populate it from forecast data:

```python
# Read latest forecast run for entity
forecast_doc = await mongo_db.forecast_runs.find_one(
    {"client_id": client_id, "entity_id": entity_id},
    sort=[("generated_at", -1)]
)

if forecast_doc and forecast_doc.get("data_status") != "blocked":
    rows = forecast_doc.get("forecast_rows", [])
    # 7-day outlook: first 7 rows
    forecast_outlook = [
        {
            "date": r["forecast_date"],
            "projected_closing_usd": r.get("projected_closing_usd"),
            "confidence_band_low_usd": r.get("confidence_band_low_usd"),
            "confidence_band_high_usd": r.get("confidence_band_high_usd"),
        }
        for r in rows[:7]
    ]
else:
    forecast_outlook = []   # blocked or no forecast yet
```

This unblocks the CFO Summary forecast_outlook section:
1. Session 7 had forecast_outlook = [] (stub)
2. Session 13 now queries forecast_runs collection
3. If latest forecast is not blocked, extracts first 7 days
4. If blocked or not found, returns empty array

The 7-day horizon is used for the CFO Summary report's forecast_outlook section.

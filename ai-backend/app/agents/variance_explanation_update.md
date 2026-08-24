# Agent 5 (Variance Explanation) - Session 13 Update

## File: ai-backend/app/agents/variance_explanation.py

After computing forecast_accuracy_pct in the variance explanation agent, add this code to write it back to the forecast_runs document:

```python
# After computing forecast_accuracy_pct:
if forecast_doc_id:  # the _id of the forecast_runs document used
    await mongo_db.forecast_runs.update_one(
        {"_id": forecast_doc_id},
        {"$set": {"forecast_accuracy_pct": forecast_accuracy_pct}}
    )
```

This closes the feedback loop:
1. Agent 2 writes forecast_runs document with forecast_accuracy_pct = None
2. Agent 5 runs variance calculation and computes forecast_accuracy_pct
3. Agent 5 updates the original forecast_runs document with the accuracy value
4. Later queries on forecast_runs will see the updated accuracy_pct

This allows Agent 6 (CFO Summary) to read the complete forecast data including accuracy.

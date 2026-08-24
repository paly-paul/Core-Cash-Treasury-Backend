"""
Job type registry for AI Backend.

Maps job_type string to handler function.
"""

from .forecast_job import run_forecast_job

JOB_REGISTRY = {
    "forecast": run_forecast_job,
    # Other job types registered here as they're added
    # "variance_explanation": run_variance_job,
    # "cfo_summary": run_cfo_summary_job,
}

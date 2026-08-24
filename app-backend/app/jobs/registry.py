from typing import Callable, Dict

# Maps job_type string → handler function
# Populated by each agent session
JOB_HANDLERS: Dict[str, Callable] = {}

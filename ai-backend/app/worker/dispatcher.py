from typing import Callable, Dict

from core_cash_shared.enums import JobType

# Maps JobType → agent runner function
# Populated by each agent session
AGENT_RUNNERS: Dict[JobType, Callable] = {}

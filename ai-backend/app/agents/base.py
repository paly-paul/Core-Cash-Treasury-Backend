from abc import ABC, abstractmethod

from app.graph.state import AgentState


class BaseAgent(ABC):
    def __init__(self, db, mongo_db):
        self.db = db
        self.mongo_db = mongo_db

    @abstractmethod
    async def run(self, state: AgentState) -> AgentState:
        """Run the agent with the given state."""
        ...

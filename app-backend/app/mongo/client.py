from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings


class MongoClient:
    def __init__(self):
        self.client: AsyncIOMotorClient = None
        self.db: AsyncIOMotorDatabase = None

    async def connect(self):
        """Connect to MongoDB and create collections/indexes."""
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_db_name]

        # Create collections
        collections_to_create = [
            "agent_runs",
            "recommendations",
            "cfo_reports",
            "daily_briefings",
            "variance_reports",
            "job_status_mirror",
        ]

        existing_collections = await self.db.list_collection_names()

        for collection_name in collections_to_create:
            if collection_name not in existing_collections:
                await self.db.create_collection(collection_name)

        # Create indexes
        await self.db.agent_runs.create_index([("client_id", 1), ("job_id", 1)])
        await self.db.agent_runs.create_index([("client_id", 1), ("created_at", -1)])

        await self.db.recommendations.create_index(
            [("client_id", 1), ("approval_status", 1)]
        )
        await self.db.recommendations.create_index([("client_id", 1), ("created_at", -1)])

        await self.db.cfo_reports.create_index([("client_id", 1), ("created_at", -1)])
        await self.db.daily_briefings.create_index([("client_id", 1), ("created_at", -1)])
        await self.db.variance_reports.create_index(
            [("client_id", 1), ("created_at", -1)]
        )

    async def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()


mongo_client = MongoClient()


def get_mongo_db():
    """Get MongoDB database."""
    return mongo_client.db

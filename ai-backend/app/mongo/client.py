from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings


class MongoClient:
    def __init__(self):
        self.client: AsyncIOMotorClient = None
        self.db: AsyncIOMotorDatabase = None

    async def connect(self):
        """Connect to MongoDB."""
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_db_name]

    async def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()


mongo_client = MongoClient()


async def get_mongo_db():
    """Dependency to get MongoDB database."""
    return mongo_client.db

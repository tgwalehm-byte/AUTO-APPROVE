from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL


# MongoDB connection
mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=10000,
)

db = mongo_client["auto_join_request_bot"]


# Collections
users_collection = db["users"]
chats_collection = db["chats"]
groups_collection = db["groups"]
ads_collection = db["ads"]


class Database:

    # -------------------------
    # USERS
    # -------------------------

    async def save_user(self, user):
        if not user:
            return

        await users_collection.update_one(
            {"_id": user.id},
            {
                "$set": {
                    "user_id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                }
            },
            upsert=True,
        )

    async def user_exists(self, user_id: int):
        return await users_collection.find_one(
            {"_id": user_id}
        ) is not None

    async def get_user_ids(self):
        cursor = users_collection.find(
            {},
            {"_id": 1}
        )

        return [
            document["_id"]
            async for document in cursor
        ]

    async def count_users(self):
        return await users_collection.count_documents({})

    # -------------------------
    # GROUPS / CHANNELS
    # -------------------------

    async def save_chat(self, chat):
        if not chat:
            return

        chat_type = str(chat.type)

        await chats_collection.update_one(
            {"_id": chat.id},
            {
                "$set": {
                    "chat_id": chat.id,
                    "title": getattr(chat, "title", None),
                    "username": getattr(chat, "username", None),
                    "type": chat_type,
                }
            },
            upsert=True,
        )

    async def save_group(self, chat):
        if not chat:
            return

        await groups_collection.update_one(
            {"_id": chat.id},
            {
                "$set": {
                    "chat_id": chat.id,
                    "title": getattr(chat, "title", None),
                    "username": getattr(chat, "username", None),
                    "type": str(chat.type),
                },
                "$setOnInsert": {
                    # IMPORTANT:
                    # Group auto approval is OFF by default.
                    "approve_enabled": False,
                },
            },
            upsert=True,
        )

    async def get_group(self, chat_id: int):
        return await groups_collection.find_one(
            {"_id": chat_id}
        )

    async def set_group_approval(
        self,
        chat_id: int,
        enabled: bool
    ):
        await groups_collection.update_one(
            {"_id": chat_id},
            {
                "$set": {
                    "approve_enabled": enabled
                }
            },
            upsert=True,
        )

    async def is_group_approval_enabled(
        self,
        chat_id: int
    ):
        group = await self.get_group(chat_id)

        if not group:
            return False

        return group.get(
            "approve_enabled",
            False
        )

    async def get_group_ids(self):
        cursor = groups_collection.find(
            {},
            {"_id": 1}
        )

        return [
            document["_id"]
            async for document in cursor
        ]

    async def count_groups(self):
        return await groups_collection.count_documents({})

    async def count_chats(self):
        return await chats_collection.count_documents({})

    # -------------------------
    # ADVERTISEMENT
    # -------------------------

    async def set_ad(
        self,
        chat_id: int,
        message_id: int
    ):
        await ads_collection.update_one(
            {"_id": "main"},
            {
                "$set": {
                    "chat_id": chat_id,
                    "message_id": message_id,
                }
            },
            upsert=True,
        )

    async def get_ad(self):
        return await ads_collection.find_one(
            {"_id": "main"}
        )

    async def delete_ad(self):
        await ads_collection.delete_one(
            {"_id": "main"}
        )

    async def has_ad(self):
        return await ads_collection.find_one(
            {"_id": "main"}
        ) is not None


db = Database()
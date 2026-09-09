from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_URL


# ============================================================
# MONGODB
# ============================================================

mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=10000
)

db = mongo_client["auto_join_request_bot"]


# ============================================================
# COLLECTIONS
# ============================================================

users_collection = db["users"]
chats_collection = db["chats"]
groups_collection = db["groups"]
ads_collection = db["ads"]
pending_collection = db["pending_requests"]


# ============================================================
# DATABASE
# ============================================================

class Database:

    # ========================================================
    # USERS
    # ========================================================

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
                    "last_name": user.last_name
                }
            },
            upsert=True
        )

    async def get_user_ids(self):

        cursor = users_collection.find(
            {},
            {"_id": 1}
        )

        result = []

        async for document in cursor:
            result.append(document["_id"])

        return result

    async def count_users(self):

        return await users_collection.count_documents({})

    # ========================================================
    # CHATS
    # ========================================================

    async def save_chat(self, chat):

        if not chat:
            return

        chat_type = str(chat.type)

        await chats_collection.update_one(
            {"_id": chat.id},
            {
                "$set": {
                    "chat_id": chat.id,
                    "title": getattr(
                        chat,
                        "title",
                        None
                    ),
                    "username": getattr(
                        chat,
                        "username",
                        None
                    ),
                    "type": chat_type
                }
            },
            upsert=True
        )

        if chat.type in (
            "group",
            "supergroup"
        ):

            await self.save_group(chat)

    async def count_chats(self):

        return await chats_collection.count_documents({})

    # ========================================================
    # GROUPS
    # ========================================================

    async def save_group(self, chat):

        await groups_collection.update_one(
            {"_id": chat.id},
            {
                "$set": {
                    "chat_id": chat.id,
                    "title": getattr(
                        chat,
                        "title",
                        None
                    ),
                    "username": getattr(
                        chat,
                        "username",
                        None
                    ),
                    "type": str(chat.type)
                },
                "$setOnInsert": {
                    "approve_enabled": False
                }
            },
            upsert=True
        )

    async def get_group_ids(self):

        cursor = groups_collection.find(
            {},
            {"_id": 1}
        )

        result = []

        async for document in cursor:
            result.append(document["_id"])

        return result

    async def count_groups(self):

        return await groups_collection.count_documents({})

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
            upsert=True
        )

    async def is_group_approval_enabled(
        self,
        chat_id: int
    ):

        group = await groups_collection.find_one(
            {"_id": chat_id}
        )

        if not group:
            return False

        return bool(
            group.get(
                "approve_enabled",
                False
            )
        )

    # ========================================================
    # CHANNELS
    # ========================================================

    async def count_channels(self):

        return await chats_collection.count_documents(
            {
                "type": "ChatType.CHANNEL"
            }
        )

    # ========================================================
    # PENDING JOIN REQUESTS
    # ========================================================

    async def save_pending_request(
        self,
        chat_id: int,
        user
    ):

        await pending_collection.update_one(
            {
                "chat_id": chat_id,
                "user_id": user.id
            },
            {
                "$set": {
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name
                }
            },
            upsert=True
        )

    async def remove_pending_request(
        self,
        chat_id: int,
        user_id: int
    ):

        await pending_collection.delete_one(
            {
                "chat_id": chat_id,
                "user_id": user_id
            }
        )

    async def get_pending_requests(
        self,
        chat_id: int,
        limit: int = 10
    ):

        cursor = pending_collection.find(
            {
                "chat_id": chat_id
            }
        ).limit(limit)

        result = []

        async for document in cursor:
            result.append(document)

        return result

    async def count_pending(
        self,
        chat_id: int
    ):

        return await pending_collection.count_documents(
            {
                "chat_id": chat_id
            }
        )

    # ========================================================
    # ADVERTISEMENT
    # ========================================================

    async def set_ad(
        self,
        chat_id: int,
        message_id: int
    ):

        await ads_collection.update_one(
            {"_id": "main"},
            {
                "$set": {
                    "type": "message",
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": None
                }
            },
            upsert=True
        )

    async def set_ad_text(
        self,
        text: str
    ):

        await ads_collection.update_one(
            {"_id": "main"},
            {
                "$set": {
                    "type": "text",
                    "text": text,
                    "chat_id": None,
                    "message_id": None
                }
            },
            upsert=True
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

        return (
            await ads_collection.find_one(
                {"_id": "main"}
            )
            is not None
        )

    # ========================================================
    # MONGODB PING
    # ========================================================

    async def ping(self):

        try:

            await mongo_client.admin.command(
                "ping"
            )

            return True

        except Exception:

            return False


# ============================================================
# INSTANCE
# ============================================================

db = Database()
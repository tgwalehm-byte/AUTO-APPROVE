from motor.motor_asyncio import AsyncIOMotorClient

from config import MONGO_URL


# ============================================================
# MONGODB CONNECTION
# ============================================================

mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=10000,
)

db = mongo_client["auto_join_request_bot"]


# ============================================================
# COLLECTIONS
# ============================================================

users_collection = db["users"]
chats_collection = db["chats"]
groups_collection = db["groups"]
ads_collection = db["ads"]


# ============================================================
# DATABASE CLASS
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
                    "last_name": user.last_name,
                }
            },
            upsert=True,
        )

    async def user_exists(self, user_id: int):

        user = await users_collection.find_one(
            {"_id": user_id}
        )

        return user is not None

    async def get_user_ids(self):

        cursor = users_collection.find(
            {},
            {"_id": 1}
        )

        user_ids = []

        async for document in cursor:
            user_ids.append(
                document["_id"]
            )

        return user_ids

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
                    "type": chat_type,
                }
            },
            upsert=True,
        )

        # If group, also save in groups collection.
        if chat.type in (
            "group",
            "supergroup",
        ):

            await self.save_group(chat)

    async def count_chats(self):

        return await chats_collection.count_documents({})

    # ========================================================
    # GROUPS
    # ========================================================

    async def save_group(self, chat):

        if not chat:
            return

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
                    "type": str(chat.type),
                },

                # IMPORTANT:
                # New groups are OFF by default.
                "$setOnInsert": {
                    "approve_enabled": False
                }
            },
            upsert=True,
        )

    async def get_group(self, chat_id: int):

        return await groups_collection.find_one(
            {"_id": chat_id}
        )

    async def get_group_ids(self):

        cursor = groups_collection.find(
            {},
            {"_id": 1}
        )

        group_ids = []

        async for document in cursor:

            group_ids.append(
                document["_id"]
            )

        return group_ids

    async def count_groups(self):

        return await groups_collection.count_documents({})

    # ========================================================
    # GROUP APPROVAL SETTING
    # ========================================================

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
                    "text": None,
                }
            },
            upsert=True,
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
                    "message_id": None,
                }
            },
            upsert=True,
        )

    async def get_ad(self):

        return await ads_collection.find_one(
            {"_id": "main"}
        )

    async def has_ad(self):

        ad = await ads_collection.find_one(
            {"_id": "main"}
        )

        return ad is not None

    async def delete_ad(self):

        await ads_collection.delete_one(
            {"_id": "main"}
        )

    # ========================================================
    # DATABASE TEST
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
# DATABASE INSTANCE
# ============================================================

db = Database()
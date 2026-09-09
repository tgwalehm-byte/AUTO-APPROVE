from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL


# ============================================================
# MONGODB CONNECTION
# ============================================================

mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=10000
)

db = mongo_client["auto_join_request_bot"]


# ============================================================
# COLLECTIONS
# ============================================================

users = db["users"]
groups = db["groups"]
pending_requests = db["pending_requests"]
ads = db["ads"]


# ============================================================
# DATABASE CLASS
# ============================================================

class Database:

    # ========================================================
    # USER
    # ========================================================

    async def save_user(self, user_id, username=None,
                        first_name=None, last_name=None):

        await users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name
                }
            },
            upsert=True
        )

    async def get_all_users(self):

        cursor = users.find(
            {},
            {"_id": 1}
        )

        result = []

        async for doc in cursor:
            result.append(doc["_id"])

        return result

    async def total_users(self):

        return await users.count_documents({})

    # ========================================================
    # GROUP
    # ========================================================

    async def save_group(self, chat_id, title=None,
                         username=None):

        await groups.update_one(
            {"_id": chat_id},
            {
                "$set": {
                    "chat_id": chat_id,
                    "title": title,
                    "username": username
                },

                # VERY IMPORTANT:
                # New group = auto approval OFF
                "$setOnInsert": {
                    "approve_enabled": False
                }
            },
            upsert=True
        )

    async def get_group(self, chat_id):

        return await groups.find_one(
            {"_id": chat_id}
        )

    async def get_all_groups(self):

        cursor = groups.find(
            {},
            {"_id": 1}
        )

        result = []

        async for doc in cursor:
            result.append(doc["_id"])

        return result

    async def total_groups(self):

        return await groups.count_documents({})

    # ========================================================
    # GROUP APPROVAL SETTING
    # ========================================================

    async def set_approval(
        self,
        chat_id,
        enabled
    ):

        await groups.update_one(
            {"_id": chat_id},
            {
                "$set": {
                    "approve_enabled": enabled
                }
            },
            upsert=True
        )

    async def approval_enabled(
        self,
        chat_id
    ):

        group = await groups.find_one(
            {"_id": chat_id}
        )

        if not group:
            return False

        return group.get(
            "approve_enabled",
            False
        )

    # ========================================================
    # PENDING REQUEST
    # ========================================================

    async def save_pending(
        self,
        chat_id,
        user_id,
        user_chat_id
    ):

        await pending_requests.update_one(
            {
                "chat_id": chat_id,
                "user_id": user_id
            },
            {
                "$set": {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "user_chat_id": user_chat_id
                }
            },
            upsert=True
        )

    async def get_pending(
        self,
        chat_id,
        limit
    ):

        cursor = pending_requests.find(
            {
                "chat_id": chat_id
            }
        ).limit(limit)

        result = []

        async for doc in cursor:
            result.append(doc)

        return result

    async def remove_pending(
        self,
        chat_id,
        user_id
    ):

        await pending_requests.delete_one(
            {
                "chat_id": chat_id,
                "user_id": user_id
            }
        )

    async def remove_all_pending(
        self,
        chat_id
    ):

        await pending_requests.delete_many(
            {
                "chat_id": chat_id
            }
        )

    async def total_pending(
        self,
        chat_id
    ):

        return await pending_requests.count_documents(
            {
                "chat_id": chat_id
            }
        )

    # ========================================================
    # ADVERTISEMENT
    # ========================================================

    async def set_ad(self, data):

        await ads.update_one(
            {"_id": "main"},
            {
                "$set": data
            },
            upsert=True
        )

    async def get_ad(self):

        return await ads.find_one(
            {"_id": "main"}
        )

    async def delete_ad(self):

        await ads.delete_one(
            {"_id": "main"}
        )

    async def has_ad(self):

        return (
            await ads.find_one(
                {"_id": "main"}
            )
            is not None
        )

    # ========================================================
    # MONGODB TEST
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
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL
from datetime import datetime


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

users = db["users"]
groups = db["groups"]
pending_requests = db["pending_requests"]
ads = db["ads"]


# ============================================================
# DATABASE
# ============================================================

class Database:

    # ========================================================
    # SAVE USER
    # ========================================================

    async def save_user(
        self,
        user_id,
        username=None,
        first_name=None,
        last_name=None,
        user_chat_id=None,
        eligible=False
    ):

        data = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "updated_at": datetime.utcnow()
        }

        if user_chat_id:
            data["user_chat_id"] = user_chat_id

        # User ne /start ya verification kiya
        if eligible:
            data["eligible"] = True
            data["eligible_at"] = datetime.utcnow()

        await users.update_one(
            {
                "_id": user_id
            },
            {
                "$set": data,

                "$setOnInsert": {
                    "eligible": False,
                    "verified": False,
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # MARK USER ELIGIBLE
    # ========================================================

    async def mark_user_eligible(self, user_id):

        await users.update_one(
            {
                "_id": user_id
            },
            {
                "$set": {
                    "eligible": True,
                    "eligible_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # VERIFY USER
    # ========================================================

    async def verify_user(self, user_id):

        await users.update_one(
            {
                "_id": user_id
            },
            {
                "$set": {
                    "verified": True,
                    "eligible": True,
                    "verified_at": datetime.utcnow(),
                    "eligible_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # CHECK VERIFIED
    # ========================================================

    async def is_verified(self, user_id):

        user = await users.find_one(
            {
                "_id": user_id
            }
        )

        if not user:
            return False

        return user.get(
            "verified",
            False
        )

    # ========================================================
    # GET BROADCAST USERS
    # ========================================================

    async def get_broadcast_users(self):

        cursor = users.find(
            {
                "eligible": True
            },
            {
                "_id": 1
            }
        )

        result = []

        async for doc in cursor:

            result.append(
                doc["_id"]
            )

        return result

    # ========================================================
    # TOTAL BROADCAST USERS
    # ========================================================

    async def total_broadcast_users(self):

        return await users.count_documents(
            {
                "eligible": True
            }
        )

    # ========================================================
    # TOTAL VERIFIED
    # ========================================================

    async def total_verified_users(self):

        return await users.count_documents(
            {
                "verified": True
            }
        )

    # ========================================================
    # DELETE USER
    # ========================================================

    async def delete_user(self, user_id):

        await users.delete_one(
            {
                "_id": user_id
            }
        )

    # ========================================================
    # DELETE ALL USERS
    # ========================================================

    async def delete_all_users(self):

        result = await users.delete_many({})

        return result.deleted_count

    # ========================================================
    # GROUP
    # ========================================================

    async def save_group(
        self,
        chat_id,
        title=None,
        username=None,
        chat_type=None
    ):

        data = {
            "chat_id": chat_id,
            "title": title,
            "username": username,
            "updated_at": datetime.utcnow()
        }

        if chat_type:
            data["chat_type"] = chat_type

        await groups.update_one(
            {
                "_id": chat_id
            },
            {
                "$set": data,

                "$setOnInsert": {
                    "approve_enabled": False,
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # GET GROUP
    # ========================================================

    async def get_group(self, chat_id):

        return await groups.find_one(
            {
                "_id": chat_id
            }
        )

    # ========================================================
    # GET ALL GROUPS
    # ========================================================

    async def get_all_groups(self):

        cursor = groups.find(
            {},
            {
                "_id": 1
            }
        )

        result = []

        async for doc in cursor:
            result.append(
                doc["_id"]
            )

        return result

    # ========================================================
    # TOTAL GROUPS
    # ========================================================

    async def total_groups(self):

        return await groups.count_documents({})

    # ========================================================
    # DELETE GROUP
    # ========================================================

    async def delete_group(self, chat_id):

        await groups.delete_one(
            {
                "_id": chat_id
            }
        )

    # ========================================================
    # AUTO APPROVAL
    # ========================================================

    async def set_approval(
        self,
        chat_id,
        enabled
    ):

        await groups.update_one(
            {
                "_id": chat_id
            },
            {
                "$set": {
                    "approve_enabled": enabled,
                    "updated_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # CHECK AUTO APPROVAL
    # ========================================================

    async def approval_enabled(
        self,
        chat_id
    ):

        group = await groups.find_one(
            {
                "_id": chat_id
            }
        )

        if not group:
            return False

        return group.get(
            "approve_enabled",
            False
        )

    # ========================================================
    # PENDING
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
                    "user_chat_id": user_chat_id,
                    "updated_at": datetime.utcnow()
                },

                "$setOnInsert": {
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # GET PENDING
    # ========================================================

    async def get_pending(
        self,
        chat_id,
        limit
    ):

        cursor = pending_requests.find(
            {
                "chat_id": chat_id
            }
        ).sort(
            "created_at",
            1
        ).limit(limit)

        result = []

        async for doc in cursor:
            result.append(doc)

        return result

    # ========================================================
    # REMOVE PENDING
    # ========================================================

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

    # ========================================================
    # REMOVE ALL PENDING
    # ========================================================

    async def remove_all_pending(
        self,
        chat_id
    ):

        await pending_requests.delete_many(
            {
                "chat_id": chat_id
            }
        )

    # ========================================================
    # TOTAL PENDING
    # ========================================================

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
            {
                "_id": "main"
            },
            {
                "$set": data,

                "$setOnInsert": {
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # GET AD
    # ========================================================

    async def get_ad(self):

        return await ads.find_one(
            {
                "_id": "main"
            }
        )

    # ========================================================
    # DELETE AD
    # ========================================================

    async def delete_ad(self):

        await ads.delete_one(
            {
                "_id": "main"
            }
        )

    # ========================================================
    # HAS AD
    # ========================================================

    async def has_ad(self):

        return (
            await ads.find_one(
                {
                    "_id": "main"
                }
            )
            is not None
        )

    # ========================================================
    # PING
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
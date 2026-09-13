from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL
import os
from datetime import datetime


# ============================================================
# CURRENT MONGODB CONNECTION
# ============================================================

mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    serverSelectionTimeoutMS=10000
)

db = mongo_client["auto_join_request_bot"]


# ============================================================
# OLD MONGODB CONNECTION
# ============================================================

OLD_MONGO_URL = os.getenv("OLD_MONGO_URL", "").strip()

old_mongo_client = None
old_db = None

if OLD_MONGO_URL:
    old_mongo_client = AsyncIOMotorClient(
        OLD_MONGO_URL,
        serverSelectionTimeoutMS=10000
    )

    old_db = old_mongo_client["auto_join_request_bot"]


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

    async def save_user(
        self,
        user_id,
        username=None,
        first_name=None,
        last_name=None,
        user_chat_id=None
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

        await users.update_one(
            {"_id": user_id},
            {
                "$set": data,
                "$setOnInsert": {
                    "verified": False,
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )

    # ========================================================
    # GET ALL USERS
    # ========================================================

    async def get_all_users(self):

        cursor = users.find(
            {},
            {
                "_id": 1
            }
        )

        result = []

        async for doc in cursor:
            result.append(doc["_id"])

        return result

    # ========================================================
    # GET VERIFIED USERS
    # ========================================================

    async def get_verified_users(self):

        cursor = users.find(
            {
                "verified": True
            },
            {
                "_id": 1
            }
        )

        result = []

        async for doc in cursor:
            result.append(doc["_id"])

        return result

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
                    "verified_at": datetime.utcnow()
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
    # TOTAL USERS
    # ========================================================

    async def total_users(self):

        return await users.count_documents({})

    # ========================================================
    # TOTAL VERIFIED USERS
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

                # New group/channel:
                # Auto approval OFF
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
            result.append(doc["_id"])

        return result

    # ========================================================
    # GET ALL GROUP DOCUMENTS
    # ========================================================

    async def get_all_group_docs(self):

        cursor = groups.find({})

        result = []

        async for doc in cursor:
            result.append(doc)

        return result

    # ========================================================
    # TOTAL GROUPS
    # ========================================================

    async def total_groups(self):

        return await groups.count_documents({})

    # ========================================================
    # SET APPROVAL
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
    # CHECK APPROVAL
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
    # DELETE GROUP
    # ========================================================

    async def delete_group(self, chat_id):

        await groups.delete_one(
            {
                "_id": chat_id
            }
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
                    "user_chat_id": user_chat_id,
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
    # REMOVE ONE PENDING
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
    # MARGET / MERGE OLD DATABASE
    # ========================================================

    async def merge_old_data(self):

        if old_db is None:

            return {
                "success": False,
                "message": "OLD_MONGO_URL not configured",
                "users": 0,
                "groups": 0,
                "pending": 0,
                "ads": 0
            }

        merged_users = 0
        merged_groups = 0
        merged_pending = 0
        merged_ads = 0

        # ====================================================
        # USERS
        # ====================================================

        old_users = old_db["users"]

        async for doc in old_users.find({}):

            user_id = doc.get(
                "_id"
            )

            if user_id is None:
                continue

            new_data = {
                "_id": user_id
            }

            for key in [
                "user_id",
                "username",
                "first_name",
                "last_name",
                "user_chat_id",
                "verified",
                "verified_at",
                "created_at",
                "updated_at"
            ]:

                if key in doc:
                    new_data[key] = doc[key]

            await users.update_one(
                {
                    "_id": user_id
                },
                {
                    "$setOnInsert": new_data
                },
                upsert=True
            )

            merged_users += 1

        # ====================================================
        # GROUPS
        # ====================================================

        old_groups = old_db["groups"]

        async for doc in old_groups.find({}):

            chat_id = doc.get(
                "_id"
            )

            if chat_id is None:
                continue

            new_data = {
                "_id": chat_id
            }

            for key in [
                "chat_id",
                "title",
                "username",
                "chat_type",
                "approve_enabled",
                "created_at",
                "updated_at"
            ]:

                if key in doc:
                    new_data[key] = doc[key]

            await groups.update_one(
                {
                    "_id": chat_id
                },
                {
                    "$setOnInsert": new_data
                },
                upsert=True
            )

            merged_groups += 1

        # ====================================================
        # PENDING REQUESTS
        # ====================================================

        old_pending = old_db[
            "pending_requests"
        ]

        async for doc in old_pending.find({}):

            chat_id = doc.get(
                "chat_id"
            )

            user_id = doc.get(
                "user_id"
            )

            if chat_id is None or user_id is None:
                continue

            await pending_requests.update_one(
                {
                    "chat_id": chat_id,
                    "user_id": user_id
                },
                {
                    "$setOnInsert": {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "user_chat_id": doc.get(
                            "user_chat_id"
                        ),
                        "created_at": doc.get(
                            "created_at",
                            datetime.utcnow()
                        )
                    }
                },
                upsert=True
            )

            merged_pending += 1

        # ====================================================
        # AD
        # ====================================================

        old_ads = old_db["ads"]

        old_ad = await old_ads.find_one(
            {
                "_id": "main"
            }
        )

        current_ad = await ads.find_one(
            {
                "_id": "main"
            }
        )

        # Current ad ko overwrite nahi karega.
        # Sirf tab old ad dalega jab current DB me ad nahi hai.

        if old_ad and not current_ad:

            await ads.insert_one(
                old_ad
            )

            merged_ads = 1

        return {
            "success": True,
            "message": "Old database merged successfully",
            "users": merged_users,
            "groups": merged_groups,
            "pending": merged_pending,
            "ads": merged_ads
        }

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
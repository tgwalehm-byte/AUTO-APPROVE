import os

from motor.motor_asyncio import AsyncIOMotorClient


# =========================================================
# MONGODB
# =========================================================

MONGO_URL = os.environ["MONGO_URL"]

mongo = AsyncIOMotorClient(MONGO_URL)

db = mongo["join_request_bot"]

settings_collection = db["settings"]
ads_collection = db["ads"]
requests_collection = db["requests"]
users_collection = db["users"]
groups_collection = db["groups"]


# =========================================================
# AUTO APPROVE
# =========================================================

async def get_auto_approve(chat_id: int) -> bool:

    data = await settings_collection.find_one(
        {"chat_id": chat_id}
    )

    if not data:
        return False

    return bool(
        data.get("auto_approve", False)
    )


async def set_auto_approve(
    chat_id: int,
    status: bool
):

    await settings_collection.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "auto_approve": status
            }
        },
        upsert=True
    )


# =========================================================
# ADVERTISEMENT
# =========================================================

async def get_ad():

    data = await ads_collection.find_one(
        {"_id": "global_ad"}
    )

    if not data:
        return None

    return data.get("text")


async def save_ad(
    text: str
):

    await ads_collection.update_one(
        {"_id": "global_ad"},
        {
            "$set": {
                "text": text
            }
        },
        upsert=True
    )


async def delete_ad():

    await ads_collection.delete_one(
        {"_id": "global_ad"}
    )


# =========================================================
# USERS
# =========================================================

async def save_user(
    user_id: int
):

    await users_collection.update_one(
        {
            "user_id": user_id
        },
        {
            "$set": {
                "user_id": user_id
            }
        },
        upsert=True
    )


async def get_all_users():

    cursor = users_collection.find(
        {},
        {
            "_id": 0,
            "user_id": 1
        }
    )

    return await cursor.to_list(
        length=None
    )


async def delete_user(
    user_id: int
):

    await users_collection.delete_one(
        {
            "user_id": user_id
        }
    )


async def get_total_users():

    return await users_collection.count_documents({})


# =========================================================
# GROUPS
# =========================================================

async def save_group(
    chat_id: int,
    title: str = ""
):

    await groups_collection.update_one(
        {
            "chat_id": chat_id
        },
        {
            "$set": {
                "chat_id": chat_id,
                "title": title
            }
        },
        upsert=True
    )


async def delete_group(
    chat_id: int
):

    await groups_collection.delete_one(
        {
            "chat_id": chat_id
        }
    )


async def get_all_groups():

    cursor = groups_collection.find(
        {},
        {
            "_id": 0,
            "chat_id": 1,
            "title": 1
        }
    )

    return await cursor.to_list(
        length=None
    )


async def get_total_groups():

    return await groups_collection.count_documents({})


# =========================================================
# JOIN REQUESTS
# =========================================================

async def save_request(
    chat_id: int,
    user_id: int
):

    await requests_collection.update_one(
        {
            "chat_id": chat_id,
            "user_id": user_id
        },
        {
            "$set": {
                "chat_id": chat_id,
                "user_id": user_id
            }
        },
        upsert=True
    )


async def get_pending_requests(
    chat_id: int,
    limit: int
):

    cursor = requests_collection.find(
        {
            "chat_id": chat_id
        }
    ).limit(limit)

    return await cursor.to_list(
        length=limit
    )


async def delete_request(
    chat_id: int,
    user_id: int
):

    await requests_collection.delete_one(
        {
            "chat_id": chat_id,
            "user_id": user_id
        }
    )
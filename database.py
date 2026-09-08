import os

from motor.motor_asyncio import AsyncIOMotorClient


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


async def save_ad(text: str):

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
    user_id: int,
    started: bool = False,
    name: str = "",
    username: str = ""
):

    update = {
        "user_id": user_id,
        "name": name,
        "username": username
    }

    if started:
        update["started"] = True

    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": update},
        upsert=True
    )


async def mark_user_started(
    user_id: int
):

    await users_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "started": True
            }
        },
        upsert=True
    )


async def get_all_users(
    started_only: bool = False
):

    query = {}

    if started_only:
        query["started"] = True

    cursor = users_collection.find(
        query,
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
        {"user_id": user_id}
    )


async def get_total_users():

    return await users_collection.count_documents({})


async def get_started_users():

    return await users_collection.count_documents(
        {"started": True}
    )


# =========================================================
# GROUPS / CHANNELS
# =========================================================

async def save_group(
    chat_id: int,
    title: str = "",
    chat_type: str = "group",
    username: str = ""
):

    await groups_collection.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "title": title,
                "type": chat_type,
                "username": username
            }
        },
        upsert=True
    )


async def delete_group(
    chat_id: int
):

    await groups_collection.delete_one(
        {"chat_id": chat_id}
    )


async def get_all_groups():

    cursor = groups_collection.find(
        {
            "type": {
                "$in": [
                    "group",
                    "supergroup"
                ]
            }
        },
        {
            "_id": 0,
            "chat_id": 1,
            "title": 1,
            "type": 1,
            "username": 1
        }
    )

    return await cursor.to_list(
        length=None
    )


async def get_all_channels():

    cursor = groups_collection.find(
        {"type": "channel"},
        {
            "_id": 0,
            "chat_id": 1,
            "title": 1,
            "type": 1,
            "username": 1
        }
    )

    return await cursor.to_list(
        length=None
    )


async def get_all_chats():

    cursor = groups_collection.find(
        {},
        {
            "_id": 0,
            "chat_id": 1,
            "title": 1,
            "type": 1,
            "username": 1
        }
    )

    return await cursor.to_list(
        length=None
    )


async def get_total_groups():

    return await groups_collection.count_documents(
        {
            "type": {
                "$in": [
                    "group",
                    "supergroup"
                ]
            }
        }
    )


async def get_total_channels():

    return await groups_collection.count_documents(
        {"type": "channel"}
    )


async def get_chat_info(
    chat_id: int
):

    return await groups_collection.find_one(
        {"chat_id": chat_id},
        {"_id": 0}
    )


# =========================================================
# JOIN REQUESTS
# =========================================================

async def save_request(
    chat_id: int,
    user_id: int,
    name: str = "",
    username: str = ""
):

    await requests_collection.update_one(
        {
            "chat_id": chat_id,
            "user_id": user_id
        },
        {
            "$set": {
                "chat_id": chat_id,
                "user_id": user_id,
                "name": name,
                "username": username
            }
        },
        upsert=True
    )


async def get_pending_requests(
    chat_id: int,
    limit: int = 100
):

    cursor = requests_collection.find(
        {"chat_id": chat_id}
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


async def get_pending_count(
    chat_id: int
):

    return await requests_collection.count_documents(
        {"chat_id": chat_id}
    )
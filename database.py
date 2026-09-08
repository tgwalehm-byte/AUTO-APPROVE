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


# =========================================================
# AUTO APPROVE
# =========================================================

async def get_auto_approve(chat_id: int) -> bool:

    data = await settings_collection.find_one(
        {"chat_id": chat_id}
    )

    if not data:
        return False

    return bool(data.get("auto_approve", False))


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
# GLOBAL AD
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


async def clear_request(
    chat_id: int,
    user_id: int
):

    await delete_request(
        chat_id,
        user_id
    )
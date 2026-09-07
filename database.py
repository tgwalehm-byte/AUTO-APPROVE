import os
from motor.motor_asyncio import AsyncIOMotorClient

# MongoDB URL
MONGO_URL = os.environ["MONGO_URL"]

# MongoDB connection
mongo = AsyncIOMotorClient(MONGO_URL)

db = mongo["join_request_bot"]

settings_collection = db["settings"]
ads_collection = db["ads"]


# =========================
# AUTO APPROVE
# =========================

async def get_auto_approve(chat_id: int) -> bool:

    data = await settings_collection.find_one(
        {"chat_id": chat_id}
    )

    if not data:
        return False

    return data.get(
        "auto_approve",
        False
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


# =========================
# ADVERTISEMENT
# =========================

async def get_ad(chat_id: int):

    data = await ads_collection.find_one(
        {"chat_id": chat_id}
    )

    if not data:
        return None

    return data.get("text")


async def save_ad(
    chat_id: int,
    text: str
):

    await ads_collection.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "text": text
            }
        },
        upsert=True
    )


async def delete_ad(
    chat_id: int
):

    await ads_collection.delete_one(
        {"chat_id": chat_id}
    )
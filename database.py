import os

from motor.motor_asyncio import AsyncIOMotorClient


# =========================================================
# MONGODB CONFIG
# =========================================================

MONGO_URL = os.environ["MONGO_URL"]

mongo = AsyncIOMotorClient(
    MONGO_URL
)

db = mongo["join_request_bot"]


# Collections
settings_collection = db["settings"]
ads_collection = db["ads"]


# =========================================================
# AUTO APPROVE
# =========================================================

async def get_auto_approve(
    chat_id: int
) -> bool:

    data = await settings_collection.find_one(
        {
            "chat_id": chat_id
        }
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
        {
            "chat_id": chat_id
        },
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
#
# Advertisement GLOBAL hai.
# Owner ek baar /setad karega.
# Sabhi configured groups ke join-request
# users ko wahi advertisement milega.
#
# =========================================================

async def get_ad():

    data = await ads_collection.find_one(
        {
            "_id": "global_ad"
        }
    )

    if not data:
        return None

    return data.get(
        "text"
    )


async def save_ad(
    text: str
):

    await ads_collection.update_one(
        {
            "_id": "global_ad"
        },
        {
            "$set": {
                "text": text
            }
        },
        upsert=True
    )


async def delete_ad():

    await ads_collection.delete_one(
        {
            "_id": "global_ad"
        }
    )
import os
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait, UserIsBlocked, PeerIdInvalid

from database import (
    get_auto_approve,
    set_auto_approve,
    get_ad,
    save_ad,
    delete_ad
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

app = Client(
    "JoinRequestBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

running_tasks = {}


async def is_admin(client, chat_id, user_id):
    try:
        member = await client.get_chat_member(chat_id, user_id)

        return member.status in (
            "administrator",
            "owner"
        )

    except Exception:
        return False


# =========================
# /approve
# =========================

@app.on_message(filters.command("approve"))
async def approve_toggle(client, message):

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id
    ):
        return await message.reply_text(
            "❌ Admin only."
        )

    chat_id = message.chat.id

    current = await get_auto_approve(chat_id)

    new_status = not current

    await set_auto_approve(
        chat_id,
        new_status
    )

    status = "ON 🟢" if new_status else "OFF 🔴"

    await message.reply_text(
        f"🤖 Auto Approve: {status}"
    )


# =========================
# JOIN REQUEST
# =========================

@app.on_chat_join_request()
async def join_request(client, request: ChatJoinRequest):

    chat_id = request.chat.id
    user = request.from_user

    # Send Advertisement
    ad = await get_ad(chat_id)

    if ad:

        try:

            await client.send_message(
                user.id,
                ad
            )

        except (
            UserIsBlocked,
            PeerIdInvalid
        ):

            pass

        except Exception as e:

            logging.error(
                f"DM error: {e}"
            )

    # Auto approve
    if await get_auto_approve(chat_id):

        try:

            await client.approve_chat_join_request(
                chat_id,
                user.id
            )

        except FloodWait as e:

            await asyncio.sleep(e.value)

        except Exception as e:

            logging.error(
                f"Approve error: {e}"
            )


# =========================
# /addmember
# =========================

@app.on_message(filters.command("addmember"))
async def addmember(client, message):

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id
    ):
        return await message.reply_text(
            "❌ Admin only."
        )

    if len(message.command) < 2:

        return await message.reply_text(
            "Usage:\n\n"
            "/addmember 10\n"
            "/addmember 100\n"
            "/addmember 1k\n"
            "/addmember 10k"
        )

    value = message.command[1].lower()

    try:

        if value.endswith("k"):
            amount = int(
                float(value[:-1]) * 1000
            )
        else:
            amount = int(value)

    except ValueError:

        return await message.reply_text(
            "❌ Invalid number."
        )

    if message.chat.id in running_tasks:

        return await message.reply_text(
            "⚠️ Approval already running."
        )

    task = asyncio.create_task(
        approve_requests(
            client,
            message,
            message.chat.id,
            amount
        )
    )

    running_tasks[message.chat.id] = task

    await message.reply_text(
        f"⏳ Starting...\n\n"
        f"🎯 Target: {amount:,}\n\n"
        f"Use /stop to stop."
    )


async def approve_requests(
    client,
    message,
    chat_id,
    amount
):

    approved = 0
    failed = 0

    try:

        async for request in client.get_chat_join_requests(
            chat_id
        ):

            if approved >= amount:
                break

            try:

                await client.approve_chat_join_request(
                    chat_id,
                    request.user.id
                )

                approved += 1

                await asyncio.sleep(0.1)

            except FloodWait as e:

                await asyncio.sleep(e.value)

            except Exception:

                failed += 1

        await message.reply_text(
            "✅ Completed\n\n"
            f"Approved: {approved:,}\n"
            f"Failed: {failed:,}"
        )

    except asyncio.CancelledError:

        await message.reply_text(
            "🛑 Stopped\n\n"
            f"Approved: {approved:,}"
        )

    except Exception as e:

        await message.reply_text(
            f"❌ Error: `{e}`"
        )

    finally:

        running_tasks.pop(
            chat_id,
            None
        )


# =========================
# /stop
# =========================

@app.on_message(filters.command("stop"))
async def stop(client, message):

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id
    ):
        return await message.reply_text(
            "❌ Admin only."
        )

    task = running_tasks.get(
        message.chat.id
    )

    if not task:

        return await message.reply_text(
            "ℹ️ Nothing is running."
        )

    task.cancel()

    await message.reply_text(
        "🛑 Stopping..."
    )


# =========================
# /remove
# =========================

@app.on_message(filters.command("remove"))
async def remove_deleted(client, message):

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id
    ):
        return await message.reply_text(
            "❌ Admin only."
        )

    chat_id = message.chat.id

    checked = 0
    removed = 0

    msg = await message.reply_text(
        "🧹 Checking requests..."
    )

    try:

        async for request in client.get_chat_join_requests(
            chat_id
        ):

            checked += 1

            user = request.user

            if getattr(
                user,
                "is_deleted",
                False
            ):

                try:

                    await client.decline_chat_join_request(
                        chat_id,
                        user.id
                    )

                    removed += 1

                except FloodWait as e:

                    await asyncio.sleep(e.value)

                except Exception:
                    pass

        await msg.edit_text(
            "✅ Cleanup completed\n\n"
            f"🔎 Checked: {checked:,}\n"
            f"🗑 Removed: {removed:,}"
        )

    except Exception as e:

        await msg.edit_text(
            f"❌ Error: `{e}`"
        )


# =========================
# /setad
# =========================

@app.on_message(filters.command("setad"))
async def set_ad(client, message):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )

    if len(message.command) < 2:

        return await message.reply_text(
            "/setad Your advertisement"
        )

    text = message.text.split(
        None,
        1
    )[1]

    await save_ad(
        message.chat.id,
        text
    )

    await message.reply_text(
        "✅ Advertisement saved."
    )


# =========================
# /delad
# =========================

@app.on_message(filters.command("delad"))
async def del_ad(client, message):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )

    await delete_ad(
        message.chat.id
    )

    await message.reply_text(
        "🗑 Advertisement deleted."
    )


# =========================
# /start
# =========================

@app.on_message(filters.command("start"))
async def start(client, message):

    await message.reply_text(
        "👋 Hello!\n\n"
        "I am a Join Request Manager Bot."
    )


print("🤖 Bot Started")

app.run()
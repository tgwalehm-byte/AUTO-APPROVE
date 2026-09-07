import os
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait

from database import (
    get_auto_approve,
    set_auto_approve,
    get_ad,
    save_ad,
    delete_ad
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


# =========================================================
# ENVIRONMENT
# =========================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])


# =========================================================
# BOT
# =========================================================

app = Client(
    "JoinRequestBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# Running bulk approval tasks
running_tasks = {}


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(client, chat_id, user_id):

    try:

        member = await client.get_chat_member(
            chat_id,
            user_id
        )

        if member.status in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR
        ):
            return True

        return False

    except Exception as e:

        logging.error(
            f"Admin check failed: {e}"
        )

        return False


# =========================================================
# NUMBER PARSER
# =========================================================

def parse_amount(value):

    value = value.lower()
    value = value.replace(",", "")
    value = value.strip()

    try:

        if value.endswith("k"):

            number = float(
                value[:-1]
            )

            return int(
                number * 1000
            )

        return int(value)

    except Exception:

        return None


# =========================================================
# /approve
# AUTO APPROVE ON / OFF
# =========================================================

@app.on_message(
    filters.command("approve") & filters.group
)
async def approve_command(client, message):

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Check admin
    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ Admin only."
        )

    current = await get_auto_approve(
        chat_id
    )

    new_status = not current

    await set_auto_approve(
        chat_id,
        new_status
    )

    if new_status:

        await message.reply_text(
            "🟢 **AUTO APPROVE ON**\n\n"
            "New join requests will now "
            "be automatically approved."
        )

    else:

        await message.reply_text(
            "🔴 **AUTO APPROVE OFF**\n\n"
            "New join requests will no longer "
            "be automatically approved."
        )


# =========================================================
# JOIN REQUEST
# =========================================================

@app.on_chat_join_request()
async def join_request(
    client,
    request: ChatJoinRequest
):

    chat_id = request.chat.id
    user = request.from_user

    logging.info(
        f"Join request: {user.id} -> {chat_id}"
    )


    # =====================================================
    # SEND OWNER AD
    # =====================================================

    try:

        ad = await get_ad()

        if ad:

            try:

                # IMPORTANT:
                # Telegram provides a temporary
                # user chat ID for join requests.
                await client.send_message(
                    request.user_chat_id,
                    ad
                )

                logging.info(
                    f"Advertisement sent to {user.id}"
                )

            except Exception as e:

                logging.error(
                    f"Advertisement DM failed: {e}"
                )


    except Exception as e:

        logging.error(
            f"Advertisement database error: {e}"
        )


    # =====================================================
    # AUTO APPROVE
    # =====================================================

    try:

        enabled = await get_auto_approve(
            chat_id
        )

        if not enabled:
            return

        await client.approve_chat_join_request(
            chat_id,
            user.id
        )

        logging.info(
            f"Auto approved: {user.id}"
        )

    except FloodWait as e:

        logging.warning(
            f"FloodWait: {e.value} seconds"
        )

        await asyncio.sleep(
            e.value
        )

        try:

            await client.approve_chat_join_request(
                chat_id,
                user.id
            )

        except Exception as error:

            logging.error(
                f"Approve retry failed: {error}"
            )

    except Exception as e:

        logging.error(
            f"Auto approve failed: {e}"
        )


# =========================================================
# /addmember
# =========================================================

@app.on_message(
    filters.command("addmember") & filters.group
)
async def addmember_command(
    client,
    message
):

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id


    # Admin check
    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ Admin only."
        )


    # Argument check
    if len(message.command) < 2:

        return await message.reply_text(
            "❌ **Usage:**\n\n"
            "/addmember 10\n"
            "/addmember 20\n"
            "/addmember 100\n"
            "/addmember 1k\n"
            "/addmember 10k"
        )


    amount = parse_amount(
        message.command[1]
    )


    if amount is None or amount <= 0:

        return await message.reply_text(
            "❌ Invalid number."
        )


    # Already running
    if chat_id in running_tasks:

        return await message.reply_text(
            "⚠️ Approval process is already running.\n\n"
            "Use /stop first."
        )


    # Create task
    task = asyncio.create_task(
        bulk_approve(
            client,
            message,
            chat_id,
            amount
        )
    )


    running_tasks[chat_id] = task


    await message.reply_text(
        "🚀 **Approval Started**\n\n"
        f"🎯 Target: `{amount:,}`\n"
        "⚡ Processing pending requests...\n\n"
        "🛑 Use `/stop` to stop."
    )


# =========================================================
# BULK APPROVE
# =========================================================

async def bulk_approve(
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


                if approved % 100 == 0:

                    logging.info(
                        f"{chat_id}: "
                        f"{approved}/{amount}"
                    )


                await asyncio.sleep(
                    0.08
                )


            except FloodWait as e:

                logging.warning(
                    f"FloodWait {e.value}s"
                )

                await asyncio.sleep(
                    e.value
                )


            except Exception as e:

                failed += 1

                logging.error(
                    f"Approval failed: {e}"
                )


        await message.reply_text(
            "✅ **Approval Completed**\n\n"
            f"👥 Approved: `{approved:,}`\n"
            f"❌ Failed: `{failed:,}`"
        )


    except asyncio.CancelledError:

        await message.reply_text(
            "🛑 **Approval Stopped**\n\n"
            f"✅ Approved: `{approved:,}`\n"
            "⏳ Remaining requests were not processed."
        )


    except Exception as e:

        logging.error(
            f"Bulk approval error: {e}"
        )

        await message.reply_text(
            f"❌ Error:\n`{e}`"
        )


    finally:

        running_tasks.pop(
            chat_id,
            None
        )


# =========================================================
# /stop
# =========================================================

@app.on_message(
    filters.command("stop") & filters.group
)
async def stop_command(
    client,
    message
):

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id


    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ Admin only."
        )


    task = running_tasks.get(
        chat_id
    )


    if not task:

        return await message.reply_text(
            "ℹ️ No approval process is running."
        )


    task.cancel()


    await message.reply_text(
        "🛑 **Stopping approval process...**"
    )


# =========================================================
# /remove
# =========================================================

@app.on_message(
    filters.command("remove") & filters.group
)
async def remove_deleted(
    client,
    message
):

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id


    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ Admin only."
        )


    if chat_id in running_tasks:

        return await message.reply_text(
            "⚠️ Approval process is running.\n"
            "Use /stop first."
        )


    msg = await message.reply_text(
        "🧹 **Checking pending requests...**"
    )


    checked = 0
    removed = 0


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

                    await asyncio.sleep(
                        0.08
                    )

                except FloodWait as e:

                    await asyncio.sleep(
                        e.value
                    )

                except Exception as e:

                    logging.error(
                        f"Remove failed: {e}"
                    )


        await msg.edit_text(
            "✅ **Cleanup Completed**\n\n"
            f"🔎 Checked: `{checked:,}`\n"
            f"🗑 Removed: `{removed:,}`"
        )


    except Exception as e:

        logging.error(
            f"Cleanup error: {e}"
        )

        await msg.edit_text(
            f"❌ Error:\n`{e}`"
        )


# =========================================================
# /setad
# OWNER PRIVATE CHAT
# =========================================================

@app.on_message(
    filters.command("setad") & filters.private
)
async def set_ad_command(
    client,
    message
):

    if not message.from_user:
        return


    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )


    if len(message.command) < 2:

        return await message.reply_text(
            "📢 **Usage:**\n\n"
            "/setad Your advertisement"
        )


    text = message.text.split(
        None,
        1
    )[1]


    await save_ad(
        text
    )


    await message.reply_text(
        "✅ **Advertisement Saved!**\n\n"
        "New join-request users will "
        "receive this advertisement."
    )


# =========================================================
# /delad
# OWNER PRIVATE CHAT
# =========================================================

@app.on_message(
    filters.command("delad") & filters.private
)
async def delete_ad_command(
    client,
    message
):

    if not message.from_user:
        return


    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )


    await delete_ad()


    await message.reply_text(
        "🗑 **Advertisement Deleted!**"
    )


# =========================================================
# /start
# =========================================================

@app.on_message(filters.command("start"))
async def start_command(
    client,
    message
):

    await message.reply_text(
        "👋 **Hello!**\n\n"
        "I am a Join Request Manager Bot.\n\n"
        "Add me to your group as an administrator "
        "with permission to manage join requests."
    )


# =========================================================
# START
# =========================================================

print(
    "🤖 Join Request Manager Bot Started..."
)

app.run()
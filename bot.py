 import os
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import (
    FloodWait,
    UserIsBlocked,
    PeerIdInvalid
)

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
# ENV
# =========================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])


# =========================================================
# CLIENT
# =========================================================

app = Client(
    "JoinRequestBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# Running bulk operations
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

        return member.status in (
            "administrator",
            "owner"
        )

    except Exception as e:

        logging.error(
            f"Admin check error: {e}"
        )

        return False


# =========================================================
# NUMBER PARSER
# =========================================================

def parse_amount(value):

    value = value.lower().replace(",", "").strip()

    try:

        if value.endswith("k"):

            number = float(
                value[:-1]
            )

            return int(
                number * 1000
            )

        return int(value)

    except (ValueError, TypeError):

        return None


# =========================================================
# /approve
# AUTO APPROVE ON / OFF
# =========================================================

@app.on_message(
    filters.command("approve") & filters.group
)
async def approve_toggle(client, message):

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
            "🟢 **Auto Approve: ON**\n\n"
            "New join requests will be "
            "automatically approved."
        )

    else:

        await message.reply_text(
            "🔴 **Auto Approve: OFF**\n\n"
            "New join requests will no longer "
            "be automatically approved."
        )


# =========================================================
# JOIN REQUEST HANDLER
# =========================================================

@app.on_chat_join_request()
async def join_request_handler(
    client,
    request: ChatJoinRequest
):

    chat_id = request.chat.id
    user = request.from_user

    logging.info(
        f"Join request received: "
        f"{user.id} -> {chat_id}"
    )


    # =====================================================
    # SEND OWNER AD
    # =====================================================

    try:

        ad = await get_ad()

        if ad:

            try:

                # IMPORTANT:
                # user.id ki jagah user_chat_id
                await client.send_message(
                    request.user_chat_id,
                    ad
                )

                logging.info(
                    f"Ad sent to {user.id}"
                )

            except (
                UserIsBlocked,
                PeerIdInvalid
            ):

                logging.info(
                    f"Cannot DM user {user.id}"
                )

            except Exception as e:

                logging.error(
                    f"Ad DM error: {e}"
                )

    except Exception as e:

        logging.error(
            f"Get ad error: {e}"
        )


    # =====================================================
    # AUTO APPROVE
    # =====================================================

    try:

        auto = await get_auto_approve(
            chat_id
        )

        if not auto:
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
            f"FloodWait: sleeping {e.value}s"
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
                f"Retry approve error: {error}"
            )

    except Exception as e:

        logging.error(
            f"Auto approve error: {e}"
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


    # Check argument
    if len(message.command) < 2:

        return await message.reply_text(
            "❌ Usage:\n\n"
            "`/addmember 10`\n"
            "`/addmember 100`\n"
            "`/addmember 1k`\n"
            "`/addmember 10k`"
        )


    amount = parse_amount(
        message.command[1]
    )


    if amount is None or amount <= 0:

        return await message.reply_text(
            "❌ Invalid number.\n\n"
            "Example:\n"
            "`/addmember 100`\n"
            "`/addmember 1k`"
        )


    # Already running?
    if chat_id in running_tasks:

        return await message.reply_text(
            "⚠️ Approval process already running.\n\n"
            "Use `/stop` first."
        )


    # Create task
    task = asyncio.create_task(
        approve_requests(
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
# BULK APPROVAL
# =========================================================

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

            # Stop target reached
            if approved >= amount:
                break


            # Stop command
            current_task = asyncio.current_task()

            if current_task.cancelled():
                break


            try:

                await client.approve_chat_join_request(
                    chat_id,
                    request.user.id
                )

                approved += 1


                # Every 100 approvals log progress
                if approved % 100 == 0:

                    logging.info(
                        f"{chat_id}: "
                        f"{approved}/{amount} approved"
                    )


                # Small delay
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
            f"⏳ Remaining requests were not processed."
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


    # Admin check
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
# REMOVE DELETED ACCOUNT REQUESTS
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


    # Admin check
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
            "Use `/stop` first."
        )


    status = await message.reply_text(
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


            # Telegram deleted account
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
                        f"Remove error: {e}"
                    )


        await status.edit_text(
            "✅ **Cleanup Completed**\n\n"
            f"🔎 Checked: `{checked:,}`\n"
            f"🗑 Removed: `{removed:,}`"
        )


    except Exception as e:

        logging.error(
            f"Cleanup error: {e}"
        )

        await status.edit_text(
            f"❌ Error:\n`{e}`"
        )


# =========================================================
# /setad
# OWNER PRIVATE CHAT ONLY
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


    # Owner only
    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )


    if len(message.command) < 2:

        return await message.reply_text(
            "📢 **Set Advertisement**\n\n"
            "Usage:\n"
            "`/setad Your advertisement text`"
        )


    text = message.text.split(
        None,
        1
    )[1]


    await save_ad(
        text
    )


    await message.reply_text(
        "✅ **Advertisement Saved**\n\n"
        "New join-request users will receive "
        "this advertisement."
    )


# =========================================================
# /delad
# OWNER PRIVATE CHAT ONLY
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
        "🗑 **Advertisement Deleted**"
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
# START BOT
# =========================================================

print("🤖 Join Request Manager Bot Started...")

app.run()
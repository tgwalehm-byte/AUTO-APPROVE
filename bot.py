import os
import sys
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
    delete_ad,
    save_request,
    get_pending_requests,
    delete_request,
    save_user,
    get_all_users,
    delete_user,
    save_group,
    get_all_groups,
    get_total_users,
    get_total_groups
)

from broadcast import start_broadcast


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


running_tasks = {}


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(
    client,
    chat_id,
    user_id
):

    try:

        member = await client.get_chat_member(
            chat_id,
            user_id
        )

        return member.status in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR
        )

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
# =========================================================

@app.on_message(
    filters.command("approve") & filters.group
)
async def approve_command(
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

    if not user:

        logging.error(
            "❌ Join request user not found."
        )

        return

    logging.info(
        f"📥 NEW JOIN REQUEST | "
        f"User: {user.id} | "
        f"Chat: {chat_id}"
    )


    # =====================================================
    # SAVE USER
    # =====================================================

    try:

        await save_user(
            user.id
        )

    except Exception as e:

        logging.error(
            f"Save user failed: {e}"
        )


    # =====================================================
    # SAVE GROUP
    # =====================================================

    try:

        await save_group(
            chat_id,
            request.chat.title or ""
        )

    except Exception as e:

        logging.error(
            f"Save group failed: {e}"
        )


    # =====================================================
    # SAVE JOIN REQUEST
    # =====================================================

    try:

        await save_request(
            chat_id,
            user.id
        )

        logging.info(
            f"💾 REQUEST SAVED | "
            f"User: {user.id}"
        )

    except Exception as e:

        logging.exception(
            f"❌ SAVE REQUEST FAILED: {e}"
        )


    # =====================================================
    # GET AD
    # =====================================================

    ad = None

    try:

        ad = await get_ad()

    except Exception as e:

        logging.error(
            f"Get ad failed: {e}"
        )


    # =====================================================
    # WELCOME MESSAGE
    # =====================================================

    welcome = (
        "👋 **Hello!**\n\n"
        "🤖 **Join Request Manager Bot**\n\n"
        "I help group administrators manage "
        "join requests and automatically approve "
        "new members when Auto Approve is enabled.\n\n"
        "✅ Manage Join Requests\n"
        "⚡ Auto Approval\n"
        "👥 Bulk Approval Support\n\n"
    )

    if ad:

        welcome += (
            "📢 **Advertisement**\n\n"
            f"{ad}\n\n"
        )

    welcome += (
        "✨ Thank you for requesting to join!"
    )


    # =====================================================
    # PRIVATE MESSAGE
    # =====================================================

    try:

        await client.send_message(
            user.id,
            welcome
        )

        logging.info(
            f"📩 WELCOME/AD SENT | "
            f"User: {user.id}"
        )

    except Exception as e:

        logging.warning(
            f"⚠️ PRIVATE MESSAGE FAILED | "
            f"User: {user.id} | {e}"
        )


    # =====================================================
    # AUTO APPROVE
    # =====================================================

    try:

        auto_approve = await get_auto_approve(
            chat_id
        )

        if auto_approve:

            logging.info(
                f"⚡ AUTO APPROVING | "
                f"User: {user.id}"
            )

            try:

                await client.approve_chat_join_request(
                    chat_id,
                    user.id
                )

            except FloodWait as e:

                await asyncio.sleep(
                    e.value
                )

                await client.approve_chat_join_request(
                    chat_id,
                    user.id
                )

            await delete_request(
                chat_id,
                user.id
            )

            logging.info(
                f"✅ AUTO APPROVED | "
                f"User: {user.id}"
            )

    except Exception as e:

        logging.exception(
            f"❌ AUTO APPROVE FAILED: {e}"
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

        requests = await get_pending_requests(
            chat_id,
            amount
        )

        if not requests:

            await message.reply_text(
                "ℹ️ No saved pending requests found."
            )

            return


        for request in requests:

            try:

                await client.approve_chat_join_request(
                    chat_id,
                    request["user_id"]
                )

                approved += 1

                await delete_request(
                    chat_id,
                    request["user_id"]
                )

                await asyncio.sleep(
                    0.08
                )

            except FloodWait as e:

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
            f"✅ Approved: `{approved:,}`"
        )

        raise


    except Exception as e:

        logging.exception(
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

    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ Admin only."
        )


    if len(message.command) < 2:

        return await message.reply_text(
            "❌ **Usage:**\n\n"
            "/addmember 10\n"
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


    if chat_id in running_tasks:

        return await message.reply_text(
            "⚠️ Approval process is already running.\n\n"
            "Use /stop first."
        )


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
        "⚡ Processing saved requests...\n\n"
        "🛑 Use `/stop` to stop."
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
async def remove_saved_requests(
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


    requests = await get_pending_requests(
        chat_id,
        10000
    )


    if not requests:

        return await message.reply_text(
            "ℹ️ No saved pending requests found."
        )


    msg = await message.reply_text(
        "🧹 **Removing saved pending requests...**"
    )


    removed = 0
    failed = 0


    for request in requests:

        try:

            await client.decline_chat_join_request(
                chat_id,
                request["user_id"]
            )

            await delete_request(
                chat_id,
                request["user_id"]
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

            failed += 1

            logging.error(
                f"Remove failed: {e}"
            )


    await msg.edit_text(
        "✅ **Cleanup Completed**\n\n"
        f"🗑 Removed: `{removed:,}`\n"
        f"❌ Failed: `{failed:,}`"
    )


# =========================================================
# /setad
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
        "✅ **Advertisement Saved!**"
    )


# =========================================================
# /delad
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
# /broadcast
# =========================================================

@app.on_message(
    filters.command("broadcast") & filters.private
)
async def broadcast_command(
    client,
    message
):

    if not message.from_user:
        return


    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )


    if not message.reply_to_message:

        return await message.reply_text(
            "📢 **Broadcast Usage**\n\n"
            "Kisi bhi message ko reply karke:\n"
            "`/broadcast`\n\n"
            "bhejo.\n\n"
            "Text, photo, video, voice, audio, "
            "document, sticker aur animation supported."
        )


    status = await message.reply_text(
        "📢 **Broadcast Preparing...**"
    )


    task = asyncio.create_task(
        start_broadcast(
            client,
            message.reply_to_message,
            status
        )
    )

    await task


# =========================================================
# /status
# =========================================================

@app.on_message(
    filters.command("status") & filters.private
)
async def status_command(
    client,
    message
):

    if not message.from_user:
        return


    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )


    try:

        total_users = await get_total_users()
        total_groups = await get_total_groups()

        await message.reply_text(
            "📊 **Bot Statistics**\n\n"
            f"👤 Total Users: `{total_users:,}`\n"
            f"👥 Total Groups: `{total_groups:,}`"
        )

    except Exception as e:

        logging.exception(
            f"Status error: {e}"
        )

        await message.reply_text(
            f"❌ Status error:\n`{e}`"
        )


# =========================================================
# /groups
# =========================================================

@app.on_message(
    filters.command("groups") & filters.private
)
async def groups_command(
    client,
    message
):

    if not message.from_user:
        return


    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )


    try:

        groups = await get_all_groups()

        if not groups:

            return await message.reply_text(
                "ℹ️ No groups found."
            )


        text = "👥 **Bot Groups**\n\n"

        for index, group in enumerate(
            groups,
            start=1
        ):

            title = group.get(
                "title",
                "Unknown"
            )

            chat_id = group.get(
                "chat_id"
            )

            text += (
                f"{index}. **{title}**\n"
                f"`{chat_id}`\n\n"
            )


        if len(text) > 4000:

            text = (
                "👥 **Total Groups:** "
                f"`{len(groups):,}`\n\n"
                "Group list is too large to display."
            )


        await message.reply_text(
            text
        )

    except Exception as e:

        logging.exception(
            f"Groups error: {e}"
        )

        await message.reply_text(
            f"❌ Error:\n`{e}`"
        )


# =========================================================
# /restart
# =========================================================

@app.on_message(
    filters.command("restart") & filters.private
)
async def restart_command(
    client,
    message
):

    if not message.from_user:
        return


    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ Owner only."
        )


    await message.reply_text(
        "♻️ **Restarting Bot...**"
    )


    await asyncio.sleep(
        1
    )


    os.execl(
        sys.executable,
        sys.executable,
        *sys.argv
    )


# =========================================================
# /start
# =========================================================

@app.on_message(
    filters.command("start")
)
async def start_command(
    client,
    message
):

    await message.reply_text(
        "👋 **Hello!**\n\n"
        "🤖 I am a Join Request Manager Bot.\n\n"
        "I help group administrators manage "
        "join requests and automate approvals.\n\n"
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
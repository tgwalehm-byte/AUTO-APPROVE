import os
import sys
import asyncio
import logging

import aiohttp

from pyrogram import Client, filters

from pyrogram.enums import ChatMemberStatus

from pyrogram.types import (
    ChatJoinRequest,
    ChatMemberUpdated
)

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
    get_total_users,

    save_group,
    get_all_groups,
    get_total_groups,
    delete_group
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


# =========================================================
# RUNNING TASKS
# =========================================================

running_tasks = {}


# =========================================================
# BOT API URL
# =========================================================

BOT_API_URL = (
    f"https://api.telegram.org/bot{BOT_TOKEN}"
)


# =========================================================
# BOT API REQUEST
# =========================================================

async def bot_api_call(
    method,
    data
):

    url = f"{BOT_API_URL}/{method}"

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            url,
            json=data
        ) as response:

            result = await response.json()

            if not result.get("ok"):

                error_code = result.get(
                    "error_code",
                    "UNKNOWN"
                )

                description = result.get(
                    "description",
                    "Unknown Telegram error"
                )

                raise RuntimeError(
                    f"Telegram API [{error_code}] "
                    f"{description}"
                )

            return result.get(
                "result"
            )


# =========================================================
# APPROVE JOIN REQUEST
# =========================================================

async def approve_join_request(
    chat_id,
    user_id
):

    return await bot_api_call(
        "approveChatJoinRequest",
        {
            "chat_id": chat_id,
            "user_id": user_id
        }
    )


# =========================================================
# DECLINE JOIN REQUEST
# =========================================================

async def decline_join_request(
    chat_id,
    user_id
):

    return await bot_api_call(
        "declineChatJoinRequest",
        {
            "chat_id": chat_id,
            "user_id": user_id
        }
    )


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
# REGISTER GROUP
# =========================================================

async def register_group(chat):

    if not chat:
        return

    try:

        await save_group(
            chat.id,
            chat.title or ""
        )

        logging.info(
            f"👥 GROUP SAVED | "
            f"{chat.title} | {chat.id}"
        )

    except Exception as e:

        logging.error(
            f"Group save failed: {e}"
        )


# =========================================================
# NUMBER PARSER
# =========================================================

def parse_amount(value):

    if not value:
        return None

    value = (
        value
        .lower()
        .replace(",", "")
        .strip()
    )

    try:

        if value.endswith("k"):

            number = float(
                value[:-1]
            )

            if number <= 0:
                return None

            return int(
                number * 1000
            )

        amount = int(value)

        if amount <= 0:
            return None

        return amount

    except (
        ValueError,
        TypeError
    ):

        return None


# =========================================================
# BOT ADDED / REMOVED
# =========================================================

@app.on_chat_member_updated()
async def chat_member_updated(
    client,
    update: ChatMemberUpdated
):

    try:

        if not update.chat:
            return

        chat = update.chat

        if chat.type not in (
            "group",
            "supergroup"
        ):
            return

        new_member = update.new_chat_member

        if not new_member:
            return

        if not new_member.user:
            return

        if not new_member.user.is_self:
            return

        new_status = new_member.status

        # =================================================
        # BOT ACTIVE
        # =================================================

        active_statuses = (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        )

        if new_status in active_statuses:

            await register_group(chat)

            logging.info(
                f"🤖 BOT ACTIVE IN GROUP | "
                f"{chat.title} | {chat.id}"
            )

            return

        # =================================================
        # BOT REMOVED
        # =================================================

        if new_status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.BANNED
        ):

            await delete_group(
                chat.id
            )

            logging.info(
                f"🚪 BOT REMOVED FROM GROUP | "
                f"{chat.title}"
            )

    except Exception as e:

        logging.exception(
            f"Chat member update error: {e}"
        )


# =========================================================
# /approve
# =========================================================

@app.on_message(
    filters.command("approve")
    & filters.group
)
async def approve_command(
    client,
    message
):

    if not message.from_user:
        return

    await register_group(
        message.chat
    )

    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ **Admin only.**"
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
            "New join requests will remain "
            "pending."
        )


# =========================================================
# JOIN REQUEST
# =========================================================

@app.on_chat_join_request()
async def join_request(
    client,
    request: ChatJoinRequest
):

    try:

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

        # =================================================
        # SAVE GROUP
        # =================================================

        await register_group(
            request.chat
        )

        # =================================================
        # SAVE USER
        # =================================================

        try:

            await save_user(
                user.id
            )

            logging.info(
                f"👤 USER SAVED | "
                f"{user.id}"
            )

        except Exception as e:

            logging.error(
                f"User save failed: {e}"
            )

        # =================================================
        # SAVE REQUEST
        # =================================================

        try:

            await save_request(
                chat_id,
                user.id
            )

            logging.info(
                f"💾 REQUEST SAVED | "
                f"{user.id}"
            )

        except Exception as e:

            logging.exception(
                f"❌ REQUEST SAVE FAILED: {e}"
            )

        # =================================================
        # GET AD
        # =================================================

        ad = None

        try:

            ad = await get_ad()

        except Exception as e:

            logging.error(
                f"Ad loading failed: {e}"
            )

        # =================================================
        # WELCOME
        # =================================================

        welcome = (
            "👋 **Hello!**\n\n"
            "🤖 **Join Request Manager Bot**\n\n"
            "I help group administrators manage "
            "join requests and automate approvals.\n\n"
            "✅ Join Request Management\n"
            "⚡ Auto Approval\n"
            "👥 Bulk Approval\n"
            "📢 Advertisement System\n\n"
        )

        if ad:

            welcome += (
                "📢 **Advertisement**\n\n"
                f"{ad}\n\n"
            )

        welcome += (
            "✨ Thank you for requesting to join!"
        )

        # =================================================
        # PRIVATE MESSAGE
        # =================================================

        try:

            await client.send_message(
                user.id,
                welcome
            )

            logging.info(
                f"📩 WELCOME/AD SENT | "
                f"{user.id}"
            )

        except Exception as e:

            logging.warning(
                f"⚠️ PRIVATE MESSAGE FAILED | "
                f"{user.id} | {e}"
            )

        # =================================================
        # AUTO APPROVE CHECK
        # =================================================

        auto_approve = await get_auto_approve(
            chat_id
        )

        if not auto_approve:

            logging.info(
                f"⏸️ REQUEST KEPT PENDING | "
                f"{user.id}"
            )

            return

        # =================================================
        # AUTO APPROVE
        # =================================================

        logging.info(
            f"⚡ AUTO APPROVING | "
            f"{user.id}"
        )

        while True:

            try:

                await approve_join_request(
                    chat_id,
                    user.id
                )

                break

            except Exception as e:

                error_text = str(e)

                if "429" in error_text:

                    await asyncio.sleep(3)

                    continue

                raise

        await delete_request(
            chat_id,
            user.id
        )

        logging.info(
            f"✅ AUTO APPROVED | "
            f"{user.id}"
        )

    except Exception as e:

        logging.exception(
            f"❌ JOIN REQUEST ERROR: {e}"
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
    stopped = False

    progress = None

    try:

        # =================================================
        # GET REQUESTS
        # =================================================

        requests = await get_pending_requests(
            chat_id,
            amount
        )

        total_found = len(
            requests
        )

        logging.info(
            f"📋 BULK APPROVE | "
            f"Requested: {amount} | "
            f"Found: {total_found}"
        )

        if not requests:

            await message.reply_text(
                "ℹ️ **No Saved Pending Requests**\n\n"
                "Auto approve OFF karke naye "
                "join requests aane do."
            )

            return

        # =================================================
        # PROGRESS
        # =================================================

        progress = await message.reply_text(
            "🚀 **APPROVAL STARTED**\n\n"
            f"🎯 Target: `{amount:,}`\n"
            f"📋 Found: `{total_found:,}`\n"
            f"⚡ Processed: `0`\n"
            f"✅ Approved: `0`\n"
            f"❌ Failed: `0`\n\n"
            "🛑 Use `/stop` to stop."
        )

        # =================================================
        # LOOP
        # =================================================

        for request in requests:

            if chat_id not in running_tasks:

                stopped = True
                break

            user_id = request.get(
                "user_id"
            )

            if not user_id:

                failed += 1
                continue

            success = False

            # =================================================
            # BOT API APPROVAL
            # =================================================

            while True:

                if chat_id not in running_tasks:

                    stopped = True
                    break

                try:

                    await approve_join_request(
                        chat_id,
                        user_id
                    )

                    success = True

                    logging.info(
                        f"✅ APPROVED | "
                        f"Chat: {chat_id} | "
                        f"User: {user_id}"
                    )

                    break

                except Exception as e:

                    error_text = str(e)

                    # Telegram rate limit
                    if (
                        "429" in error_text
                        or "Too Many Requests"
                        in error_text
                    ):

                        logging.warning(
                            f"⏳ Rate limit | "
                            f"User: {user_id}"
                        )

                        await asyncio.sleep(
                            3
                        )

                        continue

                    logging.error(
                        f"❌ Approval failed | "
                        f"Chat: {chat_id} | "
                        f"User: {user_id} | "
                        f"{e}"
                    )

                    break

            if stopped:
                break

            # =================================================
            # DELETE SUCCESSFUL REQUEST
            # =================================================

            if success:

                approved += 1

                try:

                    await delete_request(
                        chat_id,
                        user_id
                    )

                except Exception as e:

                    logging.error(
                        f"Mongo request delete failed | "
                        f"{user_id} | {e}"
                    )

            else:

                failed += 1

            await asyncio.sleep(
                0.10
            )

            # =================================================
            # PROGRESS UPDATE
            # =================================================

            processed = (
                approved +
                failed
            )

            if (
                processed % 10 == 0
                or processed == total_found
            ):

                try:

                    await progress.edit_text(
                        "🚀 **APPROVAL IN PROGRESS**\n\n"
                        f"🎯 Target: `{amount:,}`\n"
                        f"📋 Found: `{total_found:,}`\n"
                        f"⚡ Processed: `{processed:,}`\n"
                        f"✅ Approved: `{approved:,}`\n"
                        f"❌ Failed: `{failed:,}`\n\n"
                        "🛑 Use `/stop` to stop."
                    )

                except Exception:
                    pass

        # =================================================
        # STOPPED
        # =================================================

        if stopped:

            processed = (
                approved +
                failed
            )

            if progress:

                try:

                    await progress.edit_text(
                        "🛑 **APPROVAL STOPPED**\n\n"
                        f"🎯 Target: `{amount:,}`\n"
                        f"📋 Found: `{total_found:,}`\n"
                        f"⚡ Processed: `{processed:,}`\n"
                        f"✅ Approved: `{approved:,}`\n"
                        f"❌ Failed: `{failed:,}`"
                    )

                except Exception:
                    pass

            return

        # =================================================
        # COMPLETED
        # =================================================

        processed = (
            approved +
            failed
        )

        if progress:

            try:

                await progress.edit_text(
                    "✅ **APPROVAL COMPLETED**\n\n"
                    f"🎯 Requested: `{amount:,}`\n"
                    f"📋 Found: `{total_found:,}`\n\n"
                    f"⚡ Processed: `{processed:,}`\n"
                    f"✅ Approved: `{approved:,}`\n"
                    f"❌ Failed: `{failed:,}`"
                )

            except Exception:
                pass

    except asyncio.CancelledError:

        logging.info(
            f"🛑 BULK APPROVE CANCELLED | "
            f"{chat_id}"
        )

        raise

    except Exception as e:

        logging.exception(
            f"Bulk approval error: {e}"
        )

        try:

            await message.reply_text(
                "❌ **Bulk Approval Error**\n\n"
                f"`{e}`"
            )

        except Exception:
            pass

    finally:

        running_tasks.pop(
            chat_id,
            None
        )


# =========================================================
# /addmember
# =========================================================

@app.on_message(
    filters.command("addmember")
    & filters.group
)
async def addmember_command(
    client,
    message
):

    if not message.from_user:
        return

    await register_group(
        message.chat
    )

    chat_id = message.chat.id
    user_id = message.from_user.id

    # Admin
    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ **Admin only.**"
        )

    # Usage
    if len(message.command) < 2:

        return await message.reply_text(
            "❌ **Usage:**\n\n"
            "`/addmember 10`\n"
            "`/addmember 100`\n"
            "`/addmember 1k`\n"
            "`/addmember 10k`"
        )

    # Parse
    amount = parse_amount(
        message.command[1]
    )

    if amount is None:

        return await message.reply_text(
            "❌ **Invalid Number**\n\n"
            "Examples:\n"
            "`10`\n"
            "`100`\n"
            "`1k`\n"
            "`10k`"
        )

    # Already running
    if chat_id in running_tasks:

        return await message.reply_text(
            "⚠️ **Approval Already Running**\n\n"
            "Use `/stop` first."
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

    running_tasks[
        chat_id
    ] = task

    await message.reply_text(
        "🚀 **APPROVAL STARTED**\n\n"
        f"🎯 Target: `{amount:,}`\n"
        "📋 Saved pending requests will be processed.\n\n"
        "🛑 Use `/stop` to stop."
    )


# =========================================================
# /stop
# =========================================================

@app.on_message(
    filters.command("stop")
    & filters.group
)
async def stop_command(
    client,
    message
):

    if not message.from_user:
        return

    await register_group(
        message.chat
    )

    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ **Admin only.**"
        )

    task = running_tasks.get(
        chat_id
    )

    if not task:

        return await message.reply_text(
            "ℹ️ **No approval process is running.**"
        )

    # Remove task marker first
    running_tasks.pop(
        chat_id,
        None
    )

    # Cancel
    task.cancel()

    await message.reply_text(
        "🛑 **Stopping approval process...**"
    )


# =========================================================
# /remove
# =========================================================

@app.on_message(
    filters.command("remove")
    & filters.group
)
async def remove_saved_requests(
    client,
    message
):

    if not message.from_user:
        return

    await register_group(
        message.chat
    )

    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await is_admin(
        client,
        chat_id,
        user_id
    ):

        return await message.reply_text(
            "❌ **Admin only.**"
        )

    if chat_id in running_tasks:

        return await message.reply_text(
            "⚠️ **Approval process is running.**\n\n"
            "Use `/stop` first."
        )

    requests = await get_pending_requests(
        chat_id,
        10000
    )

    if not requests:

        return await message.reply_text(
            "ℹ️ **No Saved Pending Requests**"
        )

    msg = await message.reply_text(
        "🧹 **Removing saved pending requests...**"
    )

    removed = 0
    failed = 0

    for request in requests:

        user_id = request.get(
            "user_id"
        )

        if not user_id:

            failed += 1
            continue

        try:

            await decline_join_request(
                chat_id,
                user_id
            )

            await delete_request(
                chat_id,
                user_id
            )

            removed += 1

            await asyncio.sleep(
                0.08
            )

        except Exception as e:

            failed += 1

            logging.error(
                f"Remove failed | "
                f"{user_id} | {e}"
            )

    await msg.edit_text(
        "✅ **CLEANUP COMPLETED**\n\n"
        f"🗑 Removed: `{removed:,}`\n"
        f"❌ Failed: `{failed:,}`"
    )


# =========================================================
# /setad
# =========================================================

@app.on_message(
    filters.command("setad")
    & filters.private
)
async def set_ad_command(
    client,
    message
):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ **Owner only.**"
        )

    if len(message.command) < 2:

        return await message.reply_text(
            "📢 **Usage:**\n\n"
            "`/setad Your advertisement`"
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
    filters.command("delad")
    & filters.private
)
async def delete_ad_command(
    client,
    message
):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ **Owner only.**"
        )

    await delete_ad()

    await message.reply_text(
        "🗑 **Advertisement Deleted!**"
    )


# =========================================================
# /broadcast
# =========================================================

@app.on_message(
    filters.command("broadcast")
    & filters.private
)
async def broadcast_command(
    client,
    message
):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ **Owner only.**"
        )

    if not message.reply_to_message:

        return await message.reply_text(
            "📢 **Broadcast Usage**\n\n"
            "Kisi message ko reply karke:\n\n"
            "`/broadcast`\n\n"
            "send karo.\n\n"
            "✅ Text\n"
            "✅ Photo\n"
            "✅ Video\n"
            "✅ Voice\n"
            "✅ Audio\n"
            "✅ Document\n"
            "✅ Sticker\n"
            "✅ Animation"
        )

    status = await message.reply_text(
        "📢 **Broadcast Preparing...**"
    )

    await start_broadcast(
        client,
        message.reply_to_message,
        status
    )


# =========================================================
# /status
# =========================================================

@app.on_message(
    filters.command("status")
    & filters.private
)
async def status_command(
    client,
    message
):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ **Owner only.**"
        )

    try:

        total_users = await get_total_users()
        total_groups = await get_total_groups()

        await message.reply_text(
            "📊 **BOT STATISTICS**\n\n"
            f"👤 Total Users: `{total_users:,}`\n"
            f"👥 Total Groups: `{total_groups:,}`"
        )

    except Exception as e:

        logging.exception(
            f"Status error: {e}"
        )

        await message.reply_text(
            f"❌ **Status Error**\n\n"
            f"`{e}`"
        )


# =========================================================
# /groups
# =========================================================

@app.on_message(
    filters.command("groups")
    & filters.private
)
async def groups_command(
    client,
    message
):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ **Owner only.**"
        )

    try:

        groups = await get_all_groups()

        if not groups:

            return await message.reply_text(
                "ℹ️ **No groups found.**"
            )

        text = "👥 **BOT GROUPS**\n\n"

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
            f"❌ **Error**\n\n"
            f"`{e}`"
        )


# =========================================================
# /restart
# =========================================================

@app.on_message(
    filters.command("restart")
    & filters.private
)
async def restart_command(
    client,
    message
):

    if not message.from_user:
        return

    if message.from_user.id != OWNER_ID:

        return await message.reply_text(
            "❌ **Owner only.**"
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
    & filters.private
)
async def start_command(
    client,
    message
):

    if not message.from_user:
        return

    user = message.from_user

    try:

        await save_user(
            user.id
        )

        logging.info(
            f"👤 USER SAVED FROM START | "
            f"{user.id}"
        )

    except Exception as e:

        logging.error(
            f"Start user save failed: {e}"
        )

    await message.reply_text(
        "👋 **Hello!**\n\n"
        "🤖 **Join Request Manager Bot**\n\n"
        "I help group administrators manage "
        "join requests and automate approvals.\n\n"
        "✅ Join Request Management\n"
        "⚡ Auto Approval\n"
        "👥 Bulk Approval\n"
        "📢 Advertisement System\n\n"
        "✨ Your account has been registered."
    )


# =========================================================
# START
# =========================================================

print(
    "🤖 Join Request Manager Bot Started..."
)

app.run()
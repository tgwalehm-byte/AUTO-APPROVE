import asyncio
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait

from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID
from database import db


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s"
)

LOGGER = logging.getLogger("AUTO-APPROVE")


# ============================================================
# CLIENT
# ============================================================

app = Client(
    "auto_approve_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============================================================
# HELPERS
# ============================================================

def owner(user_id: int) -> bool:
    return user_id == OWNER_ID


async def is_admin(client, chat_id, user_id):
    if owner(user_id):
        return True

    try:
        member = await client.get_chat_member(
            chat_id,
            user_id
        )

        return member.status in (
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR
        )

    except Exception:
        return False


async def save_user(user):
    try:
        await db.save_user(user)
    except Exception as e:
        LOGGER.error("Save user error: %s", e)


async def save_chat(chat):
    try:
        await db.save_chat(chat)
    except Exception as e:
        LOGGER.error("Save chat error: %s", e)


# ============================================================
# ADVERTISEMENT
# ============================================================

async def send_ad(client, user_id):

    ad = await db.get_ad()

    if not ad:
        return

    try:

        # Text advertisement
        if ad.get("text"):

            await client.send_message(
                user_id,
                ad["text"]
            )

            return

        # Replied message advertisement
        if ad.get("chat_id") and ad.get("message_id"):

            await client.copy_message(
                chat_id=user_id,
                from_chat_id=ad["chat_id"],
                message_id=ad["message_id"]
            )

    except FloodWait as e:

        await asyncio.sleep(e.value)

        try:

            if ad.get("text"):

                await client.send_message(
                    user_id,
                    ad["text"]
                )

            elif ad.get("chat_id"):

                await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=ad["chat_id"],
                    message_id=ad["message_id"]
                )

        except Exception:
            pass

    except Exception as e:

        LOGGER.warning(
            "Could not send ad to %s: %s",
            user_id,
            e
        )


# ============================================================
# JOIN REQUEST
# ============================================================

@app.on_chat_join_request()
async def join_request(client, request: ChatJoinRequest):

    user = request.from_user
    chat = request.chat

    await save_user(user)
    await save_chat(chat)

    # ========================================================
    # CHANNEL
    # ========================================================

    if chat.type == enums.ChatType.CHANNEL:

        try:

            await client.approve_chat_join_request(
                chat.id,
                user.id
            )

            LOGGER.info(
                "CHANNEL APPROVED | %s | %s",
                user.id,
                chat.id
            )

            await send_ad(
                client,
                user.id
            )

        except FloodWait as e:

            await asyncio.sleep(e.value)

            try:

                await client.approve_chat_join_request(
                    chat.id,
                    user.id
                )

                await send_ad(
                    client,
                    user.id
                )

            except Exception as error:
                LOGGER.error(
                    "Channel retry error: %s",
                    error
                )

        except Exception as e:

            LOGGER.error(
                "Channel approval error: %s",
                e
            )

        return

    # ========================================================
    # GROUP
    # ========================================================

    if chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP
    ):
        return

    # IMPORTANT:
    # Group approval is OFF by default.

    enabled = await db.is_group_approval_enabled(
        chat.id
    )

    if not enabled:

        LOGGER.info(
            "GROUP REQUEST PENDING | APPROVAL OFF | %s",
            chat.id
        )

        return

    # ========================================================
    # AUTO APPROVE GROUP
    # ========================================================

    try:

        await client.approve_chat_join_request(
            chat.id,
            user.id
        )

        LOGGER.info(
            "GROUP APPROVED | %s | %s",
            user.id,
            chat.id
        )

        await send_ad(
            client,
            user.id
        )

    except FloodWait as e:

        await asyncio.sleep(e.value)

        try:

            await client.approve_chat_join_request(
                chat.id,
                user.id
            )

            await send_ad(
                client,
                user.id
            )

        except Exception as error:

            LOGGER.error(
                "Group retry error: %s",
                error
            )

    except Exception as e:

        LOGGER.error(
            "Group approval error: %s",
            e
        )


# ============================================================
# START
# ============================================================

@app.on_message(
    filters.command("start") & filters.private
)
async def start_command(client, message):

    await save_user(
        message.from_user
    )

    await message.reply_text(
        "👋 Welcome!\n\n"
        "✅ You are registered successfully."
    )


# ============================================================
# SET AD
# ============================================================

@app.on_message(
    filters.command("setad") & filters.private
)
async def setad_command(client, message):

    if not owner(message.from_user.id):
        return

    # --------------------------------------------------------
    # /setad hello
    # --------------------------------------------------------

    text = message.text.split(
        " ",
        1
    )

    if len(text) > 1 and text[1].strip():

        ad_text = text[1].strip()

        await db.set_ad_text(
            ad_text
        )

        await message.reply_text(
            "✅ Advertisement saved.\n\n"
            f"📝 {ad_text}"
        )

        return

    # --------------------------------------------------------
    # Reply + /setad
    # --------------------------------------------------------

    if message.reply_to_message:

        replied = message.reply_to_message

        await db.set_ad(
            replied.chat.id,
            replied.id
        )

        await message.reply_text(
            "✅ Advertisement message saved."
        )

        return

    # --------------------------------------------------------
    # No text / no reply
    # --------------------------------------------------------

    await message.reply_text(
        "❌ Use:\n\n"
        "/setad Your advertisement\n\n"
        "OR reply to any message and send:\n"
        "/setad"
    )


# ============================================================
# DELETE AD
# ============================================================

@app.on_message(
    filters.command("delad") & filters.private
)
async def delad_command(client, message):

    if not owner(message.from_user.id):
        return

    await db.delete_ad()

    await message.reply_text(
        "🗑 Advertisement deleted successfully."
    )


# ============================================================
# APPROVE COMMAND
# ============================================================

@app.on_message(
    filters.command("approve")
)
async def approve_command(client, message):

    if not message.chat:
        return

    # --------------------------------------------------------
    # This command works in GROUP only.
    # --------------------------------------------------------

    if message.chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP
    ):

        if (
            message.from_user
            and owner(message.from_user.id)
        ):

            await message.reply_text(
                "📢 Channel requests are always "
                "approved automatically."
            )

        return

    # --------------------------------------------------------
    # Admin check
    # --------------------------------------------------------

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id
    ):
        return

    args = message.text.split()

    # /approve
    if len(args) == 1:

        await message.reply_text(
            "⚙️ APPROVE SETTINGS\n\n"
            "/approve on - Auto approve ON\n"
            "/approve off - Auto approve OFF\n"
            "/approve 10 - Approve 10 pending\n"
            "/approve 20 - Approve 20 pending\n"
            "/approve 50 - Approve 50 pending"
        )

        return

    option = args[1].lower()

    # --------------------------------------------------------
    # ON
    # --------------------------------------------------------

    if option == "on":

        await db.set_group_approval(
            message.chat.id,
            True
        )

        await message.reply_text(
            "✅ AUTO APPROVE: ON\n\n"
            "New join requests will now be "
            "approved automatically."
        )

        return

    # --------------------------------------------------------
    # OFF
    # --------------------------------------------------------

    if option == "off":

        await db.set_group_approval(
            message.chat.id,
            False
        )

        await message.reply_text(
            "🛑 AUTO APPROVE: OFF\n\n"
            "New join requests will remain pending."
        )

        return

    # --------------------------------------------------------
    # NUMBER
    # --------------------------------------------------------

    if option.isdigit():

        amount = int(option)

        if amount <= 0:

            await message.reply_text(
                "❌ Invalid number."
            )

            return

        # Maximum 1000 per command
        amount = min(
            amount,
            1000
        )

        await approve_pending(
            client,
            message.chat.id,
            amount,
            message
        )

        return

    await message.reply_text(
        "❌ Invalid command.\n\n"
        "Use /approve on\n"
        "/approve off\n"
        "/approve 10"
    )


# ============================================================
# STOP APPROVAL
# ============================================================

@app.on_message(
    filters.command("stopapprov")
)
async def stopapprov_command(client, message):

    if message.chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP
    ):
        return

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id
    ):
        return

    await db.set_group_approval(
        message.chat.id,
        False
    )

    await message.reply_text(
        "🛑 AUTO APPROVE STOPPED\n\n"
        "New requests will remain pending."
    )


# ============================================================
# APPROVE PENDING
# ============================================================

async def approve_pending(
    client,
    chat_id,
    amount,
    message
):

    approved = 0
    failed = 0

    try:

        async for request in client.get_chat_join_requests(
            chat_id,
            limit=amount
        ):

            user = request.from_user

            await save_user(user)

            try:

                await client.approve_chat_join_request(
                    chat_id,
                    user.id
                )

                approved += 1

                await send_ad(
                    client,
                    user.id
                )

            except FloodWait as e:

                await asyncio.sleep(
                    e.value
                )

                try:

                    await client.approve_chat_join_request(
                        chat_id,
                        user.id
                    )

                    approved += 1

                    await send_ad(
                        client,
                        user.id
                    )

                except Exception:
                    failed += 1

            except Exception:
                failed += 1

    except Exception as e:

        await message.reply_text(
            "❌ Pending request error:\n\n"
            f"{e}"
        )

        return

    await message.reply_text(
        "✅ PENDING APPROVAL COMPLETE\n\n"
        f"✅ Approved: {approved}\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# REMOVE
# ============================================================

@app.on_message(
    filters.command("remove")
)
async def remove_command(client, message):

    if message.chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP
    ):
        return

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id
    ):
        return

    args = message.text.split()

    if len(args) < 2:

        await message.reply_text(
            "Use:\n\n"
            "/remove pending\n"
            "/remove ban\n"
            "/remove delete"
        )

        return

    mode = args[1].lower()

    if mode not in (
        "pending",
        "ban",
        "delete"
    ):

        await message.reply_text(
            "❌ Invalid option."
        )

        return

    removed = 0

    try:

        async for request in client.get_chat_join_requests(
            message.chat.id,
            limit=1000
        ):

            user_id = request.from_user.id

            try:

                # Remove pending request
                await client.decline_chat_join_request(
                    message.chat.id,
                    user_id
                )

                # Ban if requested
                if mode in (
                    "ban",
                    "delete"
                ):

                    try:

                        await client.ban_chat_member(
                            message.chat.id,
                            user_id
                        )

                    except Exception:
                        pass

                removed += 1

            except Exception:
                pass

    except Exception as e:

        await message.reply_text(
            f"❌ Error:\n{e}"
        )

        return

    await message.reply_text(
        f"✅ Removed: {removed}"
    )


# ============================================================
# STATUS
# ============================================================

@app.on_message(
    filters.command("status") & filters.private
)
async def status_command(client, message):

    if not owner(message.from_user.id):
        return

    users = await db.count_users()
    groups = await db.count_groups()
    channels = await db.count_channels()

    ad = await db.has_ad()

    await message.reply_text(
        "📊 BOT STATUS\n\n"
        f"👤 Total Users: {users}\n"
        f"👥 Total Groups: {groups}\n"
        f"📢 Total Channels: {channels}\n\n"
        f"📣 Advertisement: "
        f"{'SET ✅' if ad else 'NOT SET ❌'}"
    )


# ============================================================
# BROADCAST
# ============================================================

@app.on_message(
    filters.command("broadcast") & filters.private
)
async def broadcast_command(client, message):

    if not owner(message.from_user.id):
        return

    # --------------------------------------------------------
    # /broadcast Hello
    # --------------------------------------------------------

    parts = message.text.split(
        " ",
        1
    )

    broadcast_text = None

    if len(parts) > 1:
        broadcast_text = parts[1].strip()

    # --------------------------------------------------------
    # /broadcast as reply
    # --------------------------------------------------------

    source = message.reply_to_message

    if not source and not broadcast_text:

        await message.reply_text(
            "❌ Use:\n\n"
            "/broadcast Your message\n\n"
            "OR reply to a message and send:\n"
            "/broadcast"
        )

        return

    users = await db.get_user_ids()
    groups = await db.get_group_ids()

    total_users = len(users)
    total_groups = len(groups)

    sent_users = 0
    sent_groups = 0
    failed = 0

    # ========================================================
    # USERS
    # ========================================================

    for user_id in users:

        try:

            if broadcast_text:

                await client.send_message(
                    user_id,
                    broadcast_text
                )

            else:

                await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=source.chat.id,
                    message_id=source.id
                )

            sent_users += 1

            await asyncio.sleep(0.05)

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                if broadcast_text:

                    await client.send_message(
                        user_id,
                        broadcast_text
                    )

                else:

                    await client.copy_message(
                        chat_id=user_id,
                        from_chat_id=source.chat.id,
                        message_id=source.id
                    )

                sent_users += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

    # ========================================================
    # GROUPS
    # ========================================================

    for group_id in groups:

        try:

            if broadcast_text:

                await client.send_message(
                    group_id,
                    broadcast_text
                )

            else:

                await client.copy_message(
                    chat_id=group_id,
                    from_chat_id=source.chat.id,
                    message_id=source.id
                )

            sent_groups += 1

            await asyncio.sleep(0.05)

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                if broadcast_text:

                    await client.send_message(
                        group_id,
                        broadcast_text
                    )

                else:

                    await client.copy_message(
                        chat_id=group_id,
                        from_chat_id=source.chat.id,
                        message_id=source.id
                    )

                sent_groups += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

    # ========================================================
    # RESULT
    # ========================================================

    await message.reply_text(
        "📣 BROADCAST COMPLETED\n\n"
        f"👤 Users: {total_users}\n"
        f"✅ Users Sent: {sent_users}\n\n"
        f"👥 Groups: {total_groups}\n"
        f"✅ Groups Sent: {sent_groups}\n\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# BOT ADDED TO GROUP
# ============================================================

@app.on_message(
    filters.new_chat_members
)
async def bot_added(client, message):

    try:

        me = await client.get_me()

        for member in message.new_chat_members:

            if member.id != me.id:
                continue

            await save_chat(
                message.chat
            )

            # ------------------------------------------------
            # GROUP DEFAULT OFF
            # ------------------------------------------------

            if message.chat.type in (
                enums.ChatType.GROUP,
                enums.ChatType.SUPERGROUP
            ):

                await db.set_group_approval(
                    message.chat.id,
                    False
                )

                await message.reply_text(
                    "🤖 AUTO APPROVE BOT\n\n"
                    "🔴 Group Auto Approval: OFF\n\n"
                    "Enable with:\n"
                    "/approve on\n\n"
                    "Disable with:\n"
                    "/approve off\n\n"
                    "📢 Channel requests are "
                    "approved automatically."
                )

    except Exception as e:

        LOGGER.error(
            "Bot added error: %s",
            e
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    LOGGER.info(
        "AUTO APPROVE BOT STARTING..."
    )

    app.run()
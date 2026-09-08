import asyncio
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import ChatJoinRequest
from pyrogram.errors import FloodWait, RPCError

from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID
from database import db


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
)

LOGGER = logging.getLogger("AutoJoinBot")


# =========================================================
# BOT
# =========================================================

app = Client(
    "auto_join_request_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


# =========================================================
# OWNER CHECK
# =========================================================

def is_owner(user_id):
    return user_id == OWNER_ID


async def is_admin(client, chat_id, user_id):
    if is_owner(user_id):
        return True

    try:
        member = await client.get_chat_member(
            chat_id,
            user_id,
        )

        return member.status in (
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
        )

    except Exception:
        return False


# =========================================================
# SAVE USER
# =========================================================

async def save_request_user(user):
    try:
        await db.save_user(user)
    except Exception as e:
        LOGGER.error(
            "Could not save user %s: %s",
            user.id,
            e,
        )


# =========================================================
# SEND ADVERTISEMENT
# =========================================================

async def send_ad(client, user_id):
    ad = await db.get_ad()

    if not ad:
        return False

    try:
        await client.copy_message(
            chat_id=user_id,
            from_chat_id=ad["chat_id"],
            message_id=ad["message_id"],
        )

        return True

    except FloodWait as e:
        await asyncio.sleep(e.value)

        try:
            await client.copy_message(
                chat_id=user_id,
                from_chat_id=ad["chat_id"],
                message_id=ad["message_id"],
            )

            return True

        except Exception:
            return False

    except Exception as e:
        LOGGER.warning(
            "Advertisement could not be sent to %s: %s",
            user_id,
            e,
        )

        return False


# =========================================================
# JOIN REQUEST HANDLER
# =========================================================

@app.on_chat_join_request()
async def join_request(client, request: ChatJoinRequest):

    user = request.from_user
    chat = request.chat

    # -----------------------------------------------------
    # Save user
    # -----------------------------------------------------

    await save_request_user(user)

    # -----------------------------------------------------
    # Save chat
    # -----------------------------------------------------

    try:
        await db.save_chat(chat)
    except Exception as e:
        LOGGER.warning(
            "Could not save chat %s: %s",
            chat.id,
            e,
        )

    # =====================================================
    # CHANNEL
    # =====================================================

    if chat.type == enums.ChatType.CHANNEL:

        try:

            await client.approve_chat_join_request(
                chat.id,
                user.id,
            )

            LOGGER.info(
                "Channel request approved: %s -> %s",
                user.id,
                chat.id,
            )

            # Try sending advertisement.
            await send_ad(
                client,
                user.id,
            )

        except FloodWait as e:

            await asyncio.sleep(e.value)

            try:
                await client.approve_chat_join_request(
                    chat.id,
                    user.id,
                )

                await send_ad(
                    client,
                    user.id,
                )

            except Exception as error:
                LOGGER.warning(
                    "Channel approval retry failed: %s",
                    error,
                )

        except Exception as e:

            LOGGER.warning(
                "Channel approval failed: %s",
                e,
            )

        return

    # =====================================================
    # GROUP / SUPERGROUP
    # =====================================================

    if chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ):
        return

    # -----------------------------------------------------
    # IMPORTANT
    #
    # GROUP AUTO APPROVAL IS OFF BY DEFAULT.
    # -----------------------------------------------------

    enabled = await db.is_group_approval_enabled(
        chat.id
    )

    if not enabled:

        LOGGER.info(
            "Group request left pending because approval is OFF: %s",
            chat.id,
        )

        return

    # -----------------------------------------------------
    # APPROVE GROUP REQUEST
    # -----------------------------------------------------

    try:

        await client.approve_chat_join_request(
            chat.id,
            user.id,
        )

        LOGGER.info(
            "Group request approved: %s -> %s",
            user.id,
            chat.id,
        )

        await send_ad(
            client,
            user.id,
        )

    except FloodWait as e:

        await asyncio.sleep(e.value)

        try:

            await client.approve_chat_join_request(
                chat.id,
                user.id,
            )

            await send_ad(
                client,
                user.id,
            )

        except Exception as error:

            LOGGER.warning(
                "Group approval retry failed: %s",
                error,
            )

    except Exception as e:

        LOGGER.warning(
            "Group approval failed: %s",
            e,
        )


# =========================================================
# START
# =========================================================

@app.on_message(
    filters.command("start")
    & filters.private
)
async def start_command(client, message):

    await save_request_user(
        message.from_user
    )

    await message.reply_text(
        "👋 Welcome!\n\n"
        "You are now registered with the bot."
    )


# =========================================================
# SET AD
# =========================================================

@app.on_message(
    filters.command("setad")
    & filters.private
)
async def set_ad_command(client, message):

    if not is_owner(message.from_user.id):
        return

    if not message.reply_to_message:

        await message.reply_text(
            "❌ Reply to the advertisement message "
            "and use /setad"
        )

        return

    replied = message.reply_to_message

    await db.set_ad(
        replied.chat.id,
        replied.id,
    )

    await message.reply_text(
        "✅ Advertisement saved successfully."
    )


# =========================================================
# DELETE AD
# =========================================================

@app.on_message(
    filters.command("delad")
    & filters.private
)
async def delete_ad_command(client, message):

    if not is_owner(message.from_user.id):
        return

    await db.delete_ad()

    await message.reply_text(
        "🗑 Advertisement deleted."
    )


# =========================================================
# APPROVE COMMAND
# =========================================================

@app.on_message(
    filters.command("approve")
)
async def approve_command(client, message):

    # -----------------------------------------------------
    # Only groups
    # -----------------------------------------------------

    if message.chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ):

        if message.from_user and is_owner(
            message.from_user.id
        ):

            await message.reply_text(
                "📢 Channel join requests are "
                "already approved automatically."
            )

        return

    # -----------------------------------------------------
    # Admin check
    # -----------------------------------------------------

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id,
    ):
        return

    args = message.text.split()

    if len(args) < 2:

        await message.reply_text(
            "Use:\n\n"
            "/approve on\n"
            "/approve off\n"
            "/approve 10\n"
            "/approve 20\n"
            "/approve 50"
        )

        return

    option = args[1].lower()

    # =====================================================
    # ON
    # =====================================================

    if option == "on":

        await db.set_group_approval(
            message.chat.id,
            True,
        )

        await message.reply_text(
            "✅ Group auto approval is ON.\n\n"
            "New join requests will now be "
            "approved automatically."
        )

        return

    # =====================================================
    # OFF
    # =====================================================

    if option == "off":

        await db.set_group_approval(
            message.chat.id,
            False,
        )

        await message.reply_text(
            "🛑 Group auto approval is OFF.\n\n"
            "New join requests will remain pending."
        )

        return

    # =====================================================
    # PENDING BATCH
    # =====================================================

    if option.isdigit():

        amount = int(option)

        if amount <= 0:

            await message.reply_text(
                "❌ Invalid number."
            )

            return

        amount = min(amount, 1000)

        # Enable approval for this group.
        await db.set_group_approval(
            message.chat.id,
            True,
        )

        await approve_pending(
            client,
            message.chat.id,
            amount,
            message,
        )

        return

    await message.reply_text(
        "❌ Invalid option."
    )


# =========================================================
# STOP APPROVAL
# =========================================================

@app.on_message(
    filters.command("stopapprov")
)
async def stop_approval_command(
    client,
    message,
):

    if message.chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ):
        return

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id,
    ):
        return

    await db.set_group_approval(
        message.chat.id,
        False,
    )

    await message.reply_text(
        "🛑 Auto approval stopped.\n\n"
        "Pending requests will remain pending."
    )


# =========================================================
# APPROVE PENDING REQUESTS
# =========================================================

async def approve_pending(
    client,
    chat_id,
    amount,
    message,
):

    approved = 0
    failed = 0

    try:

        async for request in client.get_chat_join_requests(
            chat_id,
            limit=amount,
        ):

            user = request.from_user

            await save_request_user(
                user
            )

            try:

                await client.approve_chat_join_request(
                    chat_id,
                    user.id,
                )

                approved += 1

                await send_ad(
                    client,
                    user.id,
                )

            except FloodWait as e:

                await asyncio.sleep(
                    e.value
                )

                try:

                    await client.approve_chat_join_request(
                        chat_id,
                        user.id,
                    )

                    approved += 1

                    await send_ad(
                        client,
                        user.id,
                    )

                except Exception:
                    failed += 1

            except Exception:
                failed += 1

    except Exception as e:

        await message.reply_text(
            f"❌ Could not read pending requests.\n\n{e}"
        )

        return

    await message.reply_text(
        "✅ Pending approval completed.\n\n"
        f"Approved: {approved}\n"
        f"Failed: {failed}"
    )


# =========================================================
# REMOVE PENDING
# =========================================================

@app.on_message(
    filters.command("remove")
)
async def remove_command(
    client,
    message,
):

    if message.chat.type not in (
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ):
        return

    if not message.from_user:
        return

    if not await is_admin(
        client,
        message.chat.id,
        message.from_user.id,
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
        "delete",
    ):

        await message.reply_text(
            "❌ Invalid option."
        )

        return

    removed = 0

    try:

        async for request in client.get_chat_join_requests(
            message.chat.id,
            limit=1000,
        ):

            user_id = request.from_user.id

            try:

                # Remove request from pending.
                await client.decline_chat_join_request(
                    message.chat.id,
                    user_id,
                )

                # ban/delete mode:
                # Telegram does not allow a bot to
                # delete a user's Telegram account.
                if mode in ("ban", "delete"):

                    try:

                        await client.ban_chat_member(
                            message.chat.id,
                            user_id,
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


# =========================================================
# STATUS
# =========================================================

@app.on_message(
    filters.command("status")
    & filters.private
)
async def status_command(
    client,
    message,
):

    if not is_owner(message.from_user.id):
        return

    users = await db.count_users()
    groups = await db.count_groups()
    channels = await db.count_channels()

    ad_status = await db.has_ad()

    await message.reply_text(
        "📊 BOT STATUS\n\n"
        f"👤 Total Users: {users}\n"
        f"👥 Total Groups: {groups}\n"
        f"📢 Total Channels: {channels}\n\n"
        f"📣 Advertisement: "
        f"{'SET ✅' if ad_status else 'NOT SET ❌'}"
    )


# =========================================================
# BROADCAST
# =========================================================

@app.on_message(
    filters.command("broadcast")
    & filters.private
)
async def broadcast_command(
    client,
    message,
):

    if not is_owner(message.from_user.id):
        return

    if not message.reply_to_message:

        await message.reply_text(
            "❌ Reply to the message you want "
            "to broadcast and use /broadcast"
        )

        return

    source = message.reply_to_message

    user_ids = await db.get_user_ids()
    group_ids = await db.get_group_ids()

    total_users = len(user_ids)
    total_groups = len(group_ids)

    sent = 0
    failed = 0

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    for user_id in user_ids:

        try:

            await client.copy_message(
                chat_id=user_id,
                from_chat_id=source.chat.id,
                message_id=source.id,
            )

            sent += 1

            await asyncio.sleep(0.05)

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=source.chat.id,
                    message_id=source.id,
                )

                sent += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

    # -----------------------------------------------------
    # GROUPS
    # -----------------------------------------------------

    for group_id in group_ids:

        try:

            await client.copy_message(
                chat_id=group_id,
                from_chat_id=source.chat.id,
                message_id=source.id,
            )

            sent += 1

            await asyncio.sleep(0.05)

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await client.copy_message(
                    chat_id=group_id,
                    from_chat_id=source.chat.id,
                    message_id=source.id,
                )

                sent += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

    await message.reply_text(
        "📣 BROADCAST COMPLETED\n\n"
        f"👤 Users: {total_users}\n"
        f"👥 Groups: {total_groups}\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )


# =========================================================
# BOT ADDED TO GROUP
# =========================================================

@app.on_message(
    filters.new_chat_members
)
async def bot_added(
    client,
    message,
):

    try:

        me = await client.get_me()

        for member in message.new_chat_members:

            if member.id != me.id:
                continue

            await db.save_chat(
                message.chat
            )

            # Group is OFF by default.
            if message.chat.type in (
                enums.ChatType.GROUP,
                enums.ChatType.SUPERGROUP,
            ):

                await db.set_group_approval(
                    message.chat.id,
                    False,
                )

                await message.reply_text(
                    "🤖 Bot added successfully.\n\n"
                    "🔴 Group auto approval is OFF.\n\n"
                    "Use:\n"
                    "/approve on\n\n"
                    "to enable auto approval.\n\n"
                    "📢 Channel join requests are "
                    "approved automatically."
                )

    except Exception as e:

        LOGGER.warning(
            "Bot added handler error: %s",
            e,
        )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    LOGGER.info(
        "Auto Join Request Bot starting..."
    )

    app.run()
import asyncio
import logging

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError, RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    ChatJoinRequestHandler,
    ContextTypes,
)

from config import BOT_TOKEN, OWNER_ID
from database import db


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="[%(asctime)s] %(levelname)s - %(message)s",
    level=logging.INFO,
)

LOGGER = logging.getLogger("AUTO-APPROVE")


# ============================================================
# OWNER
# ============================================================

def is_owner(user_id):
    return user_id == OWNER_ID


# ============================================================
# ADMIN CHECK
# ============================================================

async def is_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    if is_owner(user.id):
        return True

    try:

        member = await context.bot.get_chat_member(
            chat.id,
            user.id
        )

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception:
        return False


# ============================================================
# SAVE USER
# ============================================================

async def save_user(user):

    if not user:
        return

    await db.save_user(
        user.id,
        user.username,
        user.first_name,
        user.last_name
    )


# ============================================================
# SEND AD
# ============================================================

async def send_saved_ad(
    context,
    chat_id
):

    ad = await db.get_ad()

    if not ad:
        return

    try:

        ad_type = ad.get("type")

        # ----------------------------------------------------
        # TEXT
        # ----------------------------------------------------

        if ad_type == "text":

            await context.bot.send_message(
                chat_id=chat_id,
                text=ad["text"],
                parse_mode="HTML",
                disable_web_page_preview=False
            )

        # ----------------------------------------------------
        # COPIED MESSAGE
        # ----------------------------------------------------

        elif ad_type == "copy":

            await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=ad["from_chat_id"],
                message_id=ad["message_id"]
            )

    except RetryAfter as e:

        await asyncio.sleep(
            e.retry_after
        )

        try:

            if ad.get("type") == "text":

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=ad["text"],
                    parse_mode="HTML"
                )

            elif ad.get("type") == "copy":

                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=ad["from_chat_id"],
                    message_id=ad["message_id"]
                )

        except Exception:
            pass

    except TelegramError as e:

        LOGGER.warning(
            "Advertisement DM failed for %s: %s",
            chat_id,
            e
        )

    except Exception as e:

        LOGGER.warning(
            "Advertisement error: %s",
            e
        )


# ============================================================
# JOIN REQUEST
# ============================================================

async def join_request_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    request = update.chat_join_request

    if not request:
        return

    user = request.from_user
    chat = request.chat

    await save_user(user)

    # ========================================================
    # CHANNEL
    # ========================================================

    if chat.type == ChatType.CHANNEL:

        # ----------------------------------------------------
        # Save channel
        # ----------------------------------------------------

        await db.save_group(
            chat.id,
            chat.title,
            chat.username
        )

        # ----------------------------------------------------
        # DM FIRST
        # ----------------------------------------------------

        try:

            await context.bot.send_message(
                chat_id=request.user_chat_id,
                text=(
                    "👋 Hello!\n\n"
                    "Your join request has been received "
                    "successfully. ❤️"
                )
            )

        except Exception as e:

            LOGGER.info(
                "Channel DM failed for %s: %s",
                user.id,
                e
            )

        # ----------------------------------------------------
        # OWNER AD
        # ----------------------------------------------------

        await send_saved_ad(
            context,
            request.user_chat_id
        )

        # ----------------------------------------------------
        # INSTANT APPROVE
        # ----------------------------------------------------

        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user.id
            )

            LOGGER.info(
                "CHANNEL APPROVED: %s",
                user.id
            )

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                await context.bot.approve_chat_join_request(
                    chat_id=chat.id,
                    user_id=user.id
                )

            except Exception as error:

                LOGGER.error(
                    "Channel approval retry error: %s",
                    error
                )

        except Exception as e:

            LOGGER.error(
                "Channel approval error: %s",
                e
            )

        return

    # ========================================================
    # GROUP / SUPERGROUP
    # ========================================================

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    # --------------------------------------------------------
    # Save group
    # --------------------------------------------------------

    await db.save_group(
        chat.id,
        chat.title,
        chat.username
    )

    # --------------------------------------------------------
    # SAVE PENDING REQUEST
    # --------------------------------------------------------

    await db.save_pending(
        chat.id,
        user.id,
        request.user_chat_id
    )

    # --------------------------------------------------------
    # DM USER
    # --------------------------------------------------------

    try:

        await context.bot.send_message(
            chat_id=request.user_chat_id,
            text=(
                "👋 Hello!\n\n"
                "Your join request has been received. ❤️\n"
                "Please wait for approval."
            )
        )

    except Exception as e:

        LOGGER.info(
            "Group DM failed for %s: %s",
            user.id,
            e
        )

    # --------------------------------------------------------
    # OWNER AD
    # --------------------------------------------------------

    await send_saved_ad(
        context,
        request.user_chat_id
    )

    # --------------------------------------------------------
    # CHECK AUTO APPROVAL
    # --------------------------------------------------------

    enabled = await db.approval_enabled(
        chat.id
    )

    if not enabled:

        LOGGER.info(
            "GROUP REQUEST PENDING: %s",
            user.id
        )

        return

    # --------------------------------------------------------
    # INSTANT APPROVAL
    # --------------------------------------------------------

    try:

        await context.bot.approve_chat_join_request(
            chat_id=chat.id,
            user_id=user.id
        )

        await db.remove_pending(
            chat.id,
            user.id
        )

        LOGGER.info(
            "GROUP APPROVED: %s",
            user.id
        )

    except RetryAfter as e:

        await asyncio.sleep(
            e.retry_after
        )

        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user.id
            )

            await db.remove_pending(
                chat.id,
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

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    await save_user(user)

    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "✅ You are registered successfully."
    )


# ============================================================
# SET AD
# ============================================================

async def setad_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or not is_owner(user.id):
        return

    # --------------------------------------------------------
    # /setad TEXT
    # --------------------------------------------------------

    if context.args:

        text = " ".join(
            context.args
        ).strip()

        await db.set_ad({
            "type": "text",
            "text": text
        })

        await update.message.reply_text(
            "✅ Advertisement saved."
        )

        return

    # --------------------------------------------------------
    # REPLY MESSAGE + /setad
    # --------------------------------------------------------

    if update.message.reply_to_message:

        replied = update.message.reply_to_message

        await db.set_ad({
            "type": "copy",
            "from_chat_id": replied.chat.id,
            "message_id": replied.message_id
        })

        await update.message.reply_text(
            "✅ Advertisement message saved."
        )

        return

    await update.message.reply_text(
        "❌ Use:\n\n"
        "/setad Your advertisement\n\n"
        "OR reply to a message and use:\n"
        "/setad"
    )


# ============================================================
# DELETE AD
# ============================================================

async def delad_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or not is_owner(user.id):
        return

    await db.delete_ad()

    await update.message.reply_text(
        "🗑 Advertisement deleted."
    )


# ============================================================
# APPROVE
# ============================================================

async def approve_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    if not await is_admin(
        update,
        context
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "⚙️ APPROVE\n\n"
            "/approve on\n"
            "/approve off\n"
            "/approve 10\n"
            "/approve 20\n"
            "/approve 50\n"
            "/approve 100"
        )

        return

    option = context.args[0].lower()

    # ========================================================
    # ON
    # ========================================================

    if option == "on":

        await db.set_approval(
            chat.id,
            True
        )

        await update.message.reply_text(
            "✅ AUTO APPROVE ON\n\n"
            "New join requests will be "
            "approved instantly."
        )

        return

    # ========================================================
    # OFF
    # ========================================================

    if option == "off":

        await db.set_approval(
            chat.id,
            False
        )

        await update.message.reply_text(
            "🛑 AUTO APPROVE OFF\n\n"
            "New join requests will remain pending."
        )

        return

    # ========================================================
    # NUMBER
    # ========================================================

    if option.isdigit():

        amount = int(option)

        if amount <= 0:
            return

        # Safety limit
        amount = min(
            amount,
            100000
        )

        await approve_pending(
            update,
            context,
            amount
        )

        return

    await update.message.reply_text(
        "❌ Invalid command."
    )


# ============================================================
# APPROVE PENDING
# ============================================================

async def approve_pending(
    update,
    context,
    amount
):

    chat_id = update.effective_chat.id

    requests = await db.get_pending(
        chat_id,
        amount
    )

    if not requests:

        await update.message.reply_text(
            "ℹ️ No tracked pending requests found."
        )

        return

    approved = 0
    failed = 0

    for request in requests:

        user_id = request["user_id"]

        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat_id,
                user_id=user_id
            )

            await db.remove_pending(
                chat_id,
                user_id
            )

            approved += 1

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                await context.bot.approve_chat_join_request(
                    chat_id=chat_id,
                    user_id=user_id
                )

                await db.remove_pending(
                    chat_id,
                    user_id
                )

                approved += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

        await asyncio.sleep(
            0.05
        )

    await update.message.reply_text(
        "✅ PENDING APPROVAL COMPLETE\n\n"
        f"✅ Approved: {approved}\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# STOP
# ============================================================

async def stop_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    if not await is_admin(
        update,
        context
    ):
        return

    await db.set_approval(
        chat.id,
        False
    )

    await update.message.reply_text(
        "🛑 APPROVING STOPPED\n\n"
        "New join requests will remain pending."
    )


# ============================================================
# REMOVE
# ============================================================

async def remove_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    if not await is_admin(
        update,
        context
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Use:\n\n"
            "/remove ban\n"
            "/remove delete\n"
            "/remove frozen"
        )

        return

    mode = context.args[0].lower()

    if mode not in (
        "ban",
        "delete",
        "frozen"
    ):

        await update.message.reply_text(
            "❌ Invalid option."
        )

        return

    requests = await db.get_pending(
        chat.id,
        100000
    )

    removed = 0

    for request in requests:

        user_id = request["user_id"]

        try:

            # Remove join request
            await context.bot.decline_chat_join_request(
                chat_id=chat.id,
                user_id=user_id
            )

            # Ban
            if mode in (
                "ban",
                "delete"
            ):

                try:

                    await context.bot.ban_chat_member(
                        chat_id=chat.id,
                        user_id=user_id
                    )

                except Exception:
                    pass

            # Restrict/freeze
            elif mode == "frozen":

                try:

                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=user_id,
                        permissions={
                            "can_send_messages": False
                        }
                    )

                except Exception:
                    pass

            await db.remove_pending(
                chat.id,
                user_id
            )

            removed += 1

        except Exception:
            pass

    await update.message.reply_text(
        f"✅ Removed: {removed}"
    )


# ============================================================
# STATUS
# ============================================================

async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or not is_owner(user.id):
        return

    total_users = await db.total_users()
    total_groups = await db.total_groups()

    await update.message.reply_text(
        "📊 BOT STATUS\n\n"
        f"👤 Total Users: {total_users}\n"
        f"👥 Total Groups: {total_groups}"
    )


# ============================================================
# BROADCAST
# ============================================================

async def broadcast_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user or not is_owner(user.id):
        return

    # --------------------------------------------------------
    # Get source message
    # --------------------------------------------------------

    source = update.message.reply_to_message

    # --------------------------------------------------------
    # Text broadcast
    # --------------------------------------------------------

    text = None

    if context.args:
        text = " ".join(
            context.args
        ).strip()

    if not source and not text:

        await update.message.reply_text(
            "❌ Use:\n\n"
            "/broadcast Your message\n\n"
            "OR reply to any message and use:\n"
            "/broadcast"
        )

        return

    users = await db.get_all_users()
    groups = await db.get_all_groups()

    sent_users = 0
    sent_groups = 0
    failed = 0

    # ========================================================
    # USERS
    # ========================================================

    for chat_id in users:

        try:

            if text:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML"
                )

            else:

                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source.chat.id,
                    message_id=source.message_id
                )

            sent_users += 1

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                if text:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML"
                    )

                else:

                    await context.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source.chat.id,
                        message_id=source.message_id
                    )

                sent_users += 1

            except Exception:
                failed += 1

        except Exception:

            failed += 1

        await asyncio.sleep(
            0.04
        )

    # ========================================================
    # GROUPS
    # ========================================================

    for chat_id in groups:

        try:

            if text:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML"
                )

            else:

                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source.chat.id,
                    message_id=source.message_id
                )

            sent_groups += 1

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                if text:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML"
                    )

                else:

                    await context.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source.chat.id,
                        message_id=source.message_id
                    )

                sent_groups += 1

            except Exception:
                failed += 1

        except Exception:

            failed += 1

        await asyncio.sleep(
            0.04
        )

    await update.message.reply_text(
        "📣 BROADCAST COMPLETE\n\n"
        f"👤 Total Users: {len(users)}\n"
        f"✅ Users Sent: {sent_users}\n\n"
        f"👥 Total Groups: {len(groups)}\n"
        f"✅ Groups Sent: {sent_groups}\n\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):

    LOGGER.error(
        "Telegram error: %s",
        context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    LOGGER.info(
        "Starting Auto Approve Bot..."
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Commands
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "setad",
            setad_command
        )
    )

    application.add_handler(
        CommandHandler(
            "delad",
            delad_command
        )
    )

    application.add_handler(
        CommandHandler(
            "approve",
            approve_command
        )
    )

    application.add_handler(
        CommandHandler(
            "stop",
            stop_command
        )
    )

    application.add_handler(
        CommandHandler(
            "remove",
            remove_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_command
        )
    )

    # --------------------------------------------------------
    # Join Request
    # --------------------------------------------------------

    application.add_handler(
        ChatJoinRequestHandler(
            join_request_handler
        )
    )

    # --------------------------------------------------------
    # Error
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    LOGGER.info(
        "BOT STARTED SUCCESSFULLY"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
import asyncio
import logging

from telegram import Update, BotCommand
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
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

LOGGER = logging.getLogger("AUTO_APPROVE")


# ============================================================
# OWNER
# ============================================================

def is_owner(user_id):
    return user_id == OWNER_ID


# ============================================================
# ADMIN CHECK
# ============================================================

async def check_admin(update, context):

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    if user.id == OWNER_ID:
        return True

    try:
        member = await context.bot.get_chat_member(
            chat_id=chat.id,
            user_id=user.id
        )

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception as e:
        LOGGER.error("Admin check error: %s", e)
        return False


# ============================================================
# SAVE USER
# ============================================================

async def save_user(user):

    if not user:
        return

    try:
        await db.save_user(
            user.id,
            user.username,
            user.first_name,
            user.last_name
        )
    except Exception as e:
        LOGGER.error("User save error: %s", e)


# ============================================================
# SAVE GROUP
# ============================================================

async def save_group(chat):

    if not chat:
        return

    try:
        await db.save_group(
            chat.id,
            chat.title,
            chat.username
        )
    except Exception as e:
        LOGGER.error("Group save error: %s", e)


# ============================================================
# SEND AD
# ============================================================

async def send_ad(context, user_chat_id):

    ad = await db.get_ad()

    if not ad:
        return

    try:

        # Text ad
        if ad.get("type") == "text":

            await context.bot.send_message(
                chat_id=user_chat_id,
                text=ad["text"],
                disable_web_page_preview=False
            )

        # Message ad
        elif ad.get("type") == "copy":

            await context.bot.copy_message(
                chat_id=user_chat_id,
                from_chat_id=ad["from_chat_id"],
                message_id=ad["message_id"]
            )

    except RetryAfter as e:

        await asyncio.sleep(e.retry_after)

        try:

            if ad.get("type") == "text":

                await context.bot.send_message(
                    chat_id=user_chat_id,
                    text=ad["text"]
                )

            else:

                await context.bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=ad["from_chat_id"],
                    message_id=ad["message_id"]
                )

        except Exception:
            pass

    except Exception as e:

        LOGGER.warning(
            "Ad DM failed for %s: %s",
            user_chat_id,
            e
        )


# ============================================================
# JOIN REQUEST
# ============================================================

async def join_request(update, context):

    request = update.chat_join_request

    if not request:
        return

    user = request.from_user
    chat = request.chat

    LOGGER.info(
        "JOIN REQUEST | user=%s | chat=%s | type=%s",
        user.id,
        chat.id,
        chat.type
    )

    # Save user
    await save_user(user)

    # ========================================================
    # CHANNEL
    # ========================================================

    if chat.type == ChatType.CHANNEL:

        await save_group(chat)

        # DM first
        try:

            await context.bot.send_message(
                chat_id=request.user_chat_id,
                text=(
                    "👋 Hello!\n\n"
                    "Your channel join request has been "
                    "received successfully. ❤️"
                )
            )

        except Exception as e:

            LOGGER.info(
                "Channel welcome DM failed: %s",
                e
            )

        # Owner advertisement
        await send_ad(
            context,
            request.user_chat_id
        )

        # Instant approve
        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user.id
            )

            LOGGER.info(
                "CHANNEL APPROVED | %s",
                user.id
            )

        except RetryAfter as e:

            await asyncio.sleep(e.retry_after)

            try:

                await context.bot.approve_chat_join_request(
                    chat_id=chat.id,
                    user_id=user.id
                )

            except Exception as error:

                LOGGER.error(
                    "Channel retry failed: %s",
                    error
                )

        except Exception as e:

            LOGGER.error(
                "Channel approval failed: %s",
                e
            )

        return

    # ========================================================
    # GROUP
    # ========================================================

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    await save_group(chat)

    # Save pending request
    try:

        await db.save_pending(
            chat.id,
            user.id,
            request.user_chat_id
        )

    except Exception as e:

        LOGGER.error(
            "Pending save error: %s",
            e
        )

    # --------------------------------------------------------
    # Welcome DM
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
            "Group DM failed: %s",
            e
        )

    # --------------------------------------------------------
    # Advertisement
    # --------------------------------------------------------

    await send_ad(
        context,
        request.user_chat_id
    )

    # --------------------------------------------------------
    # Check auto approval
    # --------------------------------------------------------

    enabled = await db.approval_enabled(
        chat.id
    )

    if not enabled:

        LOGGER.info(
            "GROUP REQUEST PENDING | %s",
            user.id
        )

        return

    # --------------------------------------------------------
    # Instant approve
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
            "GROUP APPROVED | %s",
            user.id
        )

    except RetryAfter as e:

        await asyncio.sleep(e.retry_after)

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
# /START
# ============================================================

async def start_command(update, context):

    await save_user(
        update.effective_user
    )

    await update.message.reply_text(
        "🤖 AUTO APPROVE BOT\n\n"
        "✅ Bot is working.\n\n"
        "Use /help to see commands."
    )


# ============================================================
# /HELP
# ============================================================

async def help_command(update, context):

    text = (
        "🤖 AUTO APPROVE BOT\n\n"

        "👥 GROUP COMMANDS\n"
        "/auto on - Auto approval ON\n"
        "/auto off - Auto approval OFF\n"
        "/pending 10 - Approve 10\n"
        "/pending 20 - Approve 20\n"
        "/pending 50 - Approve 50\n"
        "/pending 100 - Approve 100\n"
        "/pending 1000 - Approve 1000\n"
        "/stop - Stop auto approval\n"
        "/remove - Remove pending requests\n\n"

        "👑 OWNER COMMANDS\n"
        "/ad - Set advertisement\n"
        "/delad - Delete advertisement\n"
        "/bc - Broadcast\n"
        "/stats - Bot statistics"
    )

    await update.message.reply_text(text)


# ============================================================
# /AUTO
# ============================================================

async def auto_command(update, context):

    chat = update.effective_chat

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await update.message.reply_text(
            "❌ Use this command inside a group."
        )
        return

    if not await check_admin(
        update,
        context
    ):
        await update.message.reply_text(
            "❌ Only group admins can use this."
        )
        return

    if not context.args:

        await update.message.reply_text(
            "Use:\n\n"
            "/auto on\n"
            "/auto off"
        )
        return

    option = context.args[0].lower()

    if option == "on":

        await db.set_approval(
            chat.id,
            True
        )

        await update.message.reply_text(
            "✅ AUTO APPROVAL ON\n\n"
            "New join requests will be approved instantly."
        )

    elif option == "off":

        await db.set_approval(
            chat.id,
            False
        )

        await update.message.reply_text(
            "🛑 AUTO APPROVAL OFF\n\n"
            "New join requests will remain pending."
        )

    else:

        await update.message.reply_text(
            "❌ Use /auto on or /auto off"
        )


# ============================================================
# /PENDING
# ============================================================

async def pending_command(update, context):

    chat = update.effective_chat

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    if not await check_admin(
        update,
        context
    ):
        await update.message.reply_text(
            "❌ Only group admins can use this."
        )
        return

    if not context.args:

        await update.message.reply_text(
            "Example:\n\n"
            "/pending 10\n"
            "/pending 20\n"
            "/pending 50\n"
            "/pending 100"
        )
        return

    try:

        amount = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Enter a number."
        )
        return

    if amount <= 0:

        await update.message.reply_text(
            "❌ Number must be greater than 0."
        )
        return

    amount = min(
        amount,
        100000
    )

    requests = await db.get_pending(
        chat.id,
        amount
    )

    if not requests:

        await update.message.reply_text(
            "ℹ️ No tracked pending requests."
        )
        return

    await update.message.reply_text(
        f"⏳ Approving {len(requests)} requests..."
    )

    approved = 0
    failed = 0

    for item in requests:

        user_id = item["user_id"]

        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user_id
            )

            await db.remove_pending(
                chat.id,
                user_id
            )

            approved += 1

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                await context.bot.approve_chat_join_request(
                    chat_id=chat.id,
                    user_id=user_id
                )

                await db.remove_pending(
                    chat.id,
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
        "✅ DONE\n\n"
        f"✅ Approved: {approved}\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# /STOP
# ============================================================

async def stop_command(update, context):

    chat = update.effective_chat

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    if not await check_admin(
        update,
        context
    ):
        await update.message.reply_text(
            "❌ Only group admins can use this."
        )
        return

    await db.set_approval(
        chat.id,
        False
    )

    await update.message.reply_text(
        "🛑 AUTO APPROVAL STOPPED\n\n"
        "New requests will remain pending."
    )


# ============================================================
# /REMOVE
# ============================================================

async def remove_command(update, context):

    chat = update.effective_chat

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    if not await check_admin(
        update,
        context
    ):
        await update.message.reply_text(
            "❌ Only group admins can use this."
        )
        return

    requests = await db.get_pending(
        chat.id,
        100000
    )

    if not requests:

        await update.message.reply_text(
            "ℹ️ No tracked pending requests."
        )
        return

    removed = 0

    for item in requests:

        user_id = item["user_id"]

        try:

            await context.bot.decline_chat_join_request(
                chat_id=chat.id,
                user_id=user_id
            )

            await db.remove_pending(
                chat.id,
                user_id
            )

            removed += 1

        except Exception:
            pass

    await update.message.reply_text(
        f"🗑 Removed {removed} pending requests."
    )


# ============================================================
# /AD
# ============================================================

async def ad_command(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    # /ad TEXT
    if context.args:

        text = " ".join(
            context.args
        )

        await db.set_ad({
            "type": "text",
            "text": text
        })

        await update.message.reply_text(
            "✅ Advertisement saved."
        )

        return

    # Reply message + /ad
    if update.message.reply_to_message:

        message = update.message.reply_to_message

        await db.set_ad({
            "type": "copy",
            "from_chat_id": message.chat.id,
            "message_id": message.message_id
        })

        await update.message.reply_text(
            "✅ Advertisement message saved."
        )

        return

    await update.message.reply_text(
        "Use:\n\n"
        "/ad Your advertisement\n\n"
        "OR reply to a message/photo/video/button "
        "and send /ad"
    )


# ============================================================
# /DELAD
# ============================================================

async def delad_command(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    await db.delete_ad()

    await update.message.reply_text(
        "🗑 Advertisement deleted."
    )


# ============================================================
# /BC
# ============================================================

async def broadcast_command(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    source = update.message.reply_to_message

    text = None

    if context.args:

        text = " ".join(
            context.args
        )

    if not source and not text:

        await update.message.reply_text(
            "Use:\n\n"
            "/bc Your message\n\n"
            "OR reply to any message and send /bc"
        )

        return

    users = await db.get_all_users()
    groups = await db.get_all_groups()

    await update.message.reply_text(
        "📣 Broadcast started..."
    )

    user_sent = 0
    group_sent = 0
    failed = 0

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    for chat_id in users:

        try:

            if text:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text
                )

            else:

                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source.chat.id,
                    message_id=source.message_id
                )

            user_sent += 1

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                if text:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text
                    )

                else:

                    await context.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source.chat.id,
                        message_id=source.message_id
                    )

                user_sent += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

        await asyncio.sleep(
            0.05
        )

    # --------------------------------------------------------
    # GROUPS
    # --------------------------------------------------------

    for chat_id in groups:

        try:

            if text:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text
                )

            else:

                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source.chat.id,
                    message_id=source.message_id
                )

            group_sent += 1

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                if text:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=text
                    )

                else:

                    await context.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source.chat.id,
                        message_id=source.message_id
                    )

                group_sent += 1

            except Exception:
                failed += 1

        except Exception:
            failed += 1

        await asyncio.sleep(
            0.05
        )

    await update.message.reply_text(
        "📣 BROADCAST COMPLETE\n\n"
        f"👤 Users: {len(users)}\n"
        f"✅ User Sent: {user_sent}\n\n"
        f"👥 Groups: {len(groups)}\n"
        f"✅ Group Sent: {group_sent}\n\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# /STATS
# ============================================================

async def stats_command(update, context):

    if not is_owner(
        update.effective_user.id
    ):
        return

    users = await db.total_users()
    groups = await db.total_groups()

    await update.message.reply_text(
        "📊 BOT STATISTICS\n\n"
        f"👤 Total Users: {users}\n"
        f"👥 Total Groups: {groups}"
    )


# ============================================================
# BOT COMMAND MENU
# ============================================================

async def post_init(application):

    commands = [

        BotCommand(
            "start",
            "Start bot"
        ),

        BotCommand(
            "help",
            "Show help"
        ),

        BotCommand(
            "auto",
            "Group auto approve ON/OFF"
        ),

        BotCommand(
            "pending",
            "Approve pending requests"
        ),

        BotCommand(
            "stop",
            "Stop auto approval"
        ),

        BotCommand(
            "remove",
            "Remove pending requests"
        ),

        BotCommand(
            "ad",
            "Set advertisement"
        ),

        BotCommand(
            "delad",
            "Delete advertisement"
        ),

        BotCommand(
            "bc",
            "Broadcast message"
        ),

        BotCommand(
            "stats",
            "Show bot statistics"
        )
    ]

    await application.bot.set_my_commands(
        commands
    )

    me = await application.bot.get_me()

    LOGGER.info(
        "BOT CONNECTED: @%s",
        me.username
    )

    LOGGER.info(
        "OWNER ID: %s",
        OWNER_ID
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):

    LOGGER.error(
        "UPDATE ERROR: %s",
        context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    LOGGER.info(
        "Starting AUTO APPROVE BOT..."
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "auto",
            auto_command
        )
    )

    application.add_handler(
        CommandHandler(
            "pending",
            pending_command
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
            "ad",
            ad_command
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
            "bc",
            broadcast_command
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    # Join requests
    application.add_handler(
        ChatJoinRequestHandler(
            join_request
        )
    )

    # Errors
    application.add_error_handler(
        error_handler
    )

    LOGGER.info(
        "Polling started..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
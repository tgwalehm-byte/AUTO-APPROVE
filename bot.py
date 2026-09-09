import asyncio
import logging

from telegram import Update, BotCommand, ChatPermissions
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
    format="%(asctime)s | %(levelname)s | %(message)s",
)

LOGGER = logging.getLogger("AUTO_APPROVE")


# ============================================================
# HELPERS
# ============================================================

def is_owner(user_id: int) -> bool:
    return int(user_id) == int(OWNER_ID)


async def save_user(user):
    if not user:
        return

    try:
        await db.save_user(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
        )
    except Exception as e:
        LOGGER.error("SAVE USER ERROR: %s", e)


async def save_chat(chat):
    if not chat:
        return

    try:
        await db.save_group(
            chat.id,
            chat.title,
            chat.username,
        )
    except Exception as e:
        LOGGER.error("SAVE CHAT ERROR: %s", e)


async def is_group_admin(update, context) -> bool:
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    if is_owner(user.id):
        return True

    try:
        member = await context.bot.get_chat_member(
            chat_id=chat.id,
            user_id=user.id,
        )

        return member.status in ("administrator", "creator")

    except Exception as e:
        LOGGER.error("ADMIN CHECK ERROR: %s", e)
        return False


async def owner_only(update) -> bool:
    user = update.effective_user

    if not user:
        return False

    if is_owner(user.id):
        return True

    if update.message:
        await update.message.reply_text(
            "❌ You are not the bot owner."
        )

    return False


async def group_admin_only(update, context) -> bool:
    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        if update.message:
            await update.message.reply_text(
                "❌ Ye command sirf group mein use karein."
            )
        return False

    if not await is_group_admin(update, context):
        if update.message:
            await update.message.reply_text(
                "❌ Sirf group admin/owner ye command use kar sakta hai."
            )
        return False

    return True


# ============================================================
# SEND SAVED AD
# ============================================================

async def send_ad(context, user_chat_id):
    try:
        ad = await db.get_ad()
    except Exception as e:
        LOGGER.error("GET AD ERROR: %s", e)
        return

    if not ad:
        return

    try:
        if ad.get("type") == "text":

            await context.bot.send_message(
                chat_id=user_chat_id,
                text=ad.get("text", ""),
                disable_web_page_preview=False,
            )

        elif ad.get("type") == "copy":

            await context.bot.copy_message(
                chat_id=user_chat_id,
                from_chat_id=ad["from_chat_id"],
                message_id=ad["message_id"],
            )

    except RetryAfter as e:
        await asyncio.sleep(e.retry_after)

        try:
            if ad.get("type") == "text":
                await context.bot.send_message(
                    chat_id=user_chat_id,
                    text=ad.get("text", ""),
                )
            else:
                await context.bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=ad["from_chat_id"],
                    message_id=ad["message_id"],
                )
        except Exception as error:
            LOGGER.error("AD RETRY ERROR: %s", error)

    except Exception as e:
        LOGGER.warning(
            "AD DM FAILED | chat=%s | error=%s",
            user_chat_id,
            e,
        )


# ============================================================
# JOIN REQUEST
# ============================================================

async def join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):

    request = update.chat_join_request

    if not request:
        return

    user = request.from_user
    chat = request.chat

    LOGGER.info(
        "JOIN REQUEST | user=%s | chat=%s | type=%s",
        user.id,
        chat.id,
        chat.type,
    )

    # Save user
    await save_user(user)

    # ========================================================
    # CHANNEL
    # ========================================================

    if chat.type == ChatType.CHANNEL:

        await save_chat(chat)

        # Welcome DM
        try:
            await context.bot.send_message(
                chat_id=request.user_chat_id,
                text=(
                    "👋 Hello!\n\n"
                    "Your channel join request has been "
                    "received successfully. ❤️"
                ),
            )
        except Exception as e:
            LOGGER.info(
                "CHANNEL DM FAILED | %s",
                e,
            )

        # Advertisement
        await send_ad(
            context,
            request.user_chat_id,
        )

        # Automatic approval
        try:
            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user.id,
            )

            LOGGER.info(
                "CHANNEL APPROVED | user=%s | chat=%s",
                user.id,
                chat.id,
            )

        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)

            try:
                await context.bot.approve_chat_join_request(
                    chat_id=chat.id,
                    user_id=user.id,
                )
            except Exception as error:
                LOGGER.error(
                    "CHANNEL APPROVAL RETRY ERROR: %s",
                    error,
                )

        except Exception as e:
            LOGGER.error(
                "CHANNEL APPROVAL ERROR: %s",
                e,
            )

        return

    # ========================================================
    # GROUP
    # ========================================================

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        return

    await save_chat(chat)

    # Save pending request
    try:
        await db.save_pending(
            chat.id,
            user.id,
            request.user_chat_id,
        )
    except Exception as e:
        LOGGER.error(
            "SAVE PENDING ERROR: %s",
            e,
        )

    # Welcome DM
    try:
        await context.bot.send_message(
            chat_id=request.user_chat_id,
            text=(
                "👋 Hello!\n\n"
                "Your join request has been received. ❤️\n"
                "Please wait for approval."
            ),
        )
    except Exception as e:
        LOGGER.info(
            "GROUP DM FAILED | %s",
            e,
        )

    # Advertisement
    await send_ad(
        context,
        request.user_chat_id,
    )

    # Check auto approval
    try:
        enabled = await db.approval_enabled(chat.id)
    except Exception as e:
        LOGGER.error(
            "APPROVAL STATUS ERROR: %s",
            e,
        )
        enabled = False

    if not enabled:

        LOGGER.info(
            "REQUEST PENDING | user=%s | chat=%s",
            user.id,
            chat.id,
        )

        return

    # Automatic approval
    try:

        await context.bot.approve_chat_join_request(
            chat_id=chat.id,
            user_id=user.id,
        )

        await db.remove_pending(
            chat.id,
            user.id,
        )

        LOGGER.info(
            "GROUP APPROVED | user=%s | chat=%s",
            user.id,
            chat.id,
        )

    except RetryAfter as e:

        await asyncio.sleep(e.retry_after)

        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user.id,
            )

            await db.remove_pending(
                chat.id,
                user.id,
            )

        except Exception as error:
            LOGGER.error(
                "GROUP APPROVAL RETRY ERROR: %s",
                error,
            )

    except Exception as e:
        LOGGER.error(
            "GROUP APPROVAL ERROR: %s",
            e,
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
        "✅ Bot is online.\n\n"
        "Use /help to see all commands."
    )


# ============================================================
# /HELP
# ============================================================

async def help_command(update, context):

    text = (
        "🤖 AUTO APPROVE BOT\n\n"

        "👥 GROUP ADMIN COMMANDS\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "/auto on\n"
        "/auto off\n"
        "/pending 10\n"
        "/pending 20\n"
        "/pending 50\n"
        "/pending 100\n"
        "/pending 1000\n"
        "/stop\n"
        "/remove\n\n"

        "👑 OWNER COMMANDS\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "/ad\n"
        "/delad\n"
        "/bc\n"
        "/stats\n\n"

        "📢 CHANNEL\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Join request automatically approve hoti hai.\n"
        "Channel mein setup command ki zarurat nahi."
    )

    await update.message.reply_text(text)


# ============================================================
# /AUTO
# ============================================================

async def auto_command(update, context):

    if not await group_admin_only(update, context):
        return

    chat = update.effective_chat

    if not context.args:
        await update.message.reply_text(
            "⚙️ Usage:\n\n"
            "/auto on\n"
            "/auto off"
        )
        return

    option = context.args[0].lower()

    if option == "on":

        await db.set_approval(
            chat.id,
            True,
        )

        await update.message.reply_text(
            "✅ AUTO APPROVAL ENABLED\n\n"
            "New join requests ab automatically approve hongi."
        )

    elif option == "off":

        await db.set_approval(
            chat.id,
            False,
        )

        await update.message.reply_text(
            "🛑 AUTO APPROVAL DISABLED\n\n"
            "New join requests ab pending rahengi."
        )

    else:

        await update.message.reply_text(
            "❌ Invalid option.\n\n"
            "Use:\n"
            "/auto on\n"
            "/auto off"
        )


# ============================================================
# /PENDING
# ============================================================

async def pending_command(update, context):

    if not await group_admin_only(update, context):
        return

    chat = update.effective_chat

    if not context.args:

        await update.message.reply_text(
            "📌 Usage:\n\n"
            "/pending 10\n"
            "/pending 20\n"
            "/pending 50\n"
            "/pending 100\n"
            "/pending 1000"
        )

        return

    try:
        amount = int(context.args[0])
    except ValueError:

        await update.message.reply_text(
            "❌ Sirf number enter karein.\n\n"
            "Example: /pending 50"
        )

        return

    if amount <= 0:

        await update.message.reply_text(
            "❌ Number 0 se bada hona chahiye."
        )

        return

    amount = min(
        amount,
        100000,
    )

    requests = await db.get_pending(
        chat.id,
        amount,
    )

    if not requests:

        await update.message.reply_text(
            "ℹ️ Is group mein bot ke tracked pending requests nahi hain."
        )

        return

    await update.message.reply_text(
        f"⏳ {len(requests)} requests approve kar raha hoon..."
    )

    approved = 0
    failed = 0

    for item in requests:

        user_id = item["user_id"]

        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user_id,
            )

            await db.remove_pending(
                chat.id,
                user_id,
            )

            approved += 1

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

            try:

                await context.bot.approve_chat_join_request(
                    chat_id=chat.id,
                    user_id=user_id,
                )

                await db.remove_pending(
                    chat.id,
                    user_id,
                )

                approved += 1

            except Exception as error:
                LOGGER.error(
                    "PENDING RETRY ERROR: %s",
                    error,
                )
                failed += 1

        except Exception as e:

            LOGGER.warning(
                "PENDING APPROVAL FAILED | user=%s | %s",
                user_id,
                e,
            )

            failed += 1

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        "✅ PENDING APPROVAL COMPLETE\n\n"
        f"✅ Approved: {approved}\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# /STOP
# ============================================================

async def stop_command(update, context):

    if not await group_admin_only(update, context):
        return

    chat = update.effective_chat

    await db.set_approval(
        chat.id,
        False,
    )

    await update.message.reply_text(
        "🛑 AUTO APPROVAL STOPPED\n\n"
        "New join requests ab pending rahengi."
    )


# ============================================================
# /REMOVE
# ============================================================

async def remove_command(update, context):

    if not await group_admin_only(update, context):
        return

    chat = update.effective_chat

    requests = await db.get_pending(
        chat.id,
        100000,
    )

    if not requests:

        await update.message.reply_text(
            "ℹ️ Koi tracked pending request nahi hai."
        )

        return

    removed = 0

    for item in requests:

        user_id = item["user_id"]

        try:

            await context.bot.decline_chat_join_request(
                chat_id=chat.id,
                user_id=user_id,
            )

            await db.remove_pending(
                chat.id,
                user_id,
            )

            removed += 1

        except Exception as e:

            LOGGER.warning(
                "REMOVE FAILED | user=%s | %s",
                user_id,
                e,
            )

    await update.message.reply_text(
        "🗑 REMOVE COMPLETE\n\n"
        f"Removed: {removed}"
    )


# ============================================================
# /AD
# ============================================================

async def ad_command(update, context):

    if not await owner_only(update):
        return

    # /ad TEXT
    if context.args:

        text = " ".join(
            context.args
        )

        await db.set_ad({
            "type": "text",
            "text": text,
        })

        await update.message.reply_text(
            "✅ Advertisement saved successfully."
        )

        return

    # Reply + /ad
    if update.message.reply_to_message:

        message = update.message.reply_to_message

        await db.set_ad({
            "type": "copy",
            "from_chat_id": message.chat.id,
            "message_id": message.message_id,
        })

        await update.message.reply_text(
            "✅ Advertisement message saved successfully."
        )

        return

    await update.message.reply_text(
        "📢 AD SETUP\n\n"
        "Text:\n"
        "/ad Your advertisement\n\n"
        "Ya kisi message/photo/video/button wale message "
        "par reply karke /ad bhejein."
    )


# ============================================================
# /DELAD
# ============================================================

async def delad_command(update, context):

    if not await owner_only(update):
        return

    await db.delete_ad()

    await update.message.reply_text(
        "🗑 Advertisement deleted successfully."
    )


# ============================================================
# /BC
# ============================================================

async def broadcast_command(update, context):

    if not await owner_only(update):
        return

    source = update.message.reply_to_message

    text = None

    if context.args:
        text = " ".join(
            context.args
        )

    if not source and not text:

        await update.message.reply_text(
            "📣 BROADCAST USAGE\n\n"
            "/bc Your message\n\n"
            "Ya kisi message/photo/video par reply "
            "karke /bc bhejein."
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

    # ========================================================
    # USERS
    # ========================================================

    for chat_id in users:

        try:

            if text:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                )

            else:

                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source.chat.id,
                    message_id=source.message_id,
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
                        text=text,
                    )

                else:

                    await context.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source.chat.id,
                        message_id=source.message_id,
                    )

                user_sent += 1

            except Exception:
                failed += 1

        except Exception as e:

            LOGGER.warning(
                "USER BROADCAST FAILED | %s",
                e,
            )

            failed += 1

        await asyncio.sleep(0.05)

    # ========================================================
    # GROUPS
    # ========================================================

    for chat_id in groups:

        try:

            if text:

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                )

            else:

                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source.chat.id,
                    message_id=source.message_id,
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
                        text=text,
                    )

                else:

                    await context.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source.chat.id,
                        message_id=source.message_id,
                    )

                group_sent += 1

            except Exception:
                failed += 1

        except Exception as e:

            LOGGER.warning(
                "GROUP BROADCAST FAILED | %s",
                e,
            )

            failed += 1

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        "📣 BROADCAST COMPLETE\n\n"
        f"👤 Users Found: {len(users)}\n"
        f"✅ Users Sent: {user_sent}\n\n"
        f"👥 Groups Found: {len(groups)}\n"
        f"✅ Groups Sent: {group_sent}\n\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# /STATS
# ============================================================

async def stats_command(update, context):

    if not await owner_only(update):
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
        BotCommand("start", "Start bot"),
        BotCommand("help", "Show help"),
        BotCommand("auto", "Group auto approve ON/OFF"),
        BotCommand("pending", "Approve pending requests"),
        BotCommand("stop", "Stop auto approval"),
        BotCommand("remove", "Remove pending requests"),
        BotCommand("ad", "Set advertisement"),
        BotCommand("delad", "Delete advertisement"),
        BotCommand("bc", "Broadcast"),
        BotCommand("stats", "Bot statistics"),
    ]

    await application.bot.set_my_commands(
        commands
    )

    me = await application.bot.get_me()

    LOGGER.info(
        "BOT CONNECTED: @%s",
        me.username,
    )

    LOGGER.info(
        "OWNER ID: %s",
        OWNER_ID,
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):

    LOGGER.error(
        "UPDATE ERROR: %s",
        context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    LOGGER.info(
        "STARTING AUTO APPROVE BOT..."
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("auto", auto_command)
    )

    application.add_handler(
        CommandHandler("pending", pending_command)
    )

    application.add_handler(
        CommandHandler("stop", stop_command)
    )

    application.add_handler(
        CommandHandler("remove", remove_command)
    )

    application.add_handler(
        CommandHandler("ad", ad_command)
    )

    application.add_handler(
        CommandHandler("delad", delad_command)
    )

    application.add_handler(
        CommandHandler("bc", broadcast_command)
    )

    application.add_handler(
        CommandHandler("stats", stats_command)
    )

    # Join requests
    application.add_handler(
        ChatJoinRequestHandler(join_request)
    )

    # Errors
    application.add_error_handler(
        error_handler
    )

    LOGGER.info(
        "POLLING STARTED..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
import asyncio
import logging

from telegram import Update, BotCommand
from telegram.constants import ChatType
from telegram.error import RetryAfter
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
# BASIC HELPERS
# ============================================================

def owner_check(user_id):
    try:
        return int(user_id) == int(OWNER_ID)
    except Exception:
        return False


async def send_reply(update, text):
    try:
        if update.message:
            await update.message.reply_text(text)
    except Exception as e:
        LOGGER.error("REPLY ERROR: %s", e)


# ============================================================
# USER SAVE
# ============================================================

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
        LOGGER.error("USER SAVE ERROR: %s", e)


# ============================================================
# CHAT SAVE
# ============================================================

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
        LOGGER.error("CHAT SAVE ERROR: %s", e)


# ============================================================
# OWNER CHECK
# ============================================================

async def require_owner(update):

    user = update.effective_user

    if not user:
        await send_reply(
            update,
            "❌ User information not found.",
        )
        return False

    LOGGER.info(
        "OWNER CHECK | User ID=%s | Config OWNER_ID=%s",
        user.id,
        OWNER_ID,
    )

    if owner_check(user.id):
        return True

    await send_reply(
        update,
        "❌ You are not the bot owner.\n\n"
        f"Your ID: `{user.id}`\n"
        "Use this numeric ID in OWNER_ID.",
    )

    return False


# ============================================================
# GROUP ADMIN CHECK
# ============================================================

async def require_group_admin(update, context):

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return False

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        await send_reply(
            update,
            "❌ Ye command sirf group mein use ho sakti hai.",
        )
        return False

    # Bot owner can control any group
    if owner_check(user.id):
        return True

    try:

        admins = await context.bot.get_chat_administrators(
            chat_id=chat.id
        )

        for admin in admins:

            if admin.user.id == user.id:

                if admin.status in (
                    "administrator",
                    "creator",
                ):
                    return True

    except Exception as e:

        LOGGER.error(
            "GROUP ADMIN CHECK ERROR | chat=%s | user=%s | %s",
            chat.id,
            user.id,
            e,
        )

    await send_reply(
        update,
        "❌ Sirf is group ke admin/owner ye command use kar sakte hain.",
    )

    return False


# ============================================================
# SEND AD
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

            elif ad.get("type") == "copy":

                await context.bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=ad["from_chat_id"],
                    message_id=ad["message_id"],
                )

        except Exception as error:

            LOGGER.error(
                "AD RETRY ERROR: %s",
                error,
            )

    except Exception as e:

        LOGGER.warning(
            "AD DM FAILED | %s",
            e,
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
        chat.type,
    )

    await save_user(user)

    # ========================================================
    # CHANNEL
    # ========================================================

    if chat.type == ChatType.CHANNEL:

        await save_chat(chat)

        # Welcome
        try:

            await context.bot.send_message(
                chat_id=request.user_chat_id,
                text=(
                    "👋 Hello!\n\n"
                    "Your join request has been received successfully. ❤️"
                ),
            )

        except Exception as e:

            LOGGER.info(
                "CHANNEL DM ERROR: %s",
                e,
            )

        # Advertisement
        await send_ad(
            context,
            request.user_chat_id,
        )

        # Auto approve
        try:

            await context.bot.approve_chat_join_request(
                chat_id=chat.id,
                user_id=user.id,
            )

            LOGGER.info(
                "CHANNEL APPROVED | %s",
                user.id,
            )

        except RetryAfter as e:

            await asyncio.sleep(
                e.retry_after
            )

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

    # Save pending
    try:

        await db.save_pending(
            chat.id,
            user.id,
            request.user_chat_id,
        )

    except Exception as e:

        LOGGER.error(
            "PENDING SAVE ERROR: %s",
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
            "GROUP DM ERROR: %s",
            e,
        )

    # Advertisement
    await send_ad(
        context,
        request.user_chat_id,
    )

    # Auto status
    try:

        enabled = await db.approval_enabled(
            chat.id
        )

    except Exception as e:

        LOGGER.error(
            "AUTO STATUS ERROR: %s",
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

    # Auto approve
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
            "GROUP AUTO APPROVED | user=%s | chat=%s",
            user.id,
            chat.id,
        )

    except RetryAfter as e:

        await asyncio.sleep(
            e.retry_after
        )

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
                "AUTO APPROVE RETRY ERROR: %s",
                error,
            )

    except Exception as e:

        LOGGER.error(
            "AUTO APPROVE ERROR: %s",
            e,
        )


# ============================================================
# /ID
# ============================================================

async def id_command(update, context):

    user = update.effective_user

    if not user:
        return

    await send_reply(
        update,
        "🆔 YOUR TELEGRAM ID\n\n"
        f"`{user.id}`",
    )


# ============================================================
# /START
# ============================================================

async def start_command(update, context):

    await save_user(
        update.effective_user
    )

    await send_reply(
        update,
        "🤖 AUTO APPROVE BOT\n\n"
        "✅ Bot is online.\n\n"
        "Use /help to see commands.\n\n"
        "Use /id to check your Telegram ID.",
    )


# ============================================================
# /HELP
# ============================================================

async def help_command(update, context):

    await send_reply(
        update,
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
        "Join request → DM → Ad → Auto Approve",
    )


# ============================================================
# /AUTO
# ============================================================

async def auto_command(update, context):

    if not await require_group_admin(
        update,
        context,
    ):
        return

    chat = update.effective_chat

    if not context.args:

        await send_reply(
            update,
            "⚙️ Usage:\n\n"
            "/auto on\n"
            "/auto off",
        )

        return

    option = context.args[0].lower()

    if option == "on":

        await db.set_approval(
            chat.id,
            True,
        )

        await send_reply(
            update,
            "✅ AUTO APPROVAL ON\n\n"
            "Ab new join requests automatically approve hongi.",
        )

    elif option == "off":

        await db.set_approval(
            chat.id,
            False,
        )

        await send_reply(
            update,
            "🛑 AUTO APPROVAL OFF\n\n"
            "Ab new requests pending rahengi.",
        )

    else:

        await send_reply(
            update,
            "❌ Use:\n\n"
            "/auto on\n"
            "/auto off",
        )


# ============================================================
# /PENDING
# ============================================================

async def pending_command(update, context):

    if not await require_group_admin(
        update,
        context,
    ):
        return

    chat = update.effective_chat

    if not context.args:

        await send_reply(
            update,
            "📌 Example:\n\n"
            "/pending 10\n"
            "/pending 20\n"
            "/pending 50\n"
            "/pending 100\n"
            "/pending 1000",
        )

        return

    try:

        amount = int(
            context.args[0]
        )

    except ValueError:

        await send_reply(
            update,
            "❌ Number enter karein.\n\n"
            "Example: /pending 50",
        )

        return

    if amount <= 0:

        await send_reply(
            update,
            "❌ Number 0 se bada hona chahiye.",
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

        await send_reply(
            update,
            "ℹ️ Is group mein tracked pending requests nahi hain.",
        )

        return

    await send_reply(
        update,
        f"⏳ {len(requests)} requests approve kar raha hoon...",
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
                "PENDING ERROR | user=%s | %s",
                user_id,
                e,
            )

            failed += 1

        await asyncio.sleep(0.05)

    await send_reply(
        update,
        "✅ PENDING COMPLETE\n\n"
        f"✅ Approved: {approved}\n"
        f"❌ Failed: {failed}",
    )


# ============================================================
# /STOP
# ============================================================

async def stop_command(update, context):

    if not await require_group_admin(
        update,
        context,
    ):
        return

    chat = update.effective_chat

    await db.set_approval(
        chat.id,
        False,
    )

    await send_reply(
        update,
        "🛑 AUTO APPROVAL STOPPED\n\n"
        "New requests ab pending rahengi.",
    )


# ============================================================
# /REMOVE
# ============================================================

async def remove_command(update, context):

    if not await require_group_admin(
        update,
        context,
    ):
        return

    chat = update.effective_chat

    requests = await db.get_pending(
        chat.id,
        100000,
    )

    if not requests:

        await send_reply(
            update,
            "ℹ️ Koi tracked pending request nahi hai.",
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
                "REMOVE ERROR | user=%s | %s",
                user_id,
                e,
            )

    await send_reply(
        update,
        "🗑 REMOVE COMPLETE\n\n"
        f"Removed: {removed}",
    )


# ============================================================
# /AD
# ============================================================

async def ad_command(update, context):

    if not await require_owner(update):
        return

    # /ad text
    if context.args:

        text = " ".join(
            context.args
        )

        await db.set_ad({
            "type": "text",
            "text": text,
        })

        await send_reply(
            update,
            "✅ Advertisement saved.",
        )

        return

    # Reply to message
    if update.message and update.message.reply_to_message:

        message = update.message.reply_to_message

        await db.set_ad({
            "type": "copy",
            "from_chat_id": message.chat.id,
            "message_id": message.message_id,
        })

        await send_reply(
            update,
            "✅ Advertisement message saved.",
        )

        return

    await send_reply(
        update,
        "📢 AD SETUP\n\n"
        "Text:\n"
        "/ad Your advertisement\n\n"
        "Ya kisi photo/video/message par reply karke:\n"
        "/ad",
    )


# ============================================================
# /DELAD
# ============================================================

async def delad_command(update, context):

    if not await require_owner(update):
        return

    await db.delete_ad()

    await send_reply(
        update,
        "🗑 Advertisement deleted.",
    )


# ============================================================
# /BC
# ============================================================

async def broadcast_command(update, context):

    if not await require_owner(update):
        return

    source = None

    if update.message:
        source = update.message.reply_to_message

    text = None

    if context.args:
        text = " ".join(
            context.args
        )

    if not source and not text:

        await send_reply(
            update,
            "📣 BROADCAST\n\n"
            "/bc Your message\n\n"
            "Ya kisi message/photo/video par reply karke /bc bhejein.",
        )

        return

    users = await db.get_all_users()
    groups = await db.get_all_groups()

    await send_reply(
        update,
        "📣 Broadcast started...",
    )

    user_sent = 0
    group_sent = 0
    failed = 0

    # USERS
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
                "USER BC ERROR: %s",
                e,
            )

            failed += 1

        await asyncio.sleep(0.05)

    # GROUPS
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
                "GROUP BC ERROR: %s",
                e,
            )

            failed += 1

        await asyncio.sleep(0.05)

    await send_reply(
        update,
        "📣 BROADCAST COMPLETE\n\n"
        f"👤 Users: {user_sent}/{len(users)}\n"
        f"👥 Groups: {group_sent}/{len(groups)}\n"
        f"❌ Failed: {failed}",
    )


# ============================================================
# /STATS
# ============================================================

async def stats_command(update, context):

    if not await require_owner(update):
        return

    users = await db.total_users()
    groups = await db.total_groups()

    await send_reply(
        update,
        "📊 BOT STATISTICS\n\n"
        f"👤 Total Users: {users}\n"
        f"👥 Total Groups: {groups}",
    )


# ============================================================
# COMMAND MENU
# ============================================================

async def post_init(application):

    commands = [
        BotCommand("start", "Start bot"),
        BotCommand("help", "Show help"),
        BotCommand("id", "Show Telegram ID"),
        BotCommand("auto", "Auto approve ON/OFF"),
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
        "===================================="
    )

    LOGGER.info(
        "BOT CONNECTED: @%s",
        me.username,
    )

    LOGGER.info(
        "BOT ID: %s",
        me.id,
    )

    LOGGER.info(
        "OWNER_ID CONFIG: %s",
        OWNER_ID,
    )

    LOGGER.info(
        "===================================="
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

    # Basic
    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "id",
            id_command,
        )
    )

    # Group
    application.add_handler(
        CommandHandler(
            "auto",
            auto_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "pending",
            pending_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stop",
            stop_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "remove",
            remove_command,
        )
    )

    # Owner
    application.add_handler(
        CommandHandler(
            "ad",
            ad_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "delad",
            delad_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "bc",
            broadcast_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command,
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
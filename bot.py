import asyncio
import logging
import re

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatType
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    ChatJoinRequestHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
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
# AD BUILDER STATES
# ============================================================

AD_MENU = 1
AD_PHOTO = 2
AD_TEXT = 3
AD_BUTTON_TEXT = 4
AD_BUTTON_URL = 5


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
        return False

    LOGGER.info(
        "OWNER CHECK | user=%s | OWNER_ID=%s",
        user.id,
        OWNER_ID,
    )

    if owner_check(user.id):
        return True

    await send_reply(
        update,
        "❌ You are not the bot owner.\n\n"
        f"Your Telegram ID:\n`{user.id}`",
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

    # Bot owner can control all groups
    if owner_check(user.id):
        return True

    try:

        member = await context.bot.get_chat_member(
            chat_id=chat.id,
            user_id=user.id,
        )

        if member.status in (
            "administrator",
            "creator",
        ):
            return True

    except Exception as e:

        LOGGER.error(
            "ADMIN CHECK ERROR: %s",
            e,
        )

    await send_reply(
        update,
        "❌ Sirf is group ke admin/owner ye command use kar sakta hai.",
    )

    return False


# ============================================================
# AD KEYBOARD
# ============================================================

def ad_manager_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ CREATE NEW AD",
                callback_data="ad_create",
            )
        ],
        [
            InlineKeyboardButton(
                "👁 PREVIEW",
                callback_data="ad_preview",
            ),
            InlineKeyboardButton(
                "✏️ EDIT",
                callback_data="ad_edit",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ SET AD",
                callback_data="ad_set",
            ),
            InlineKeyboardButton(
                "🗑 DELETE",
                callback_data="ad_delete",
            ),
        ],
    ])


def ad_builder_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📸 ADD PHOTO",
                callback_data="ad_photo",
            ),
            InlineKeyboardButton(
                "⏭ SKIP PHOTO",
                callback_data="ad_skip_photo",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ CANCEL",
                callback_data="ad_cancel",
            )
        ],
    ])


def ad_after_photo_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📝 ADD / EDIT TEXT",
                callback_data="ad_text",
            )
        ],
        [
            InlineKeyboardButton(
                "🔘 ADD BUTTON",
                callback_data="ad_button",
            )
        ],
        [
            InlineKeyboardButton(
                "👁 PREVIEW",
                callback_data="ad_preview_temp",
            )
        ],
        [
            InlineKeyboardButton(
                "✅ SET AD",
                callback_data="ad_set_temp",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ CANCEL",
                callback_data="ad_cancel",
            )
        ],
    ])


# ============================================================
# AD DATA
# ============================================================

def get_draft(context):

    draft = context.user_data.get("ad_draft")

    if not draft:

        draft = {
            "photo": None,
            "text": "",
            "buttons": [],
        }

        context.user_data["ad_draft"] = draft

    return draft


def make_ad_keyboard(buttons):

    rows = []

    for button in buttons:

        rows.append([
            InlineKeyboardButton(
                button["text"],
                url=button["url"],
            )
        ])

    return (
        InlineKeyboardMarkup(rows)
        if rows
        else None
    )


# ============================================================
# AD PREVIEW
# ============================================================

async def show_draft_preview(
    context,
    chat_id,
    draft,
):

    photo = draft.get("photo")
    text = draft.get("text") or "No advertisement text."

    keyboard = make_ad_keyboard(
        draft.get("buttons", [])
    )

    if photo:

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=text[:1024],
            reply_markup=keyboard,
        )

    else:

        await context.bot.send_message(
            chat_id=chat_id,
            text=text[:4096],
            reply_markup=keyboard,
        )


# ============================================================
# /AD
# ============================================================

async def ad_command(update, context):

    if not await require_owner(update):
        return ConversationHandler.END

    await send_reply(
        update,
        "📢 AD MANAGER\n\n"
        "Create your advertisement using the buttons below.",
    )

    await update.message.reply_text(
        "👇 Advertisement Manager",
        reply_markup=ad_manager_keyboard(),
    )

    return AD_MENU


# ============================================================
# AD CALLBACK
# ============================================================

async def ad_callback(update, context):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    if not owner_check(user.id):

        await query.answer(
            "❌ Owner only.",
            show_alert=True,
        )
        return AD_MENU

    data = query.data

    # ========================================================
    # CREATE
    # ========================================================

    if data == "ad_create":

        context.user_data["ad_draft"] = {
            "photo": None,
            "text": "",
            "buttons": [],
        }

        await query.edit_message_text(
            "📢 CREATE NEW AD\n\n"
            "Photo add karni hai ya skip karna hai?",
            reply_markup=ad_builder_keyboard(),
        )

        return AD_MENU

    # ========================================================
    # ADD PHOTO
    # ========================================================

    if data == "ad_photo":

        await query.edit_message_text(
            "📸 Please send the advertisement photo.\n\n"
            "Photo bhejne ke baad text setup hoga."
        )

        return AD_PHOTO

    # ========================================================
    # SKIP PHOTO
    # ========================================================

    if data == "ad_skip_photo":

        draft = get_draft(context)

        draft["photo"] = None

        await query.edit_message_text(
            "📝 Ab advertisement ka text bhejein."
        )

        return AD_TEXT

    # ========================================================
    # TEXT
    # ========================================================

    if data == "ad_text":

        await query.edit_message_text(
            "📝 Advertisement text bhejein."
        )

        return AD_TEXT

    # ========================================================
    # BUTTON
    # ========================================================

    if data == "ad_button":

        await query.edit_message_text(
            "🔘 Button ka naam bhejein.\n\n"
            "Example:\n"
            "JOIN NOW"
        )

        return AD_BUTTON_TEXT

    # ========================================================
    # PREVIEW SAVED
    # ========================================================

    if data == "ad_preview":

        ad = await db.get_ad()

        if not ad:

            await query.edit_message_text(
                "❌ Koi advertisement set nahi hai.",
                reply_markup=ad_manager_keyboard(),
            )

            return AD_MENU

        await query.edit_message_text(
            "👁 Current Advertisement:"
        )

        if ad.get("type") == "builder":

            await show_saved_ad(
                context,
                query.message.chat.id,
                ad,
            )

        elif ad.get("type") == "text":

            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=ad.get("text", ""),
            )

        elif ad.get("type") == "copy":

            await context.bot.copy_message(
                chat_id=query.message.chat.id,
                from_chat_id=ad["from_chat_id"],
                message_id=ad["message_id"],
            )

        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text="📢 AD MANAGER",
            reply_markup=ad_manager_keyboard(),
        )

        return AD_MENU

    # ========================================================
    # EDIT
    # ========================================================

    if data == "ad_edit":

        ad = await db.get_ad()

        if not ad:

            await query.edit_message_text(
                "❌ Pehle advertisement create karein.",
                reply_markup=ad_manager_keyboard(),
            )

            return AD_MENU

        if ad.get("type") == "builder":

            context.user_data["ad_draft"] = {
                "photo": ad.get("photo"),
                "text": ad.get("text", ""),
                "buttons": ad.get("buttons", []),
            }

        else:

            context.user_data["ad_draft"] = {
                "photo": None,
                "text": ad.get("text", ""),
                "buttons": [],
            }

        await query.edit_message_text(
            "✏️ AD EDITOR\n\n"
            "Text edit karne ke liye button dabayein, "
            "ya naya button add karein.",
            reply_markup=ad_after_photo_keyboard(),
        )

        return AD_MENU

    # ========================================================
    # SET CURRENT DRAFT
    # ========================================================

    if data == "ad_set_temp":

        draft = get_draft(context)

        if not draft.get("photo") and not draft.get("text"):

            await query.answer(
                "❌ Photo ya text zaroori hai.",
                show_alert=True,
            )

            return AD_MENU

        await db.set_ad({
            "type": "builder",
            "photo": draft.get("photo"),
            "text": draft.get("text", ""),
            "buttons": draft.get("buttons", []),
        })

        await query.edit_message_text(
            "✅ Advertisement SET successfully.\n\n"
            "Ab join request aane par ye ad user ko milega.",
            reply_markup=ad_manager_keyboard(),
        )

        return AD_MENU

    # ========================================================
    # SET SAVED
    # ========================================================

    if data == "ad_set":

        ad = await db.get_ad()

        if not ad:

            await query.answer(
                "❌ Pehle advertisement create karein.",
                show_alert=True,
            )

            return AD_MENU

        await query.edit_message_text(
            "✅ Advertisement already SET hai.",
            reply_markup=ad_manager_keyboard(),
        )

        return AD_MENU

    # ========================================================
    # DELETE
    # ========================================================

    if data == "ad_delete":

        await db.delete_ad()

        context.user_data.pop(
            "ad_draft",
            None,
        )

        await query.edit_message_text(
            "🗑 Advertisement deleted successfully.",
            reply_markup=ad_manager_keyboard(),
        )

        return AD_MENU

    # ========================================================
    # TEMP PREVIEW
    # ========================================================

    if data == "ad_preview_temp":

        draft = get_draft(context)

        await query.edit_message_text(
            "👁 Advertisement Preview:"
        )

        await show_draft_preview(
            context,
            query.message.chat.id,
            draft,
        )

        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text="📢 AD EDITOR",
            reply_markup=ad_after_photo_keyboard(),
        )

        return AD_MENU

    # ========================================================
    # CANCEL
    # ========================================================

    if data == "ad_cancel":

        context.user_data.pop(
            "ad_draft",
            None,
        )

        await query.edit_message_text(
            "❌ Advertisement creation cancelled.",
            reply_markup=ad_manager_keyboard(),
        )

        return AD_MENU

    return AD_MENU


# ============================================================
# PHOTO RECEIVER
# ============================================================

async def ad_photo_received(update, context):

    if not owner_check(
        update.effective_user.id
    ):
        return ConversationHandler.END

    if not update.message.photo:

        await send_reply(
            update,
            "❌ Please send a photo.",
        )

        return AD_PHOTO

    draft = get_draft(context)

    draft["photo"] = (
        update.message.photo[-1].file_id
    )

    await send_reply(
        update,
        "✅ Photo added.\n\n"
        "📝 Ab advertisement text bhejein.",
    )

    return AD_TEXT


# ============================================================
# TEXT RECEIVER
# ============================================================

async def ad_text_received(update, context):

    if not owner_check(
        update.effective_user.id
    ):
        return ConversationHandler.END

    if not update.message.text:

        await send_reply(
            update,
            "❌ Please send text.",
        )

        return AD_TEXT

    draft = get_draft(context)

    draft["text"] = update.message.text

    await update.message.reply_text(
        "✅ Text saved.\n\n"
        "Ab kya karna hai?",
        reply_markup=ad_after_photo_keyboard(),
    )

    return AD_MENU


# ============================================================
# BUTTON TEXT
# ============================================================

async def ad_button_text_received(update, context):

    if not owner_check(
        update.effective_user.id
    ):
        return ConversationHandler.END

    button_text = update.message.text.strip()

    if not button_text:

        await send_reply(
            update,
            "❌ Button name empty nahi ho sakta.",
        )

        return AD_BUTTON_TEXT

    context.user_data["pending_button_text"] = (
        button_text[:64]
    )

    await send_reply(
        update,
        "🔗 Ab button ka URL bhejein.\n\n"
        "Example:\n"
        "https://t.me/example",
    )

    return AD_BUTTON_URL


# ============================================================
# BUTTON URL
# ============================================================

async def ad_button_url_received(update, context):

    if not owner_check(
        update.effective_user.id
    ):
        return ConversationHandler.END

    url = update.message.text.strip()

    if not re.match(
        r"^(https?://|tg://)",
        url,
        re.IGNORECASE,
    ):

        await send_reply(
            update,
            "❌ Invalid URL.\n\n"
            "Example:\n"
            "https://t.me/example",
        )

        return AD_BUTTON_URL

    draft = get_draft(context)

    button_text = context.user_data.pop(
        "pending_button_text",
        "BUTTON",
    )

    draft["buttons"].append({
        "text": button_text,
        "url": url,
    })

    await update.message.reply_text(
        "✅ Button added.\n\n"
        "Ab next button add kar sakte hain ya Preview/Set kar sakte hain.",
        reply_markup=ad_after_photo_keyboard(),
    )

    return AD_MENU


# ============================================================
# SHOW SAVED AD
# ============================================================

async def show_saved_ad(
    context,
    chat_id,
    ad,
):

    text = ad.get(
        "text",
        "",
    )

    buttons = ad.get(
        "buttons",
        [],
    )

    keyboard = make_ad_keyboard(
        buttons
    )

    photo = ad.get(
        "photo"
    )

    if photo:

        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=text[:1024],
            reply_markup=keyboard,
        )

    else:

        await context.bot.send_message(
            chat_id=chat_id,
            text=text[:4096],
            reply_markup=keyboard,
        )


# ============================================================
# SEND AD TO USER
# ============================================================

async def send_ad(context, user_chat_id):

    try:
        ad = await db.get_ad()
    except Exception as e:
        LOGGER.error(
            "GET AD ERROR: %s",
            e,
        )
        return

    if not ad:
        return

    try:

        if ad.get("type") == "builder":

            await show_saved_ad(
                context,
                user_chat_id,
                ad,
            )

        elif ad.get("type") == "text":

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

    except RetryAfter as e:

        await asyncio.sleep(
            e.retry_after
        )

        try:

            if ad.get("type") == "builder":

                await show_saved_ad(
                    context,
                    user_chat_id,
                    ad,
                )

            elif ad.get("type") == "text":

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
                "CHANNEL DM ERROR: %s",
                e,
            )

        await send_ad(
            context,
            request.user_chat_id,
        )

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

    await send_ad(
        context,
        request.user_chat_id,
    )

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
                "APPROVAL RETRY ERROR: %s",
                error,
            )

    except Exception as e:

        LOGGER.error(
            "APPROVAL ERROR: %s",
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
        "/help - Commands\n"
        "/id - Your Telegram ID",
    )


# ============================================================
# /HELP
# ============================================================

async def help_command(update, context):

    await send_reply(
        update,
        "🤖 AUTO APPROVE BOT\n\n"

        "👥 GROUP ADMIN\n"
        "━━━━━━━━━━━━━━\n"
        "/auto on\n"
        "/auto off\n"
        "/pending 10\n"
        "/pending 20\n"
        "/pending 50\n"
        "/pending 100\n"
        "/pending 1000\n"
        "/stop\n"
        "/remove\n\n"

        "👑 OWNER\n"
        "━━━━━━━━━━━━━━\n"
        "/ad\n"
        "/delad\n"
        "/bcuser\n"
        "/bcgroup\n"
        "/bcall\n"
        "/stats\n\n"

        "📢 CHANNEL\n"
        "━━━━━━━━━━━━━━\n"
        "Join request → DM → Advertisement → Auto Approve",
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
            "New join requests automatically approve hongi.",
        )

    elif option == "off":

        await db.set_approval(
            chat.id,
            False,
        )

        await send_reply(
            update,
            "🛑 AUTO APPROVAL OFF\n\n"
            "New requests pending rahengi.",
        )

    else:

        await send_reply(
            update,
            "❌ Use /auto on or /auto off",
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
            "ℹ️ Tracked pending requests nahi hain.",
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

            except Exception:

                failed += 1

        except Exception:

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

    await db.set_approval(
        update.effective_chat.id,
        False,
    )

    await send_reply(
        update,
        "🛑 AUTO APPROVAL STOPPED.",
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

        except Exception:
            pass

    await send_reply(
        update,
        "🗑 REMOVE COMPLETE\n\n"
        f"Removed: {removed}",
    )


# ============================================================
# BROADCAST HELPER
# ============================================================

async def broadcast_to_chat(
    context,
    chat_id,
    source,
    text,
):

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

        return True

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

            return True

        except Exception:
            return False

    except Exception as e:

        LOGGER.warning(
            "BROADCAST ERROR | chat=%s | %s",
            chat_id,
            e,
        )

        return False


# ============================================================
# BROADCAST USERS
# ============================================================

async def bcuser_command(update, context):

    if not await require_owner(update):
        return

    source = update.message.reply_to_message
    text = " ".join(context.args) if context.args else None

    if not source and not text:

        await send_reply(
            update,
            "📣 USER BROADCAST\n\n"
            "/bcuser Your message\n\n"
            "Ya kisi message/photo/video par reply karke /bcuser",
        )

        return

    users = await db.get_all_users()

    await send_reply(
        update,
        "📣 USER BROADCAST STARTED...",
    )

    sent = 0
    failed = 0

    for chat_id in users:

        success = await broadcast_to_chat(
            context,
            chat_id,
            source,
            text,
        )

        if success:
            sent += 1
        else:
            failed += 1

        await asyncio.sleep(0.05)

    await send_reply(
        update,
        "📣 USER BROADCAST COMPLETE\n\n"
        f"👤 Users: {sent}/{len(users)}\n"
        f"❌ Failed: {failed}",
    )


# ============================================================
# BROADCAST GROUPS
# ============================================================

async def bcgroup_command(update, context):

    if not await require_owner(update):
        return

    source = update.message.reply_to_message
    text = " ".join(context.args) if context.args else None

    if not source and not text:

        await send_reply(
            update,
            "📣 GROUP BROADCAST\n\n"
            "/bcgroup Your message\n\n"
            "Ya kisi message/photo/video par reply karke /bcgroup",
        )

        return

    groups = await db.get_all_groups()

    await send_reply(
        update,
        "📣 GROUP BROADCAST STARTED...",
    )

    sent = 0
    failed = 0

    for chat_id in groups:

        success = await broadcast_to_chat(
            context,
            chat_id,
            source,
            text,
        )

        if success:
            sent += 1
        else:
            failed += 1

        await asyncio.sleep(0.05)

    await send_reply(
        update,
        "📣 GROUP BROADCAST COMPLETE\n\n"
        f"👥 Groups: {sent}/{len(groups)}\n"
        f"❌ Failed: {failed}",
    )


# ============================================================
# BROADCAST ALL
# ============================================================

async def bcall_command(update, context):

    if not await require_owner(update):
        return

    source = update.message.reply_to_message
    text = " ".join(context.args) if context.args else None

    if not source and not text:

        await send_reply(
            update,
            "📣 GLOBAL BROADCAST\n\n"
            "/bcall Your message\n\n"
            "Ya kisi message/photo/video par reply karke /bcall",
        )

        return

    users = await db.get_all_users()
    groups = await db.get_all_groups()

    await send_reply(
        update,
        "📣 GLOBAL BROADCAST STARTED...",
    )

    user_sent = 0
    group_sent = 0
    failed = 0

    # USERS
    for chat_id in users:

        success = await broadcast_to_chat(
            context,
            chat_id,
            source,
            text,
        )

        if success:
            user_sent += 1
        else:
            failed += 1

        await asyncio.sleep(0.05)

    # GROUPS
    for chat_id in groups:

        success = await broadcast_to_chat(
            context,
            chat_id,
            source,
            text,
        )

        if success:
            group_sent += 1
        else:
            failed += 1

        await asyncio.sleep(0.05)

    await send_reply(
        update,
        "📣 GLOBAL BROADCAST COMPLETE\n\n"
        f"👤 Users: {user_sent}/{len(users)}\n"
        f"👥 Groups: {group_sent}/{len(groups)}\n"
        f"❌ Failed: {failed}",
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
# CANCEL AD
# ============================================================

async def ad_cancel_command(update, context):

    context.user_data.pop(
        "ad_draft",
        None,
    )

    context.user_data.pop(
        "pending_button_text",
        None,
    )

    await send_reply(
        update,
        "❌ Advertisement creation cancelled.",
    )

    return ConversationHandler.END


# ============================================================
# COMMAND MENU
# ============================================================

async def post_init(application):

    commands = [
        BotCommand("start", "Start bot"),
        BotCommand("help", "Show commands"),
        BotCommand("id", "Show Telegram ID"),

        BotCommand("auto", "Group auto approve"),
        BotCommand("pending", "Approve pending"),
        BotCommand("stop", "Stop auto approval"),
        BotCommand("remove", "Remove requests"),

        BotCommand("ad", "Advertisement manager"),
        BotCommand("delad", "Delete advertisement"),

        BotCommand("bcuser", "Broadcast users"),
        BotCommand("bcgroup", "Broadcast groups"),
        BotCommand("bcall", "Broadcast everyone"),

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
        "OWNER_ID: %s",
        OWNER_ID,
    )

    LOGGER.info(
        "===================================="
    )


# ============================================================
# ERROR
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

    # ========================================================
    # AD CONVERSATION
    # ========================================================

    ad_conversation = ConversationHandler(
        entry_points=[
            CommandHandler(
                "ad",
                ad_command,
            )
        ],

        states={

            AD_MENU: [
                CallbackQueryHandler(
                    ad_callback,
                    pattern=r"^ad_",
                ),
            ],

            AD_PHOTO: [
                MessageHandler(
                    filters.PHOTO,
                    ad_photo_received,
                ),
            ],

            AD_TEXT: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ad_text_received,
                ),
            ],

            AD_BUTTON_TEXT: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ad_button_text_received,
                ),
            ],

            AD_BUTTON_URL: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    ad_button_url_received,
                ),
            ],
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                ad_cancel_command,
            )
        ],

        allow_reentry=True,
    )

    application.add_handler(
        ad_conversation
    )

    # ========================================================
    # BASIC
    # ========================================================

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

    # ========================================================
    # GROUP
    # ========================================================

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

    # ========================================================
    # OWNER
    # ========================================================

    application.add_handler(
        CommandHandler(
            "delad",
            delad_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "bcuser",
            bcuser_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "bcgroup",
            bcgroup_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "bcall",
            bcall_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command,
        )
    )

    # ========================================================
    # JOIN REQUEST
    # ========================================================

    application.add_handler(
        ChatJoinRequestHandler(
            join_request
        )
    )

    # ========================================================
    # ERROR
    # ========================================================

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
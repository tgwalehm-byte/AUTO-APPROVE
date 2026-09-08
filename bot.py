import os
import asyncio
import logging
import aiohttp

from pyrogram import Client, filters
from pyrogram.types import (
    ChatJoinRequest,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import FloodWait

from database import (
    get_auto_approve,
    set_auto_approve,

    get_ad,
    save_ad,
    delete_ad,

    save_user,
    mark_user_started,
    get_all_users,
    delete_user,
    get_total_users,
    get_started_users,

    save_group,
    delete_group,
    get_all_groups,
    get_all_channels,
    get_all_chats,
    get_total_groups,
    get_total_channels,
    get_chat_info,

    save_request,
    get_pending_requests,
    delete_request,
    get_pending_count
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(message)s"
)

LOGGER = logging.getLogger(__name__)


# =========================================================
# CONFIG
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


# =========================================================
# GLOBAL
# =========================================================

bot_username = None
bot_id = None

http_session = None

running_tasks = {}


# =========================================================
# HTTP SESSION
# =========================================================

async def get_http_session():

    global http_session

    if http_session is None or http_session.closed:

        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=100,
            ttl_dns_cache=300
        )

        timeout = aiohttp.ClientTimeout(
            total=30
        )

        http_session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )

    return http_session


async def bot_api_call(
    method,
    data
):

    session = await get_http_session()

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/{method}"
    )

    async with session.post(
        url,
        json=data
    ) as response:

        result = await response.json()

        if not result.get("ok"):

            raise Exception(
                result.get(
                    "description",
                    "Telegram API error"
                )
            )

        return result.get("result")


# =========================================================
# TELEGRAM JOIN REQUEST API
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
# LINKS
# =========================================================

def group_add_link():

    return (
        f"https://t.me/{bot_username}"
        f"?startgroup&admin=invite_users"
    )


def channel_add_link():

    return (
        f"https://t.me/{bot_username}"
        f"?startchannel&admin=invite_users"
    )


# =========================================================
# PRIVATE MAIN PANEL
# =========================================================

def main_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 GROUPS",
                    callback_data="groups"
                ),
                InlineKeyboardButton(
                    "📢 CHANNELS",
                    callback_data="channels"
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ ADD GROUP",
                    url=group_add_link()
                ),
                InlineKeyboardButton(
                    "📢 ADD CHANNEL",
                    url=channel_add_link()
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 STATUS",
                    callback_data="stats"
                )
            ]
        ]
    )


async def send_main_menu(
    client,
    user_id,
    message=None
):

    groups = await get_total_groups()
    channels = await get_total_channels()

    text = (
        "🤖 **JOIN REQUEST MANAGER**\n\n"
        "Control your Telegram groups and "
        "channels from this private bot.\n\n"
        f"👥 Groups: `{groups}`\n"
        f"📢 Channels: `{channels}`\n\n"
        "👇 Choose an option:"
    )

    if message:

        await message.edit_text(
            text,
            reply_markup=main_keyboard()
        )

    else:

        await client.send_message(
            user_id,
            text,
            reply_markup=main_keyboard()
        )


# =========================================================
# PERMISSION CHECK
# =========================================================

async def can_control_chat(
    client,
    user_id,
    chat_id
):

    if user_id == OWNER_ID:
        return True

    try:

        member = await client.get_chat_member(
            chat_id,
            user_id
        )

        if member.status not in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR
        ):
            return False

        if (
            member.status
            == ChatMemberStatus.ADMINISTRATOR
        ):

            privileges = member.privileges

            if not privileges:
                return False

            if not privileges.can_invite_users:
                return False

        bot_member = await client.get_chat_member(
            chat_id,
            "me"
        )

        if bot_member.status not in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR
        ):
            return False

        bot_privileges = bot_member.privileges

        if not bot_privileges:
            return False

        if not bot_privileges.can_invite_users:
            return False

        return True

    except Exception as e:

        LOGGER.error(
            f"Permission error "
            f"{chat_id}: {e}"
        )

        return False


# =========================================================
# CHAT MENU
# =========================================================

async def show_chat_menu(
    client,
    callback,
    chat_id
):

    if not await can_control_chat(
        client,
        callback.from_user.id,
        chat_id
    ):

        await callback.answer(
            "❌ You don't have permission.",
            show_alert=True
        )

        return

    info = await get_chat_info(
        chat_id
    )

    if not info:

        await callback.answer(
            "❌ Chat not found.",
            show_alert=True
        )

        return

    title = info.get(
        "title",
        "Unknown"
    )

    chat_type = info.get(
        "type",
        "group"
    )

    pending = await get_pending_count(
        chat_id
    )

    auto = await get_auto_approve(
        chat_id
    )

    icon = (
        "📢"
        if chat_type == "channel"
        else
        "👥"
    )

    back = (
        "channels"
        if chat_type == "channel"
        else
        "groups"
    )

    text = (
        f"{icon} **{title}**\n\n"
        f"🆔 `{chat_id}`\n"
        f"📥 Pending: `{pending:,}`\n"
        f"⚡ Auto Approve: "
        f"`{'ON' if auto else 'OFF'}`\n\n"
        "👇 Choose an option:"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    (
                        "🔴 AUTO APPROVE OFF"
                        if auto
                        else
                        "🟢 AUTO APPROVE ON"
                    ),
                    callback_data=f"toggle:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "👤 APPROVE MEMBERS",
                    callback_data=f"approve_menu:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑 REMOVE REQUESTS",
                    callback_data=f"remove:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⏹ STOP",
                    callback_data=f"stop:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 BACK",
                    callback_data=back
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


# =========================================================
# CHAT LIST
# =========================================================

async def show_chat_list(
    callback,
    chat_type
):

    if chat_type == "channel":

        chats = await get_all_channels()

        title = "📢 **YOUR CHANNELS**"

    else:

        chats = await get_all_groups()

        title = "👥 **YOUR GROUPS**"

    buttons = []

    for chat in chats:

        name = chat.get(
            "title",
            "Unknown"
        )

        chat_id = chat.get(
            "chat_id"
        )

        if len(name) > 35:
            name = name[:32] + "..."

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🔹 {name}",
                    callback_data=f"chat:{chat_id}"
                )
            ]
        )

    if not buttons:

        buttons.append(
            [
                InlineKeyboardButton(
                    (
                        "📢 ADD CHANNEL"
                        if chat_type == "channel"
                        else
                        "➕ ADD GROUP"
                    ),
                    url=(
                        channel_add_link()
                        if chat_type == "channel"
                        else
                        group_add_link()
                    )
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "🔙 BACK",
                callback_data="main"
            )
        ]
    )

    await callback.message.edit_text(
        title,
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )

    await callback.answer()


# =========================================================
# CALLBACKS
# =========================================================

@app.on_callback_query()
async def callback_handler(
    client,
    callback
):

    data = callback.data

    try:

        # MAIN
        if data == "main":

            await send_main_menu(
                client,
                callback.from_user.id,
                callback.message
            )

            await callback.answer()
            return

        # GROUPS
        if data == "groups":

            await show_chat_list(
                callback,
                "group"
            )

            return

        # CHANNELS
        if data == "channels":

            await show_chat_list(
                callback,
                "channel"
            )

            return

        # STATS
        if data == "stats":

            users = await get_total_users()
            started = await get_started_users()
            groups = await get_total_groups()
            channels = await get_total_channels()

            text = (
                "📊 **BOT STATUS**\n\n"
                f"👤 Total Users: `{users:,}`\n"
                f"▶️ Started Users: `{started:,}`\n"
                f"👥 Groups: `{groups:,}`\n"
                f"📢 Channels: `{channels:,}`"
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 BACK",
                            callback_data="main"
                        )
                    ]
                ]
            )

            await callback.message.edit_text(
                text,
                reply_markup=keyboard
            )

            await callback.answer()
            return

        # CHAT
        if data.startswith("chat:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            await show_chat_menu(
                client,
                callback,
                chat_id
            )

            return

        # TOGGLE AUTO APPROVE
        if data.startswith("toggle:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            if not await can_control_chat(
                client,
                callback.from_user.id,
                chat_id
            ):

                await callback.answer(
                    "❌ No permission.",
                    show_alert=True
                )

                return

            current = await get_auto_approve(
                chat_id
            )

            new_status = not current

            await set_auto_approve(
                chat_id,
                new_status
            )

            await callback.answer(
                (
                    "🟢 AUTO APPROVE ON"
                    if new_status
                    else
                    "🔴 AUTO APPROVE OFF"
                ),
                show_alert=True
            )

            await show_chat_menu(
                client,
                callback,
                chat_id
            )

            return

        # APPROVE MENU
        if data.startswith("approve_menu:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            if not await can_control_chat(
                client,
                callback.from_user.id,
                chat_id
            ):

                await callback.answer(
                    "❌ No permission.",
                    show_alert=True
                )

                return

            await callback.message.edit_text(
                "👤 **APPROVE MEMBERS**\n\n"
                "Use this command in private chat:\n\n"
                "`/approve CHAT_ID NUMBER`\n\n"
                "Examples:\n"
                "`/approve -1001234567890 100`\n"
                "`/approve -1001234567890 1k`\n"
                "`/approve -1001234567890 10k`\n"
                "`/approve -1001234567890 1m`\n\n"
                "♾️ No artificial user limit."
            )

            await callback.answer()
            return

        # REMOVE
        if data.startswith("remove:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            if not await can_control_chat(
                client,
                callback.from_user.id,
                chat_id
            ):

                await callback.answer(
                    "❌ No permission.",
                    show_alert=True
                )

                return

            await remove_pending(
                client,
                callback.from_user.id,
                chat_id
            )

            await callback.answer(
                "🗑 Remove completed.",
                show_alert=True
            )

            await show_chat_menu(
                client,
                callback,
                chat_id
            )

            return

        # STOP
        if data.startswith("stop:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            task = running_tasks.get(
                chat_id
            )

            if task:

                task.cancel()

                running_tasks.pop(
                    chat_id,
                    None
                )

                await callback.answer(
                    "⏹ Approval stopped.",
                    show_alert=True
                )

            else:

                await callback.answer(
                    "ℹ️ No approval running.",
                    show_alert=True
                )

            return

    except Exception as e:

        LOGGER.exception(
            f"Callback error: {e}"
        )

        try:

            await callback.answer(
                "❌ Something went wrong.",
                show_alert=True
            )

        except Exception:
            pass


# =========================================================
# JOIN REQUEST
# =========================================================

@app.on_chat_join_request()
async def join_request_handler(
    client,
    request: ChatJoinRequest
):

    chat = request.chat
    user = request.from_user

    chat_id = chat.id
    user_id = user.id

    LOGGER.info(
        f"📥 NEW JOIN REQUEST | "
        f"User: {user_id} | "
        f"Chat: {chat_id}"
    )

    # -----------------------------------------------------
    # CHAT TYPE
    # -----------------------------------------------------

    chat_type = str(
        getattr(chat, "type", "group")
    ).lower()

    if "channel" in chat_type:

        db_type = "channel"

    elif "supergroup" in chat_type:

        db_type = "supergroup"

    else:

        db_type = "group"

    # -----------------------------------------------------
    # SAVE CHAT
    # -----------------------------------------------------

    await save_group(
        chat_id=chat_id,
        title=chat.title or "",
        chat_type=db_type,
        username=chat.username or ""
    )

    # -----------------------------------------------------
    # SAVE USER BEFORE START
    # -----------------------------------------------------

    await save_user(
        user_id=user_id,
        started=False,
        name=user.first_name or "",
        username=user.username or ""
    )

    # -----------------------------------------------------
    # SAVE REQUEST
    # -----------------------------------------------------

    await save_request(
        chat_id=chat_id,
        user_id=user_id,
        name=user.first_name or "",
        username=user.username or ""
    )

    # -----------------------------------------------------
    # AD
    # -----------------------------------------------------

    ad = await get_ad()

    # -----------------------------------------------------
    # VERIFICATION MESSAGE
    # -----------------------------------------------------

    mention = user.mention

    text = (
        f"👋 **Hello {mention}!**\n\n"
        "To join the chat, confirm that "
        "you are not a robot by tapping "
        "the button below. ⬇️\n\n"
    )

    if ad:

        text += (
            "📢 **Advertisement**\n\n"
            f"{ad}\n\n"
        )

    text += (
        "🤖 **I'm not a Robot**\n"
        "Tap the button below to continue."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🤖 I'm not a Robot ✅",
                    url=(
                        f"https://t.me/"
                        f"{bot_username}"
                        f"?start=human"
                    )
                )
            ]
        ]
    )

    # -----------------------------------------------------
    # SEND PRIVATE MESSAGE
    # -----------------------------------------------------

    try:

        await client.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard
        )

        LOGGER.info(
            f"📩 Verification sent | "
            f"{user_id}"
        )

    except Exception as e:

        LOGGER.error(
            f"DM failed {user_id}: {e}"
        )

    # -----------------------------------------------------
    # AUTO APPROVE
    # -----------------------------------------------------

    auto = await get_auto_approve(
        chat_id
    )

    if auto:

        try:

            await approve_join_request(
                chat_id,
                user_id
            )

            await delete_request(
                chat_id,
                user_id
            )

            LOGGER.info(
                f"✅ AUTO APPROVED | "
                f"{user_id}"
            )

        except Exception as e:

            LOGGER.error(
                f"Auto approve failed "
                f"{user_id}: {e}"
            )


# =========================================================
# BOT ADDED TO GROUP / CHANNEL
# =========================================================

@app.on_chat_member_updated()
async def bot_chat_member_update(
    client,
    update: ChatMemberUpdated
):

    try:

        new_member = update.new_chat_member

        if not new_member:
            return

        if not new_member.user:
            return

        if bot_id != new_member.user.id:
            return

        chat = update.chat
        status = new_member.status

        # -------------------------------------------------
        # BOT ADMIN
        # -------------------------------------------------

        if status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        ):

            chat_type = str(
                getattr(
                    chat,
                    "type",
                    "group"
                )
            ).lower()

            if "channel" in chat_type:

                db_type = "channel"

            elif "supergroup" in chat_type:

                db_type = "supergroup"

            else:

                db_type = "group"

            await save_group(
                chat_id=chat.id,
                title=chat.title or "",
                chat_type=db_type,
                username=chat.username or ""
            )

            LOGGER.info(
                f"✅ CHAT SAVED | "
                f"{chat.title} | "
                f"{chat.id} | "
                f"{db_type}"
            )

            try:

                await client.send_message(
                    OWNER_ID,
                    "✅ **CHAT ADDED**\n\n"
                    f"📌 {chat.title}\n"
                    f"🆔 `{chat.id}`\n"
                    f"📂 Type: `{db_type}`"
                )

            except Exception:
                pass

        # -------------------------------------------------
        # BOT LEFT
        # -------------------------------------------------

        elif status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.BANNED
        ):

            await delete_group(
                chat.id
            )

            LOGGER.info(
                f"🗑 CHAT REMOVED | "
                f"{chat.id}"
            )

    except Exception as e:

        LOGGER.exception(
            f"Chat member update error: {e}"
        )


# =========================================================
# START
# =========================================================

@app.on_message(
    filters.command("start")
    & filters.private
)
async def start_handler(
    client,
    message
):

    user = message.from_user

    if not user:
        return

    await save_user(
        user_id=user.id,
        started=True,
        name=user.first_name or "",
        username=user.username or ""
    )

    await mark_user_started(
        user.id
    )

    mention = user.mention

    text = (
        f"👋 **Hello {mention}!**\n\n"
        "🤖 **I'm Join Request Manager Bot.**\n\n"
        "I help Telegram groups and channels "
        "manage join requests quickly and "
        "automatically.\n\n"
        "⚡ **Fast Auto Approval**\n"
        "👥 **Bulk Join Request Management**\n"
        "📢 **Group & Channel Support**\n"
        "🛡️ **Simple Request Protection**\n"
        "💾 **Reliable Database System**\n\n"
        "✨ Thanks for using me!\n"
        "Choose an option below 👇"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Add Me To A Channel",
                    url=channel_add_link()
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 Add Me To A Group",
                    url=group_add_link()
                )
            ]
        ]
    )

    await message.reply_text(
        text,
        reply_markup=keyboard
    )


# =========================================================
# PANEL
# =========================================================

@app.on_message(
    filters.command("panel")
    & filters.private
)
async def panel_handler(
    client,
    message
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    await send_main_menu(
        client,
        message.from_user.id
    )


# =========================================================
# NUMBER PARSER
# =========================================================

def parse_number(value):

    value = value.lower().strip()

    try:

        if value.endswith("k"):

            return int(
                float(value[:-1]) * 1000
            )

        if value.endswith("m"):

            return int(
                float(value[:-1]) * 1000000
            )

        return int(value)

    except Exception:

        return None


# =========================================================
# BULK APPROVE
# =========================================================

async def bulk_approve_worker(
    client,
    user_id,
    chat_id,
    amount
):

    success = 0
    failed = 0

    try:

        await client.send_message(
            user_id,
            "🚀 **APPROVAL STARTED**\n\n"
            f"📢 Chat ID: `{chat_id}`\n"
            f"👤 Requested: `{amount:,}`\n\n"
            "⏳ Approving pending requests..."
        )

        # -------------------------------------------------
        # Process in batches.
        # No artificial maximum limit.
        # -------------------------------------------------

        remaining = amount

        while remaining > 0:

            batch_size = min(
                100,
                remaining
            )

            requests = await get_pending_requests(
                chat_id,
                batch_size
            )

            if not requests:
                break

            async def approve_one(req):

                nonlocal success
                nonlocal failed

                uid = req.get(
                    "user_id"
                )

                try:

                    await approve_join_request(
                        chat_id,
                        uid
                    )

                    await delete_request(
                        chat_id,
                        uid
                    )

                    success += 1

                except FloodWait as e:

                    await asyncio.sleep(
                        e.value
                    )

                    try:

                        await approve_join_request(
                            chat_id,
                            uid
                        )

                        await delete_request(
                            chat_id,
                            uid
                        )

                        success += 1

                    except Exception as retry_error:

                        failed += 1

                        LOGGER.error(
                            f"Retry failed "
                            f"{uid}: "
                            f"{retry_error}"
                        )

                except Exception as e:

                    failed += 1

                    LOGGER.error(
                        f"Approve failed "
                        f"{uid}: {e}"
                    )

            await asyncio.gather(
                *[
                    approve_one(req)
                    for req in requests
                ],
                return_exceptions=True
            )

            remaining -= len(requests)

            # Keep API traffic controlled.
            await asyncio.sleep(
                0.15
            )

        # -------------------------------------------------
        # COMPLETED
        # -------------------------------------------------

        await client.send_message(
            user_id,
            "✅ **APPROVAL COMPLETED**\n\n"
            f"📥 Requested: `{amount:,}`\n"
            f"✅ Approved: `{success:,}`\n"
            f"❌ Failed: `{failed:,}`\n"
            f"⏭️ Not Available: "
            f"`{max(0, amount - success - failed):,}`"
        )

    except asyncio.CancelledError:

        await client.send_message(
            user_id,
            "⏹ **APPROVAL STOPPED**\n\n"
            f"✅ Approved: `{success:,}`\n"
            f"❌ Failed: `{failed:,}`"
        )

        raise

    except Exception as e:

        LOGGER.exception(
            f"Bulk approval error: {e}"
        )

        await client.send_message(
            user_id,
            f"❌ **Approval Error**\n\n"
            f"`{e}`"
        )

    finally:

        running_tasks.pop(
            chat_id,
            None
        )


# =========================================================
# /APPROVE CHAT_ID NUMBER
# =========================================================

@app.on_message(
    filters.command("approve")
    & filters.private
)
async def approve_command(
    client,
    message
):

    args = message.command

    # EXACT:
    # /approve CHAT_ID NUMBER

    if len(args) < 3:

        await message.reply_text(
            "❌ **Wrong Format**\n\n"
            "Use:\n"
            "`/approve CHAT_ID NUMBER`\n\n"
            "Examples:\n"
            "`/approve -1001234567890 100`\n"
            "`/approve -1001234567890 1k`\n"
            "`/approve -1001234567890 10k`\n"
            "`/approve -1001234567890 1m`"
        )

        return

    try:

        chat_id = int(
            args[1]
        )

    except ValueError:

        await message.reply_text(
            "❌ Invalid CHAT_ID."
        )

        return

    amount = parse_number(
        args[2]
    )

    if not amount or amount <= 0:

        await message.reply_text(
            "❌ Invalid NUMBER."
        )

        return

    if not await can_control_chat(
        client,
        message.from_user.id,
        chat_id
    ):

        await message.reply_text(
            "❌ You don't have permission "
            "to control this chat."
        )

        return

    if chat_id in running_tasks:

        await message.reply_text(
            "⚠️ Approval is already running "
            "for this chat."
        )

        return

    task = asyncio.create_task(
        bulk_approve_worker(
            client,
            message.from_user.id,
            chat_id,
            amount
        )
    )

    running_tasks[
        chat_id
    ] = task


# =========================================================
# /AUTOAPPROVE CHAT_ID ON/OFF
# =========================================================

@app.on_message(
    filters.command("autoapprove")
    & filters.private
)
async def autoapprove_command(
    client,
    message
):

    args = message.command

    if len(args) < 3:

        await message.reply_text(
            "❌ **Wrong Format**\n\n"
            "Use:\n"
            "`/autoapprove CHAT_ID on`\n"
            "`/autoapprove CHAT_ID off`"
        )

        return

    try:

        chat_id = int(
            args[1]
        )

    except ValueError:

        await message.reply_text(
            "❌ Invalid CHAT_ID."
        )

        return

    status = args[2].lower()

    if status not in (
        "on",
        "off"
    ):

        await message.reply_text(
            "❌ Use only `on` or `off`."
        )

        return

    if not await can_control_chat(
        client,
        message.from_user.id,
        chat_id
    ):

        await message.reply_text(
            "❌ You don't have permission."
        )

        return

    enabled = status == "on"

    await set_auto_approve(
        chat_id,
        enabled
    )

    if enabled:

        await message.reply_text(
            "🟢 **AUTO APPROVE ON**\n\n"
            "New join requests will now be "
            "automatically approved."
        )

    else:

        await message.reply_text(
            "🔴 **AUTO APPROVE OFF**\n\n"
            "New join requests will no longer "
            "be automatically approved."
        )


# =========================================================
# STOP
# =========================================================

@app.on_message(
    filters.command("stop")
    & filters.private
)
async def stop_command(
    client,
    message
):

    args = message.command

    if len(args) < 2:

        await message.reply_text(
            "Usage:\n"
            "`/stop CHAT_ID`"
        )

        return

    try:

        chat_id = int(
            args[1]
        )

    except ValueError:

        await message.reply_text(
            "❌ Invalid CHAT_ID."
        )

        return

    if not await can_control_chat(
        client,
        message.from_user.id,
        chat_id
    ):

        await message.reply_text(
            "❌ You don't have permission."
        )

        return

    task = running_tasks.get(
        chat_id
    )

    if not task:

        await message.reply_text(
            "ℹ️ No approval task is running."
        )

        return

    task.cancel()

    running_tasks.pop(
        chat_id,
        None
    )

    await message.reply_text(
        "⏹ **APPROVAL STOPPED**"
    )


# =========================================================
# REMOVE FUNCTION
# =========================================================

async def remove_pending(
    client,
    user_id,
    chat_id
):

    if not await can_control_chat(
        client,
        user_id,
        chat_id
    ):

        await client.send_message(
            user_id,
            "❌ You don't have permission."
        )

        return

    total = 0
    failed = 0

    while True:

        requests = await get_pending_requests(
            chat_id,
            100
        )

        if not requests:
            break

        for req in requests:

            uid = req.get(
                "user_id"
            )

            try:

                await decline_join_request(
                    chat_id,
                    uid
                )

                await delete_request(
                    chat_id,
                    uid
                )

                total += 1

            except Exception as e:

                failed += 1

                LOGGER.error(
                    f"Remove failed "
                    f"{uid}: {e}"
                )

        await asyncio.sleep(
            0.15
        )

    await client.send_message(
        user_id,
        "🗑 **REMOVE COMPLETED**\n\n"
        f"✅ Removed: `{total:,}`\n"
        f"❌ Failed: `{failed:,}`"
    )


# =========================================================
# /REMOVE CHAT_ID
# =========================================================

@app.on_message(
    filters.command("remove")
    & filters.private
)
async def remove_command(
    client,
    message
):

    args = message.command

    if len(args) < 2:

        await message.reply_text(
            "Usage:\n"
            "`/remove CHAT_ID`"
        )

        return

    try:

        chat_id = int(
            args[1]
        )

    except ValueError:

        await message.reply_text(
            "❌ Invalid CHAT_ID."
        )

        return

    await remove_pending(
        client,
        message.from_user.id,
        chat_id
    )


# =========================================================
# SET AD
# =========================================================

@app.on_message(
    filters.command("setad")
    & filters.private
)
async def setad_command(
    client,
    message
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "Usage:\n"
            "`/setad Your advertisement text`"
        )

        return

    ad_text = message.text.split(
        " ",
        1
    )[1]

    await save_ad(
        ad_text
    )

    await message.reply_text(
        "✅ **Advertisement Saved**"
    )


# =========================================================
# DELETE AD
# =========================================================

@app.on_message(
    filters.command("delad")
    & filters.private
)
async def delad_command(
    client,
    message
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    await delete_ad()

    await message.reply_text(
        "🗑 **Advertisement Deleted**"
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
    message
):

    users = await get_total_users()
    started = await get_started_users()
    groups = await get_total_groups()
    channels = await get_total_channels()

    await message.reply_text(
        "📊 **BOT STATUS**\n\n"
        f"👤 Users: `{users:,}`\n"
        f"▶️ Started Users: `{started:,}`\n"
        f"👥 Groups: `{groups:,}`\n"
        f"📢 Channels: `{channels:,}`"
    )


# =========================================================
# GROUPS
# =========================================================

@app.on_message(
    filters.command("groups")
    & filters.private
)
async def groups_command(
    client,
    message
):

    chats = await get_all_groups()

    if not chats:

        await message.reply_text(
            "❌ No groups added."
        )

        return

    text = "👥 **YOUR GROUPS**\n\n"

    for chat in chats:

        text += (
            f"• **{chat.get('title', 'Unknown')}**\n"
            f"  `{chat.get('chat_id')}`\n\n"
        )

    await message.reply_text(
        text
    )


# =========================================================
# CHANNELS
# =========================================================

@app.on_message(
    filters.command("channels")
    & filters.private
)
async def channels_command(
    client,
    message
):

    chats = await get_all_channels()

    if not chats:

        await message.reply_text(
            "❌ No channels added."
        )

        return

    text = "📢 **YOUR CHANNELS**\n\n"

    for chat in chats:

        text += (
            f"• **{chat.get('title', 'Unknown')}**\n"
            f"  `{chat.get('chat_id')}`\n\n"
        )

    await message.reply_text(
        text
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
    message
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if not message.reply_to_message:

        await message.reply_text(
            "📢 Reply to a message and use:\n"
            "`/broadcast`"
        )

        return

    users = await get_all_users(
        started_only=True
    )

    chats = await get_all_chats()

    user_success = 0
    user_failed = 0

    chat_success = 0
    chat_failed = 0

    status = await message.reply_text(
        "📢 **BROADCAST STARTED**\n\n"
        f"👤 Users: `{len(users):,}`\n"
        f"👥 Groups/Channels: `{len(chats):,}`\n\n"
        "⏳ Please wait..."
    )

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    for user in users:

        uid = user.get(
            "user_id"
        )

        try:

            await message.reply_to_message.copy(
                chat_id=uid
            )

            user_success += 1

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await message.reply_to_message.copy(
                    chat_id=uid
                )

                user_success += 1

            except Exception:

                user_failed += 1

        except Exception as e:

            user_failed += 1

            LOGGER.error(
                f"Broadcast user "
                f"{uid}: {e}"
            )

            error = str(e).lower()

            if any(
                x in error
                for x in (
                    "blocked",
                    "deactivated",
                    "peer id invalid",
                    "user not found"
                )
            ):

                try:

                    await delete_user(
                        uid
                    )

                except Exception:
                    pass

        await asyncio.sleep(
            0.04
        )

    # -----------------------------------------------------
    # GROUPS / CHANNELS
    # -----------------------------------------------------

    for chat in chats:

        chat_id = chat.get(
            "chat_id"
        )

        try:

            await message.reply_to_message.copy(
                chat_id=chat_id
            )

            chat_success += 1

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await message.reply_to_message.copy(
                    chat_id=chat_id
                )

                chat_success += 1

            except Exception:

                chat_failed += 1

        except Exception as e:

            chat_failed += 1

            LOGGER.error(
                f"Broadcast chat "
                f"{chat_id}: {e}"
            )

        await asyncio.sleep(
            0.08
        )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    await status.edit_text(
        "✅ **BROADCAST COMPLETED**\n\n"
        "👤 **USERS**\n"
        "━━━━━━━━━━━━━━\n"
        f"Total: `{len(users):,}`\n"
        f"✅ Sent: `{user_success:,}`\n"
        f"❌ Failed: `{user_failed:,}`\n\n"
        "👥 **GROUPS / CHANNELS**\n"
        "━━━━━━━━━━━━━━\n"
        f"Total: `{len(chats):,}`\n"
        f"✅ Sent: `{chat_success:,}`\n"
        f"❌ Failed: `{chat_failed:,}`"
    )


# =========================================================
# STARTUP
# =========================================================

async def startup():

    global bot_username
    global bot_id

    me = await app.get_me()

    bot_username = me.username
    bot_id = me.id

    LOGGER.info(
        f"🤖 @{bot_username} Started successfully!"
    )

    LOGGER.info(
        "👥 Group + 📢 Channel support enabled"
    )

    LOGGER.info(
        "🔐 Private control panel enabled"
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        startup()
    )
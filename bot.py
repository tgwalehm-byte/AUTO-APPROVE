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
    delete_all_requests,
    get_pending_count
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "[%(asctime)s - %(levelname)s] "
        "- %(message)s"
    )
)

LOGGER = logging.getLogger(__name__)


# =========================================================
# ENV
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
# GLOBALS
# =========================================================

bot_username = None
bot_id = None

http_session = None

running_tasks = {}

# user_id -> chat_id
awaiting_add_count = {}


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


async def bot_api_call(method, data):

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
# JOIN REQUEST API
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
# ADD GROUP LINK
# =========================================================

def group_add_link():

    return (
        f"https://t.me/"
        f"{bot_username}"
        f"?startgroup&admin=invite_users"
    )


# =========================================================
# ADD CHANNEL LINK
# =========================================================

def channel_add_link():

    return (
        f"https://t.me/"
        f"{bot_username}"
        f"?startchannel&admin=invite_users"
    )


# =========================================================
# PRIVATE MAIN MENU
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
        "Control your Groups & Channels "
        "directly from this private bot.\n\n"
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
# CHAT ACCESS CHECK
# =========================================================

async def can_control_chat(
    client,
    user_id,
    chat_id
):

    # Owner has full access
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

        # User must have invite permission
        if (
            member.status
            == ChatMemberStatus.ADMINISTRATOR
        ):

            privileges = member.privileges

            if not privileges:
                return False

            if not privileges.can_invite_users:
                return False

        # Check bot permission
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
            f"Access check failed "
            f"{chat_id}: {e}"
        )

        return False


# =========================================================
# CHAT MENU
# =========================================================

async def chat_menu(
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

    info = await get_chat_info(chat_id)

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

    auto = await get_auto_approve(chat_id)

    pending = await get_pending_count(
        chat_id
    )

    if chat_type == "channel":
        icon = "📢"
    else:
        icon = "👥"

    text = (
        f"{icon} **{title}**\n\n"
        f"🆔 `{chat_id}`\n"
        f"📥 Pending Saved: `{pending}`\n"
        f"⚡ Auto Approve: "
        f"`{'ON' if auto else 'OFF'}`\n\n"
        "👇 Select an action:"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    (
                        "🔴 Turn OFF Auto Approve"
                        if auto
                        else
                        "🟢 Turn ON Auto Approve"
                    ),
                    callback_data=f"toggle:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "👤 Approve Members",
                    callback_data=f"approve:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑 Remove Requests",
                    callback_data=f"remove:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⏹ Stop",
                    callback_data=f"stop:{chat_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data=(
                        "channels"
                        if chat_type == "channel"
                        else
                        "groups"
                    )
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

        title = "📢 YOUR CHANNELS"

        back = "main"

    else:

        chats = await get_all_groups()

        title = "👥 YOUR GROUPS"

        back = "main"

    buttons = []

    for chat in chats:

        chat_id = chat.get("chat_id")
        name = chat.get(
            "title",
            "Unknown"
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
                        "📢 Add Channel"
                        if chat_type == "channel"
                        else
                        "➕ Add Group"
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
                "🔙 Back",
                callback_data=back
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
# CALLBACK HANDLER
# =========================================================

@app.on_callback_query()
async def callback_handler(
    client,
    callback
):

    data = callback.data
    user_id = callback.from_user.id

    try:

        # -----------------------------
        # MAIN
        # -----------------------------

        if data == "main":

            await send_main_menu(
                client,
                user_id,
                callback.message
            )

            await callback.answer()
            return

        # -----------------------------
        # GROUPS
        # -----------------------------

        if data == "groups":

            await show_chat_list(
                callback,
                "group"
            )

            return

        # -----------------------------
        # CHANNELS
        # -----------------------------

        if data == "channels":

            await show_chat_list(
                callback,
                "channel"
            )

            return

        # -----------------------------
        # STATS
        # -----------------------------

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
                            "🔙 Back",
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

        # -----------------------------
        # CHAT
        # -----------------------------

        if data.startswith("chat:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            await chat_menu(
                client,
                callback,
                chat_id
            )

            return

        # -----------------------------
        # TOGGLE
        # -----------------------------

        if data.startswith("toggle:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            if not await can_control_chat(
                client,
                user_id,
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

            await set_auto_approve(
                chat_id,
                not current
            )

            await callback.answer(
                (
                    "🟢 Auto Approve ON"
                    if not current
                    else
                    "🔴 Auto Approve OFF"
                )
            )

            await chat_menu(
                client,
                callback,
                chat_id
            )

            return

        # -----------------------------
        # APPROVE
        # -----------------------------

        if data.startswith("approve:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            if not await can_control_chat(
                client,
                user_id,
                chat_id
            ):

                await callback.answer(
                    "❌ No permission.",
                    show_alert=True
                )

                return

            awaiting_add_count[
                user_id
            ] = chat_id

            await callback.message.edit_text(
                "👤 **APPROVE MEMBERS**\n\n"
                "How many pending requests "
                "do you want to approve?\n\n"
                "Examples:\n"
                "`10`\n"
                "`100`\n"
                "`1k`\n"
                "`10k`\n\n"
                "Send the number now.\n\n"
                "Use `/cancel` to cancel."
            )

            await callback.answer()

            return

        # -----------------------------
        # REMOVE
        # -----------------------------

        if data.startswith("remove:"):

            chat_id = int(
                data.split(":", 1)[1]
            )

            if not await can_control_chat(
                client,
                user_id,
                chat_id
            ):

                await callback.answer(
                    "❌ No permission.",
                    show_alert=True
                )

                return

            requests = await get_pending_requests(
                chat_id,
                10000
            )

            if not requests:

                await callback.answer(
                    "No saved pending requests.",
                    show_alert=True
                )

                return

            count = 0

            for request in requests:

                uid = request.get(
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

                    count += 1

                except Exception as e:

                    LOGGER.error(
                        f"Remove error "
                        f"{uid}: {e}"
                    )

            await callback.answer(
                f"🗑 Removed {count} requests.",
                show_alert=True
            )

            await chat_menu(
                client,
                callback,
                chat_id
            )

            return

        # -----------------------------
        # STOP
        # -----------------------------

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
                    "No running task.",
                    show_alert=True
                )

            return

    except Exception as e:

        LOGGER.exception(
            f"Callback error: {e}"
        )

        await callback.answer(
            "❌ Something went wrong.",
            show_alert=True
        )


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

    # -----------------------------------------
    # SAVE CHAT
    # -----------------------------------------

    chat_type = str(
        getattr(chat, "type", "group")
    ).lower()

    if "channel" in chat_type:

        db_type = "channel"

    elif "supergroup" in chat_type:

        db_type = "supergroup"

    else:

        db_type = "group"

    await save_group(
        chat_id=chat_id,
        title=chat.title or "",
        chat_type=db_type,
        username=chat.username or ""
    )

    # -----------------------------------------
    # SAVE USER WITHOUT /START
    # -----------------------------------------

    await save_user(
        user_id=user_id,
        started=False,
        name=user.first_name or "",
        username=user.username or ""
    )

    # -----------------------------------------
    # SAVE REQUEST
    # -----------------------------------------

    await save_request(
        chat_id=chat_id,
        user_id=user_id,
        name=user.first_name or "",
        username=user.username or ""
    )

    # -----------------------------------------
    # GET AD
    # -----------------------------------------

    ad = await get_ad()

    # -----------------------------------------
    # USER MENTION
    # -----------------------------------------

    mention = user.mention

    # -----------------------------------------
    # MESSAGE
    # -----------------------------------------

    text = (
        f"👋 **Hello {mention}!**\n\n"
        "To join the chat, confirm that you "
        "are not a robot by tapping the "
        "button below. ⬇️\n\n"
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

    # -----------------------------------------
    # HUMAN BUTTON
    # -----------------------------------------

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

    # -----------------------------------------
    # SEND DM
    # -----------------------------------------

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

    # -----------------------------------------
    # AUTO APPROVE
    # -----------------------------------------

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
                f"✅ Auto approved | "
                f"{user_id}"
            )

        except Exception as e:

            LOGGER.error(
                f"Auto approve failed "
                f"{user_id}: {e}"
            )


# =========================================================
# BOT ADDED / REMOVED FROM GROUP / CHANNEL
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

        # Only react to our own bot status
        if bot_id != new_member.user.id:
            return

        chat = update.chat

        status = new_member.status

        # -----------------------------------------
        # BOT IS ADMIN
        # -----------------------------------------

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
                f"✅ CHAT ADDED | "
                f"{chat.title} | "
                f"{chat.id} | "
                f"{db_type}"
            )

            # Notify owner
            try:

                await client.send_message(
                    OWNER_ID,
                    "✅ **New Chat Added**\n\n"
                    f"📌 {chat.title}\n"
                    f"🆔 `{chat.id}`\n"
                    f"📂 Type: `{db_type}`"
                )

            except Exception:
                pass

        # -----------------------------------------
        # BOT LEFT
        # -----------------------------------------

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

    await mark_user_started(
        user.id
    )

    await save_user(
        user_id=user.id,
        started=True,
        name=user.first_name or "",
        username=user.username or ""
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
# PRIVATE PANEL
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
# CANCEL
# =========================================================

@app.on_message(
    filters.command("cancel")
    & filters.private
)
async def cancel_handler(
    client,
    message
):

    awaiting_add_count.pop(
        message.from_user.id,
        None
    )

    await message.reply_text(
        "❌ Cancelled."
    )


# =========================================================
# APPROVE WORKER
# =========================================================

async def bulk_approve_worker(
    client,
    user_id,
    chat_id,
    limit
):

    try:

        requests = await get_pending_requests(
            chat_id,
            limit
        )

        total = len(requests)

        if total == 0:

            await client.send_message(
                user_id,
                "❌ No saved pending requests "
                "found for this chat."
            )

            return

        await client.send_message(
            user_id,
            "⚡ **Bulk Approval Started**\n\n"
            f"📥 Requests: `{total:,}`\n\n"
            "⏳ Please wait..."
        )

        success = 0
        failed = 0

        # -----------------------------------------
        # BATCHES
        # -----------------------------------------

        for index in range(
            0,
            total,
            20
        ):

            batch = requests[
                index:index + 20
            ]

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

                except Exception as e:

                    failed += 1

                    LOGGER.error(
                        f"Approve failed "
                        f"{uid}: {e}"
                    )

            await asyncio.gather(
                *[
                    approve_one(req)
                    for req in batch
                ],
                return_exceptions=True
            )

            await asyncio.sleep(
                0.15
            )

        await client.send_message(
            user_id,
            "✅ **BULK APPROVAL COMPLETED**\n\n"
            f"📥 Total: `{total:,}`\n"
            f"✅ Approved: `{success:,}`\n"
            f"❌ Failed: `{failed:,}`"
        )

    except asyncio.CancelledError:

        await client.send_message(
            user_id,
            "⏹ **Bulk Approval Stopped.**"
        )

        raise

    except Exception as e:

        LOGGER.exception(
            f"Bulk error: {e}"
        )

        await client.send_message(
            user_id,
            f"❌ **Error**\n\n`{e}`"
        )

    finally:

        running_tasks.pop(
            chat_id,
            None
        )


# =========================================================
# NUMBER INPUT
# =========================================================

def parse_number(value):

    value = value.lower().strip()

    try:

        if value.endswith("k"):

            return int(
                float(
                    value[:-1]
                ) * 1000
            )

        if value.endswith("m"):

            return int(
                float(
                    value[:-1]
                ) * 1000000
            )

        return int(value)

    except Exception:

        return None


@app.on_message(
    filters.private
    & filters.text
    & ~filters.command(
        [
            "start",
            "panel",
            "cancel",
            "approve",
            "addmember",
            "stop",
            "remove",
            "setad",
            "delad",
            "broadcast",
            "status",
            "groups",
            "channels"
        ]
    )
)
async def number_input_handler(
    client,
    message
):

    user_id = message.from_user.id

    if user_id not in awaiting_add_count:
        return

    chat_id = awaiting_add_count.pop(
        user_id
    )

    value = parse_number(
        message.text
    )

    if not value or value <= 0:

        await message.reply_text(
            "❌ Invalid number.\n\n"
            "Example: `100`, `1k`, `10k`"
        )

        return

    if value > 100000:

        value = 100000

    if not await can_control_chat(
        client,
        user_id,
        chat_id
    ):

        await message.reply_text(
            "❌ You don't have permission."
        )

        return

    if chat_id in running_tasks:

        await message.reply_text(
            "⚠️ Approval is already running."
        )

        return

    task = asyncio.create_task(
        bulk_approve_worker(
            client,
            user_id,
            chat_id,
            value
        )
    )

    running_tasks[
        chat_id
    ] = task

    await message.reply_text(
        "🚀 **Approval task started.**"
    )


# =========================================================
# /APPROVE
# /APPROVE CHAT_ID
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

    if len(args) < 2:

        await message.reply_text(
            "Usage:\n"
            "`/approve CHAT_ID`"
        )

        return

    try:

        chat_id = int(args[1])

    except ValueError:

        await message.reply_text(
            "❌ Invalid chat ID."
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

    awaiting_add_count[
        message.from_user.id
    ] = chat_id

    await message.reply_text(
        "👤 Send the number to approve.\n\n"
        "Example: `100` or `1k`"
    )


# =========================================================
# /ADDMEMBER
# =========================================================

@app.on_message(
    filters.command("addmember")
    & filters.private
)
async def addmember_command(
    client,
    message
):

    args = message.command

    if len(args) < 3:

        await message.reply_text(
            "Usage:\n"
            "`/addmember CHAT_ID NUMBER`\n\n"
            "Example:\n"
            "`/addmember -1001234567890 100`"
        )

        return

    try:

        chat_id = int(args[1])

    except ValueError:

        await message.reply_text(
            "❌ Invalid chat ID."
        )

        return

    amount = parse_number(
        args[2]
    )

    if not amount or amount <= 0:

        await message.reply_text(
            "❌ Invalid number."
        )

        return

    if amount > 100000:
        amount = 100000

    if not await can_control_chat(
        client,
        message.from_user.id,
        chat_id
    ):

        await message.reply_text(
            "❌ You don't have permission."
        )

        return

    if chat_id in running_tasks:

        await message.reply_text(
            "⚠️ Already running."
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

    await message.reply_text(
        "🚀 Bulk approval started."
    )


# =========================================================
# /STOP
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

        chat_id = int(args[1])

    except ValueError:

        await message.reply_text(
            "❌ Invalid chat ID."
        )

        return

    task = running_tasks.get(
        chat_id
    )

    if not task:

        await message.reply_text(
            "ℹ️ No running approval."
        )

        return

    task.cancel()

    running_tasks.pop(
        chat_id,
        None
    )

    await message.reply_text(
        "⏹ **Approval stopped.**"
    )


# =========================================================
# /REMOVE
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

        chat_id = int(args[1])

    except ValueError:

        await message.reply_text(
            "❌ Invalid chat ID."
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

    requests = await get_pending_requests(
        chat_id,
        10000
    )

    success = 0

    for request in requests:

        uid = request.get(
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

            success += 1

        except Exception as e:

            LOGGER.error(
                f"Remove failed "
                f"{uid}: {e}"
            )

    await message.reply_text(
        "🗑 **REMOVE COMPLETED**\n\n"
        f"✅ Removed: `{success:,}`"
    )


# =========================================================
# /SETAD
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

    text = message.text.split(
        " ",
        1
    )[1]

    await save_ad(text)

    await message.reply_text(
        "✅ Advertisement saved."
    )


# =========================================================
# /DELAD
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
        "🗑 Advertisement deleted."
    )


# =========================================================
# /STATUS
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
        f"▶️ Started: `{started:,}`\n"
        f"👥 Groups: `{groups:,}`\n"
        f"📢 Channels: `{channels:,}`"
    )


# =========================================================
# /GROUPS
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
# /CHANNELS
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
# /BROADCAST
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
            "📢 **Broadcast**\n\n"
            "Reply to the message you want "
            "to broadcast and use `/broadcast`."
        )

        return

    users = await get_all_users(
        started_only=True
    )

    groups = await get_all_chats()

    user_success = 0
    user_failed = 0

    group_success = 0
    group_failed = 0

    status = await message.reply_text(
        "📢 **Broadcast Started**\n\n"
        f"👤 Users: `{len(users):,}`\n"
        f"👥 Groups/Channels: `{len(groups):,}`\n\n"
        "⏳ Please wait..."
    )

    # -----------------------------------------
    # USERS
    # -----------------------------------------

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
                word in error
                for word in (
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

    # -----------------------------------------
    # GROUPS / CHANNELS
    # -----------------------------------------

    for chat in groups:

        chat_id = chat.get(
            "chat_id"
        )

        try:

            await message.reply_to_message.copy(
                chat_id=chat_id
            )

            group_success += 1

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

            try:

                await message.reply_to_message.copy(
                    chat_id=chat_id
                )

                group_success += 1

            except Exception:

                group_failed += 1

        except Exception as e:

            group_failed += 1

            LOGGER.error(
                f"Broadcast chat "
                f"{chat_id}: {e}"
            )

        await asyncio.sleep(
            0.08
        )

    await status.edit_text(
        "✅ **BROADCAST COMPLETED**\n\n"
        "👤 **USERS**\n"
        "━━━━━━━━━━━━━━\n"
        f"Total: `{len(users):,}`\n"
        f"✅ Sent: `{user_success:,}`\n"
        f"❌ Failed: `{user_failed:,}`\n\n"
        "👥 **GROUPS / CHANNELS**\n"
        "━━━━━━━━━━━━━━\n"
        f"Total: `{len(groups):,}`\n"
        f"✅ Sent: `{group_success:,}`\n"
        f"❌ Failed: `{group_failed:,}`"
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

    app.start()

    try:

        loop = asyncio.get_event_loop()

        loop.run_until_complete(
            startup()
        )

        idle = asyncio.Event()

        try:

            loop.run_until_complete(
                idle.wait()
            )

        except KeyboardInterrupt:

            pass

    finally:

        try:

            app.stop()

        except Exception:
            pass
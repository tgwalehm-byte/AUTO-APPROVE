import os
import asyncio
import logging
import aiohttp

from pyrogram import Client, filters, idle
from pyrogram.types import (
    ChatJoinRequest,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import FloodWait, RPCError, UserIsBlocked, PeerIdInvalid

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
    get_pending_count,
)


# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] - %(levelname)s - %(name)s - %(message)s",
)

LOGGER = logging.getLogger("JoinRequestManager")


# ============================================================
# CLIENT
# ============================================================

app = Client(
    "JoinRequestManagerBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


# ============================================================
# GLOBALS
# ============================================================

bot_username = None
bot_id = None
http_session = None

# chat_id -> running asyncio task
running_tasks = {}

# user_id -> chat_id
awaiting_addmember = {}


# ============================================================
# HELPERS
# ============================================================

def mention(user):
    name = user.first_name or "User"

    if user.last_name:
        name += f" {user.last_name}"

    return f"[{name}](tg://user?id={user.id})"


def get_chat_type(chat):
    if chat.type == ChatType.CHANNEL:
        return "channel"

    if chat.type == ChatType.SUPERGROUP:
        return "supergroup"

    if chat.type == ChatType.GROUP:
        return "group"

    return "unknown"


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


# ============================================================
# NUMBER PARSER
# ============================================================

def parse_number(value):
    """
    Examples:
    10
    100
    1k
    10k
    1m
    2.5k
    """

    if not value:
        return None

    value = str(value).strip().lower()
    value = value.replace(",", "")

    try:
        if value.endswith("k"):
            number = float(value[:-1]) * 1000

        elif value.endswith("m"):
            number = float(value[:-1]) * 1000000

        elif value.endswith("b"):
            number = float(value[:-1]) * 1000000000

        else:
            number = float(value)

        number = int(number)

        if number <= 0:
            return None

        return number

    except Exception:
        return None


# ============================================================
# TELEGRAM BOT API
# ============================================================

async def bot_api(method, payload):
    global http_session

    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    async with http_session.post(
        url,
        json=payload,
    ) as response:

        data = await response.json()

        if not data.get("ok"):
            raise RuntimeError(
                data.get("description", "Telegram API error")
            )

        return data


async def approve_request(chat_id, user_id):
    return await bot_api(
        "approveChatJoinRequest",
        {
            "chat_id": chat_id,
            "user_id": user_id,
        },
    )


async def decline_request(chat_id, user_id):
    return await bot_api(
        "declineChatJoinRequest",
        {
            "chat_id": chat_id,
            "user_id": user_id,
        },
    )


# ============================================================
# PERMISSION CHECK
# ============================================================

async def can_control_chat(user_id, chat_id):

    if user_id == OWNER_ID:
        user_is_allowed = True
    else:
        user_is_allowed = False

        try:
            member = await app.get_chat_member(
                chat_id,
                user_id,
            )

            if member.status == ChatMemberStatus.OWNER:
                user_is_allowed = True

            elif member.status == ChatMemberStatus.ADMINISTRATOR:
                user_is_allowed = bool(
                    getattr(
                        member,
                        "can_invite_users",
                        False,
                    )
                )

        except Exception as e:
            LOGGER.warning(
                f"User permission check failed "
                f"{user_id}/{chat_id}: {e}"
            )

    if not user_is_allowed:
        return False

    # Check bot permission
    try:
        bot_member = await app.get_chat_member(
            chat_id,
            bot_id,
        )

        if bot_member.status == ChatMemberStatus.OWNER:
            return True

        if bot_member.status == ChatMemberStatus.ADMINISTRATOR:

            return bool(
                getattr(
                    bot_member,
                    "can_invite_users",
                    False,
                )
            )

        return False

    except Exception as e:
        LOGGER.warning(
            f"Bot permission check failed "
            f"{chat_id}: {e}"
        )

        return False


# ============================================================
# MAIN PANEL
# ============================================================

def main_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 GROUPS",
                    callback_data="groups",
                ),
                InlineKeyboardButton(
                    "📢 CHANNELS",
                    callback_data="channels",
                ),
            ],
            [
                InlineKeyboardButton(
                    "➕ ADD GROUP",
                    url=group_add_link(),
                ),
                InlineKeyboardButton(
                    "➕ ADD CHANNEL",
                    url=channel_add_link(),
                ),
            ],
            [
                InlineKeyboardButton(
                    "📊 STATUS",
                    callback_data="status",
                )
            ],
        ]
    )


# ============================================================
# CHAT SETTINGS
# ============================================================

async def settings_text(chat_id):

    info = await get_chat_info(chat_id)

    if info:
        title = info.get(
            "title",
            "Unknown",
        )
        chat_type = info.get(
            "type",
            "unknown",
        )
    else:
        title = "Unknown"
        chat_type = "unknown"

    pending = await get_pending_count(
        chat_id
    )

    auto = await get_auto_approve(
        chat_id
    )

    auto_status = (
        "🟢 ON"
        if auto
        else
        "🔴 OFF"
    )

    return (
        f"⚙️ **{chat_type.upper()} SETTINGS**\n\n"
        f"📌 **{title}**\n"
        f"🆔 `{chat_id}`\n\n"
        f"⏳ Pending Requests: **{pending}**\n"
        f"🤖 Auto Approve: **{auto_status}**\n\n"
        "Choose an option below 👇"
    )


async def settings_keyboard(chat_id):

    auto = await get_auto_approve(
        chat_id
    )

    pending = await get_pending_count(
        chat_id
    )

    auto_text = (
        "🟢 APPROVE: ON"
        if auto
        else
        "🔴 APPROVE: OFF"
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    auto_text,
                    callback_data=f"auto:{chat_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 ADD MEMBER",
                    callback_data=f"add:{chat_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🛑 STOP",
                    callback_data=f"stop:{chat_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🗑 REMOVE ({pending})",
                    callback_data=f"remove:{chat_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 REFRESH",
                    callback_data=f"menu:{chat_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 BACK",
                    callback_data="home",
                )
            ],
        ]
    )


async def send_settings(user_id, chat_id):

    try:

        await app.send_message(
            user_id,
            await settings_text(chat_id),
            reply_markup=await settings_keyboard(
                chat_id
            ),
        )

    except Exception as e:

        LOGGER.error(
            f"Settings send error: {e}"
        )


# ============================================================
# START
# ============================================================

@app.on_message(
    filters.private & filters.command("start")
)
async def start_handler(client, message):

    user = message.from_user

    if not user:
        return

    await save_user(
        user.id,
        started=True,
        name=user.first_name or "",
        username=user.username or "",
    )

    await mark_user_started(
        user.id
    )

    text = (
        f"👋 **Hello {mention(user)}!**\n\n"
        "🤖 **I'm Join Request Manager Bot.**\n\n"
        "I help Telegram groups and channels "
        "manage join requests quickly and automatically.\n\n"
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
                    url=channel_add_link(),
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 Add Me To A Group",
                    url=group_add_link(),
                )
            ],
        ]
    )

    await message.reply_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================
# JOIN REQUEST
# ============================================================

@app.on_chat_join_request()
async def join_request_handler(
    client,
    request: ChatJoinRequest,
):

    chat = request.chat
    user = request.from_user

    try:

        chat_type = get_chat_type(
            chat
        )

        # Save chat
        await save_group(
            chat.id,
            title=chat.title or "",
            chat_type=chat_type,
            username=chat.username or "",
        )

        # Save user
        await save_user(
            user.id,
            started=False,
            name=user.first_name or "",
            username=user.username or "",
        )

        # Save request
        await save_request(
            chat.id,
            user.id,
            name=user.first_name or "",
            username=user.username or "",
        )

        LOGGER.info(
            f"📥 JOIN REQUEST | "
            f"chat={chat.id} | "
            f"user={user.id}"
        )

        # Get advertisement
        ad = await get_ad()

        text = (
            f"👋 **Hello {mention(user)}!**\n\n"
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
                        ),
                    )
                ]
            ]
        )

        # Send DM
        try:

            await app.send_message(
                user.id,
                text,
                reply_markup=keyboard,
            )

            LOGGER.info(
                f"📨 Verification message sent "
                f"to {user.id}"
            )

        except Exception as e:

            LOGGER.warning(
                f"⚠️ Cannot DM user "
                f"{user.id}: {e}"
            )

        # Auto approve
        auto = await get_auto_approve(
            chat.id
        )

        if auto:

            try:

                await approve_request(
                    chat.id,
                    user.id,
                )

                await delete_request(
                    chat.id,
                    user.id,
                )

                LOGGER.info(
                    f"✅ AUTO APPROVED | "
                    f"chat={chat.id} | "
                    f"user={user.id}"
                )

            except FloodWait as e:

                LOGGER.warning(
                    f"FloodWait {e.value}s"
                )

                await asyncio.sleep(
                    e.value
                )

                try:

                    await approve_request(
                        chat.id,
                        user.id,
                    )

                    await delete_request(
                        chat.id,
                        user.id,
                    )

                except Exception as retry_error:

                    LOGGER.error(
                        f"Auto approve retry failed: "
                        f"{retry_error}"
                    )

            except Exception as e:

                LOGGER.error(
                    f"❌ Auto approve failed: {e}"
                )

    except Exception as e:

        LOGGER.exception(
            f"❌ Join request handler error: {e}"
        )


# ============================================================
# BOT ADMIN STATUS UPDATE
# ============================================================

@app.on_chat_member_updated()
async def member_update_handler(
    client,
    update: ChatMemberUpdated,
):

    try:

        if not update.new_chat_member:
            return

        member_user = (
            update.new_chat_member.user
        )

        if not member_user:
            return

        # Only bot's own status
        if member_user.id != bot_id:
            return

        chat = update.chat

        new_status = (
            update.new_chat_member.status
        )

        LOGGER.info(
            f"🔄 BOT STATUS UPDATE | "
            f"chat={chat.id} | "
            f"status={new_status}"
        )

        # Bot became admin
        if new_status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):

            chat_type = get_chat_type(
                chat
            )

            await save_group(
                chat.id,
                title=chat.title or "",
                chat_type=chat_type,
                username=chat.username or "",
            )

            LOGGER.info(
                f"✅ CONNECTED | "
                f"{chat.title} | "
                f"{chat.id}"
            )

            # Automatically open settings
            # for the person who added/promoted bot
            if update.from_user:

                try:

                    await app.send_message(
                        update.from_user.id,
                        (
                            "🎉 **Bot Connected Successfully!**\n\n"
                            f"📌 **{chat.title}**\n"
                            f"🆔 `{chat.id}`\n"
                            f"📂 Type: **{chat_type}**\n\n"
                            "⚙️ Settings opened automatically 👇"
                        ),
                    )

                    await send_settings(
                        update.from_user.id,
                        chat.id,
                    )

                except Exception as e:

                    LOGGER.warning(
                        f"Could not open settings: {e}"
                    )

        # Bot removed
        elif new_status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.BANNED,
        ):

            await delete_group(
                chat.id
            )

            LOGGER.info(
                f"🗑 DISCONNECTED | "
                f"{chat.id}"
            )

    except Exception as e:

        LOGGER.exception(
            f"Member update error: {e}"
        )


# ============================================================
# CALLBACKS
# ============================================================

@app.on_callback_query()
async def callback_handler(
    client,
    query,
):

    user = query.from_user
    data = query.data

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if data == "home":

        if user.id != OWNER_ID:

            await query.answer(
                "❌ Owner only.",
                show_alert=True,
            )

            return

        await query.answer()

        await query.message.edit_text(
            "⚙️ **JOIN REQUEST MANAGER PANEL**\n\n"
            "Choose an option below 👇",
            reply_markup=main_keyboard(),
        )

        return

    # --------------------------------------------------------
    # GROUPS
    # --------------------------------------------------------

    if data == "groups":

        if user.id != OWNER_ID:

            await query.answer(
                "❌ Owner only.",
                show_alert=True,
            )

            return

        await query.answer()

        groups = await get_all_groups()

        buttons = []

        for group in groups:

            title = (
                group.get("title")
                or
                "Unknown Group"
            )

            chat_id = group["chat_id"]

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"👥 {title[:35]}",
                        callback_data=f"menu:{chat_id}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 BACK",
                    callback_data="home",
                )
            ]
        )

        if groups:

            text = (
                "👥 **CONNECTED GROUPS**\n\n"
                "Select a group:"
            )

        else:

            text = (
                "👥 **GROUPS**\n\n"
                "No connected groups."
            )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

        return

    # --------------------------------------------------------
    # CHANNELS
    # --------------------------------------------------------

    if data == "channels":

        if user.id != OWNER_ID:

            await query.answer(
                "❌ Owner only.",
                show_alert=True,
            )

            return

        await query.answer()

        channels = await get_all_channels()

        buttons = []

        for channel in channels:

            title = (
                channel.get("title")
                or
                "Unknown Channel"
            )

            chat_id = channel["chat_id"]

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"📢 {title[:35]}",
                        callback_data=f"menu:{chat_id}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 BACK",
                    callback_data="home",
                )
            ]
        )

        if channels:

            text = (
                "📢 **CONNECTED CHANNELS**\n\n"
                "Select a channel:"
            )

        else:

            text = (
                "📢 **CHANNELS**\n\n"
                "No connected channels."
            )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

        return

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    if data == "status":

        if user.id != OWNER_ID:

            await query.answer(
                "❌ Owner only.",
                show_alert=True,
            )

            return

        await query.answer()

        total_users = await get_total_users()
        started_users = await get_started_users()
        groups = await get_total_groups()
        channels = await get_total_channels()

        await query.message.edit_text(
            "📊 **BOT STATUS**\n\n"
            f"👤 Total Users: **{total_users}**\n"
            f"▶️ Started Users: **{started_users}**\n"
            f"👥 Groups: **{groups}**\n"
            f"📢 Channels: **{channels}**\n"
            f"⚙️ Running Jobs: **{len(running_tasks)}**\n\n"
            "🟢 **BOT ONLINE**",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 BACK",
                            callback_data="home",
                        )
                    ]
                ]
            ),
        )

        return

    # --------------------------------------------------------
    # CHAT MENU
    # --------------------------------------------------------

    if data.startswith("menu:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        if not await can_control_chat(
            user.id,
            chat_id,
        ):

            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )

            return

        await query.answer()

        await query.message.edit_text(
            await settings_text(chat_id),
            reply_markup=await settings_keyboard(
                chat_id
            ),
        )

        return

    # --------------------------------------------------------
    # AUTO APPROVE
    # --------------------------------------------------------

    if data.startswith("auto:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        if not await can_control_chat(
            user.id,
            chat_id,
        ):

            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )

            return

        current = await get_auto_approve(
            chat_id
        )

        new_value = not current

        await set_auto_approve(
            chat_id,
            new_value,
        )

        await query.answer(
            "🟢 Auto Approve ON"
            if new_value
            else
            "🔴 Auto Approve OFF"
        )

        await query.message.edit_text(
            await settings_text(chat_id),
            reply_markup=await settings_keyboard(
                chat_id
            ),
        )

        return

    # --------------------------------------------------------
    # ADD MEMBER
    # --------------------------------------------------------

    if data.startswith("add:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        if not await can_control_chat(
            user.id,
            chat_id,
        ):

            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )

            return

        awaiting_addmember[
            user.id
        ] = chat_id

        await query.answer()

        await query.message.reply_text(
            "👥 **How many members do you want to approve?**\n\n"
            "Send the number:\n\n"
            "`10`\n"
            "`20`\n"
            "`50`\n"
            "`1000`\n"
            "`1k`\n"
            "`10k`\n"
            "`1m`\n"
            "`1000000`\n\n"
            "Example: `1000`"
        )

        return

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    if data.startswith("stop:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        if not await can_control_chat(
            user.id,
            chat_id,
        ):

            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )

            return

        task = running_tasks.get(
            chat_id
        )

        if task and not task.done():

            task.cancel()

            running_tasks.pop(
                chat_id,
                None,
            )

            await query.answer(
                "🛑 Add Member stopped.",
                show_alert=True,
            )

        else:

            await query.answer(
                "ℹ️ No running job.",
                show_alert=True,
            )

        return

    # --------------------------------------------------------
    # REMOVE
    # --------------------------------------------------------

    if data.startswith("remove:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        if not await can_control_chat(
            user.id,
            chat_id,
        ):

            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )

            return

        await query.answer(
            "🗑 Checking requests..."
        )

        asyncio.create_task(
            remove_invalid_requests(
                chat_id,
                user.id,
            )
        )

        return


# ============================================================
# BULK APPROVE
# ============================================================

async def bulk_approve_worker(
    chat_id,
    amount,
    requester_id,
):

    approved = 0
    failed = 0

    LOGGER.info(
        f"🚀 BULK APPROVE STARTED | "
        f"chat={chat_id} | "
        f"target={amount}"
    )

    try:

        while approved < amount:

            remaining = (
                amount - approved
            )

            batch_size = min(
                100,
                remaining,
            )

            requests = await get_pending_requests(
                chat_id,
                limit=batch_size,
            )

            if not requests:

                LOGGER.info(
                    f"ℹ️ No pending saved "
                    f"requests left: {chat_id}"
                )

                break

            for req in requests:

                if chat_id not in running_tasks:
                    return

                user_id = req["user_id"]

                try:

                    await approve_request(
                        chat_id,
                        user_id,
                    )

                    await delete_request(
                        chat_id,
                        user_id,
                    )

                    approved += 1

                    LOGGER.info(
                        f"✅ APPROVED "
                        f"{approved}/{amount} | "
                        f"user={user_id}"
                    )

                except FloodWait as e:

                    LOGGER.warning(
                        f"⏳ FloodWait "
                        f"{e.value}s"
                    )

                    await asyncio.sleep(
                        e.value
                    )

                    continue

                except Exception as e:

                    failed += 1

                    LOGGER.warning(
                        f"❌ Approval failed "
                        f"user={user_id}: {e}"
                    )

                await asyncio.sleep(
                    0.05
                )

                if approved >= amount:
                    break

        try:

            await app.send_message(
                requester_id,
                (
                    "🏁 **ADD MEMBER FINISHED**\n\n"
                    f"📌 Chat: `{chat_id}`\n"
                    f"🎯 Requested: **{amount:,}**\n"
                    f"✅ Approved: **{approved:,}**\n"
                    f"❌ Failed: **{failed:,}**"
                ),
            )

        except Exception:
            pass

        LOGGER.info(
            f"🏁 BULK APPROVE FINISHED | "
            f"chat={chat_id} | "
            f"approved={approved}"
        )

    except asyncio.CancelledError:

        LOGGER.info(
            f"🛑 BULK APPROVE CANCELLED | "
            f"chat={chat_id}"
        )

        try:

            await app.send_message(
                requester_id,
                (
                    "🛑 **ADD MEMBER STOPPED**\n\n"
                    f"📌 Chat: `{chat_id}`\n"
                    f"✅ Approved before stop: "
                    f"**{approved:,}**"
                ),
            )

        except Exception:
            pass

    except Exception as e:

        LOGGER.exception(
            f"❌ Bulk worker error: {e}"
        )

    finally:

        running_tasks.pop(
            chat_id,
            None,
        )


# ============================================================
# PRIVATE TEXT
# ============================================================

@app.on_message(
    filters.private
    & filters.text
    & ~filters.command(
        [
            "start",
            "panel",
            "approve",
            "stop",
            "autoapprove",
            "remove",
            "setad",
            "delad",
            "status",
            "groups",
            "channels",
            "broadcast",
        ]
    )
)
async def private_text_handler(
    client,
    message,
):

    user = message.from_user

    if not user:
        return

    if user.id not in awaiting_addmember:
        return

    chat_id = awaiting_addmember.pop(
        user.id
    )

    amount = parse_number(
        message.text
    )

    if not amount:

        await message.reply_text(
            "❌ **Invalid number.**\n\n"
            "Try:\n"
            "`10`\n"
            "`100`\n"
            "`1k`\n"
            "`10k`\n"
            "`1m`"
        )

        awaiting_addmember[
            user.id
        ] = chat_id

        return

    if not await can_control_chat(
        user.id,
        chat_id,
    ):

        await message.reply_text(
            "❌ You don't have permission "
            "to control this chat."
        )

        return

    existing = running_tasks.get(
        chat_id
    )

    if existing and not existing.done():

        await message.reply_text(
            "⚠️ **ADD MEMBER is already running.**\n\n"
            "Press 🛑 STOP first."
        )

        return

    await message.reply_text(
        "🚀 **ADD MEMBER STARTED**\n\n"
        f"📌 Chat ID: `{chat_id}`\n"
        f"🎯 Target: **{amount:,}**\n\n"
        "🛑 Use STOP to cancel."
    )

    task = asyncio.create_task(
        bulk_approve_worker(
            chat_id,
            amount,
            user.id,
        )
    )

    running_tasks[
        chat_id
    ] = task


# ============================================================
# REMOVE INVALID REQUESTS
# ============================================================

async def remove_invalid_requests(
    chat_id,
    requester_id,
):

    checked = 0
    removed = 0

    try:

        requests = await get_pending_requests(
            chat_id,
            limit=100000,
        )

        for req in requests:

            user_id = req["user_id"]

            checked += 1

            invalid = False

            try:

                user = await app.get_users(
                    user_id
                )

                # Deleted Telegram account
                if getattr(
                    user,
                    "is_deleted",
                    False,
                ):
                    invalid = True

            except (
                PeerIdInvalid,
            ):

                invalid = True

            except Exception as e:

                LOGGER.debug(
                    f"User check failed "
                    f"{user_id}: {e}"
                )

            if invalid:

                try:

                    await decline_request(
                        chat_id,
                        user_id,
                    )

                    await delete_request(
                        chat_id,
                        user_id,
                    )

                    removed += 1

                    LOGGER.info(
                        f"🗑 REMOVED | "
                        f"user={user_id}"
                    )

                except FloodWait as e:

                    await asyncio.sleep(
                        e.value
                    )

                except Exception as e:

                    LOGGER.warning(
                        f"Remove failed "
                        f"{user_id}: {e}"
                    )

            await asyncio.sleep(
                0.05
            )

        try:

            await app.send_message(
                requester_id,
                (
                    "🗑 **REMOVE FINISHED**\n\n"
                    f"📌 Chat: `{chat_id}`\n"
                    f"🔎 Checked: **{checked:,}**\n"
                    f"🗑 Removed: **{removed:,}**"
                ),
            )

        except Exception:
            pass

    except Exception as e:

        LOGGER.exception(
            f"Remove error: {e}"
        )


# ============================================================
# /PANEL
# ============================================================

@app.on_message(
    filters.private & filters.command("panel")
)
async def panel_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ **Owner only.**"
        )

        return

    await message.reply_text(
        "⚙️ **JOIN REQUEST MANAGER PANEL**\n\n"
        "Choose an option below 👇",
        reply_markup=main_keyboard(),
    )


# ============================================================
# /APPROVE
# ============================================================

@app.on_message(
    filters.private & filters.command("approve")
)
async def approve_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ **Owner only.**"
        )

        return

    if len(message.command) != 3:

        await message.reply_text(
            "❌ **Wrong format**\n\n"
            "`/approve CHAT_ID NUMBER`\n\n"
            "Examples:\n"
            "`/approve -1001234567890 100`\n"
            "`/approve -1001234567890 1k`\n"
            "`/approve -1001234567890 1m`"
        )

        return

    try:

        chat_id = int(
            message.command[1]
        )

    except Exception:

        await message.reply_text(
            "❌ Invalid Chat ID."
        )

        return

    amount = parse_number(
        message.command[2]
    )

    if not amount:

        await message.reply_text(
            "❌ Invalid number."
        )

        return

    if not await can_control_chat(
        OWNER_ID,
        chat_id,
    ):

        await message.reply_text(
            "❌ Bot must be admin with "
            "**Invite Users** permission."
        )

        return

    existing = running_tasks.get(
        chat_id
    )

    if existing and not existing.done():

        await message.reply_text(
            "⚠️ Bulk approval already running."
        )

        return

    task = asyncio.create_task(
        bulk_approve_worker(
            chat_id,
            amount,
            OWNER_ID,
        )
    )

    running_tasks[
        chat_id
    ] = task

    await message.reply_text(
        "🚀 **ADD MEMBER STARTED**\n\n"
        f"📌 Chat: `{chat_id}`\n"
        f"🎯 Target: **{amount:,}**\n\n"
        "Use `/stop CHAT_ID` to stop."
    )


# ============================================================
# /STOP
# ============================================================

@app.on_message(
    filters.private & filters.command("stop")
)
async def stop_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) != 2:

        await message.reply_text(
            "`/stop CHAT_ID`"
        )

        return

    try:

        chat_id = int(
            message.command[1]
        )

    except Exception:

        await message.reply_text(
            "❌ Invalid Chat ID."
        )

        return

    task = running_tasks.get(
        chat_id
    )

    if not task or task.done():

        await message.reply_text(
            "ℹ️ No running job."
        )

        return

    task.cancel()

    running_tasks.pop(
        chat_id,
        None,
    )

    await message.reply_text(
        "🛑 **ADD MEMBER STOPPED**\n\n"
        f"Chat: `{chat_id}`"
    )


# ============================================================
# /AUTOAPPROVE
# ============================================================

@app.on_message(
    filters.private & filters.command(
        "autoapprove"
    )
)
async def autoapprove_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) != 3:

        await message.reply_text(
            "`/autoapprove CHAT_ID on`\n"
            "`/autoapprove CHAT_ID off`"
        )

        return

    try:

        chat_id = int(
            message.command[1]
        )

    except Exception:

        await message.reply_text(
            "❌ Invalid Chat ID."
        )

        return

    status = message.command[2].lower()

    if status not in (
        "on",
        "off",
    ):

        await message.reply_text(
            "❌ Use `on` or `off`."
        )

        return

    enabled = (
        status == "on"
    )

    await set_auto_approve(
        chat_id,
        enabled,
    )

    await message.reply_text(
        "🤖 **AUTO APPROVE**\n\n"
        f"Status: **"
        f"{'🟢 ON' if enabled else '🔴 OFF'}"
        f"**\n\n"
        f"Chat: `{chat_id}`"
    )


# ============================================================
# /REMOVE
# ============================================================

@app.on_message(
    filters.private & filters.command("remove")
)
async def remove_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) != 2:

        await message.reply_text(
            "`/remove CHAT_ID`"
        )

        return

    try:

        chat_id = int(
            message.command[1]
        )

    except Exception:

        await message.reply_text(
            "❌ Invalid Chat ID."
        )

        return

    if not await can_control_chat(
        OWNER_ID,
        chat_id,
    ):

        await message.reply_text(
            "❌ Bot permission missing."
        )

        return

    await message.reply_text(
        "🗑 **REMOVE STARTED**\n\n"
        "Checking invalid/deleted "
        "pending accounts..."
    )

    asyncio.create_task(
        remove_invalid_requests(
            chat_id,
            OWNER_ID,
        )
    )


# ============================================================
# /SETAD
# ============================================================

@app.on_message(
    filters.private & filters.command("setad")
)
async def setad_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "❌ Advertisement missing.\n\n"
            "Example:\n"
            "`/setad 🔥 Join our channel @example`"
        )

        return

    ad = message.text.split(
        None,
        1,
    )[1].strip()

    await save_ad(
        ad
    )

    await message.reply_text(
        "✅ **Advertisement Saved!**\n\n"
        "It will be shown in the "
        "join-request verification message."
    )


# ============================================================
# /DELAD
# ============================================================

@app.on_message(
    filters.private & filters.command("delad")
)
async def delad_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    await delete_ad()

    await message.reply_text(
        "🗑 **Advertisement Deleted!**"
    )


# ============================================================
# /STATUS
# ============================================================

@app.on_message(
    filters.private & filters.command("status")
)
async def status_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    users = await get_total_users()
    started = await get_started_users()
    groups = await get_total_groups()
    channels = await get_total_channels()

    await message.reply_text(
        "📊 **BOT STATUS**\n\n"
        f"👤 Total Users: **{users:,}**\n"
        f"▶️ Started Users: **{started:,}**\n"
        f"👥 Groups: **{groups:,}**\n"
        f"📢 Channels: **{channels:,}**\n"
        f"⚙️ Running Jobs: **{len(running_tasks)}**\n\n"
        "🟢 **BOT ONLINE**"
    )


# ============================================================
# /GROUPS
# ============================================================

@app.on_message(
    filters.private & filters.command("groups")
)
async def groups_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    groups = await get_all_groups()

    if not groups:

        await message.reply_text(
            "👥 **No groups connected.**"
        )

        return

    text = "👥 **CONNECTED GROUPS**\n\n"

    for i, group in enumerate(
        groups,
        start=1,
    ):

        text += (
            f"{i}. **{group.get('title', 'Unknown')}**\n"
            f"🆔 `{group['chat_id']}`\n\n"
        )

    await message.reply_text(
        text
    )


# ============================================================
# /CHANNELS
# ============================================================

@app.on_message(
    filters.private & filters.command(
        "channels"
    )
)
async def channels_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    channels = await get_all_channels()

    if not channels:

        await message.reply_text(
            "📢 **No channels connected.**"
        )

        return

    text = "📢 **CONNECTED CHANNELS**\n\n"

    for i, channel in enumerate(
        channels,
        start=1,
    ):

        text += (
            f"{i}. **{channel.get('title', 'Unknown')}**\n"
            f"🆔 `{channel['chat_id']}`\n\n"
        )

    await message.reply_text(
        text
    )


# ============================================================
# /BROADCAST
# ============================================================

@app.on_message(
    filters.private & filters.command(
        "broadcast"
    )
)
async def broadcast_command(
    client,
    message,
):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "❌ Message missing.\n\n"
            "Example:\n"
            "`/broadcast Hello everyone!`"
        )

        return

    broadcast_text = message.text.split(
        None,
        1,
    )[1].strip()

    await message.reply_text(
        "📢 **Broadcast Started...**"
    )

    users = await get_all_users(
        started_only=True
    )

    sent = 0
    failed = 0

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    for item in users:

        user_id = item["user_id"]

        try:

            await app.send_message(
                user_id,
                broadcast_text,
            )

            sent += 1

        except FloodWait as e:

            LOGGER.warning(
                f"Broadcast FloodWait "
                f"{e.value}s"
            )

            await asyncio.sleep(
                e.value
            )

        except (
            UserIsBlocked,
            PeerIdInvalid,
        ):

            failed += 1

            await delete_user(
                user_id
            )

        except Exception as e:

            failed += 1

            LOGGER.warning(
                f"Broadcast failed "
                f"{user_id}: {e}"
            )

        await asyncio.sleep(
            0.05
        )

    # --------------------------------------------------------
    # GROUPS + CHANNELS
    # --------------------------------------------------------

    chats = await get_all_chats()

    chat_sent = 0
    chat_failed = 0

    for chat in chats:

        chat_id = chat["chat_id"]

        try:

            await app.send_message(
                chat_id,
                broadcast_text,
            )

            chat_sent += 1

        except FloodWait as e:

            await asyncio.sleep(
                e.value
            )

        except Exception as e:

            chat_failed += 1

            LOGGER.warning(
                f"Chat broadcast failed "
                f"{chat_id}: {e}"
            )

        await asyncio.sleep(
            0.1
        )

    await message.reply_text(
        "🏁 **BROADCAST FINISHED**\n\n"
        f"👤 Users Sent: **{sent:,}**\n"
        f"❌ Users Failed: **{failed:,}**\n\n"
        f"👥📢 Chats Sent: **{chat_sent:,}**\n"
        f"❌ Chats Failed: **{chat_failed:,}**"
    )


# ============================================================
# STARTUP
# ============================================================

async def startup():

    global bot_username
    global bot_id
    global http_session

    me = await app.get_me()

    bot_username = me.username
    bot_id = me.id

    http_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(
            total=60
        )
    )

    LOGGER.info(
        "========================================"
    )

    LOGGER.info(
        f"🤖 @{bot_username} Started successfully!"
    )

    LOGGER.info(
        f"🆔 Bot ID: {bot_id}"
    )

    LOGGER.info(
        "👥 Group support enabled"
    )

    LOGGER.info(
        "📢 Channel support enabled"
    )

    LOGGER.info(
        "🤖 Auto Approve enabled"
    )

    LOGGER.info(
        "👥 Bulk Add Member enabled"
    )

    LOGGER.info(
        "🛑 Stop system enabled"
    )

    LOGGER.info(
        "🗑 Remove system enabled"
    )

    LOGGER.info(
        "📢 Advertisement system enabled"
    )

    LOGGER.info(
        "📣 Broadcast system enabled"
    )

    LOGGER.info(
        "💾 MongoDB enabled"
    )

    LOGGER.info(
        "🔐 Private panel enabled"
    )

    LOGGER.info(
        "========================================"
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    global http_session

    LOGGER.info(
        "🚀 Starting Telegram client..."
    )

    try:

        await app.start()

        await startup()

        LOGGER.info(
            "🟢 BOT IS ONLINE"
        )

        LOGGER.info(
            "📡 Waiting for Telegram updates..."
        )

        await idle()

    except Exception as e:

        LOGGER.exception(
            f"❌ FATAL ERROR: {e}"
        )

        raise

    finally:

        LOGGER.info(
            "🛑 Shutting down..."
        )

        if (
            http_session is not None
            and not http_session.closed
        ):

            await http_session.close()

        try:
            await app.stop()
        except Exception:
            pass

        LOGGER.info(
            "🔴 BOT STOPPED"
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        LOGGER.info(
            "Bot stopped manually."
        )

    except Exception as e:

        LOGGER.exception(
            f"Bot exited: {e}"
        )
# ============================================================
# 🤖 Join Request Manager Bot
# 🔹 Group + Channel Join Request Manager
# 🔹 Auto Approve / Bulk Approve / Remove / Broadcast
# ============================================================

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
from pyrogram.errors import (
    FloodWait,
    RPCError,
    UserIsBlocked,
    PeerIdInvalid,
    ChatAdminRequired,
    UserNotParticipant,
)

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
# PYROGRAM CLIENT
# ============================================================

app = Client(
    "JoinRequestManagerBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


# ============================================================
# GLOBAL VARIABLES
# ============================================================

bot_username = None
bot_id = None

http_session = None

# chat_id -> asyncio.Task
running_tasks = {}

# user_id -> chat_id
awaiting_addmember = {}


# ============================================================
# BASIC HELPERS
# ============================================================

def mention(user):
    name = user.first_name or "User"

    if user.last_name:
        name += f" {user.last_name}"

    return f"[{name}](tg://user?id={user.id})"


def chat_type_name(chat):
    if chat.type == ChatType.CHANNEL:
        return "channel"

    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        return "supergroup" if chat.type == ChatType.SUPERGROUP else "group"

    return "unknown"


def group_add_link():
    return f"https://t.me/{bot_username}?startgroup&admin=invite_users"


def channel_add_link():
    return f"https://t.me/{bot_username}?startchannel&admin=invite_users"


# ============================================================
# NUMBER PARSER
# ============================================================

def parse_number(value: str):
    """
    Supports:
    10
    100
    1k
    10k
    1m
    2.5k
    """

    value = value.strip().lower().replace(",", "")

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
# BOT API REQUEST HELPERS
# ============================================================

async def bot_api(method, payload):
    global http_session

    if http_session is None or http_session.closed:
        http_session = aiohttp.ClientSession()

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    async with http_session.post(
        url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as response:

        data = await response.json()

        if not data.get("ok"):
            raise RuntimeError(
                f"{method} failed: {data.get('description')}"
            )

        return data


async def approve_request(chat_id: int, user_id: int):
    return await bot_api(
        "approveChatJoinRequest",
        {
            "chat_id": chat_id,
            "user_id": user_id,
        },
    )


async def decline_request(chat_id: int, user_id: int):
    return await bot_api(
        "declineChatJoinRequest",
        {
            "chat_id": chat_id,
            "user_id": user_id,
        },
    )


# ============================================================
# OWNER CHECK
# ============================================================

def is_owner(user_id: int):
    return user_id == OWNER_ID


# ============================================================
# CHAT ACCESS CHECK
# ============================================================

async def can_control_chat(user_id: int, chat_id: int):
    # Owner can control everything
    if user_id == OWNER_ID:
        return True

    try:
        # User's permissions
        member = await app.get_chat_member(chat_id, user_id)

        if member.status not in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        ):
            return False

        if member.status == ChatMemberStatus.OWNER:
            user_can_invite = True
        else:
            user_can_invite = bool(
                getattr(member, "can_invite_users", False)
            )

        if not user_can_invite:
            return False

        # Bot permissions
        bot_member = await app.get_chat_member(chat_id, bot_id)

        if bot_member.status not in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        ):
            return False

        if bot_member.status == ChatMemberStatus.OWNER:
            bot_can_invite = True
        else:
            bot_can_invite = bool(
                getattr(bot_member, "can_invite_users", False)
            )

        return bot_can_invite

    except Exception as e:
        LOGGER.error(
            f"Permission check failed for {chat_id}: {e}"
        )
        return False


# ============================================================
# MAIN PANEL KEYBOARD
# ============================================================

def main_panel_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 GROUPS",
                    callback_data="panel_groups",
                ),
                InlineKeyboardButton(
                    "📢 CHANNELS",
                    callback_data="panel_channels",
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
                    callback_data="panel_status",
                )
            ],
        ]
    )


# ============================================================
# CHAT SETTINGS KEYBOARD
# ============================================================

async def chat_settings_keyboard(chat_id: int):
    auto = await get_auto_approve(chat_id)
    pending = await get_pending_count(chat_id)

    auto_text = "🟢 APPROVE: ON" if auto else "🔴 APPROVE: OFF"

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    auto_text,
                    callback_data=f"toggle_auto:{chat_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 ADD MEMBER",
                    callback_data=f"add_member:{chat_id}",
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
                    callback_data=f"chat_menu:{chat_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 BACK",
                    callback_data="panel_home",
                )
            ],
        ]
    )


async def chat_settings_text(chat_id: int):
    info = await get_chat_info(chat_id)

    if info:
        title = info.get("title") or "Unknown"
        chat_type = info.get("type") or "unknown"
    else:
        title = "Unknown"
        chat_type = "unknown"

    pending = await get_pending_count(chat_id)
    auto = await get_auto_approve(chat_id)

    auto_status = "🟢 ON" if auto else "🔴 OFF"

    return (
        f"⚙️ **{chat_type.upper()} SETTINGS**\n\n"
        f"📌 **{title}**\n"
        f"🆔 `{chat_id}`\n\n"
        f"⏳ Pending Requests: **{pending}**\n"
        f"🤖 Auto Approve: **{auto_status}**\n\n"
        "Choose an option below 👇"
    )


# ============================================================
# SEND SETTINGS
# ============================================================

async def send_chat_settings(user_id: int, chat_id: int):
    try:
        text = await chat_settings_text(chat_id)
        keyboard = await chat_settings_keyboard(chat_id)

        await app.send_message(
            user_id,
            text,
            reply_markup=keyboard,
        )

    except Exception as e:
        LOGGER.error(
            f"Unable to send settings to {user_id}: {e}"
        )


# ============================================================
# /START
# ============================================================

@app.on_message(filters.private & filters.command("start"))
async def start_command(client, message):

    user = message.from_user

    if not user:
        return

    await save_user(
        user.id,
        started=True,
        name=(user.first_name or ""),
        username=(user.username or ""),
    )

    await mark_user_started(user.id)

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
async def join_request_handler(client, request: ChatJoinRequest):

    chat = request.chat
    user = request.from_user

    try:
        chat_type = chat_type_name(chat)

        # Save chat
        await save_group(
            chat.id,
            title=chat.title or "",
            chat_type=chat_type,
            username=chat.username or "",
        )

        # Save user immediately
        await save_user(
            user.id,
            started=False,
            name=(user.first_name or ""),
            username=(user.username or ""),
        )

        # Save pending request
        await save_request(
            chat.id,
            user.id,
            name=(user.first_name or ""),
            username=(user.username or ""),
        )

        LOGGER.info(
            f"📥 Join request saved | "
            f"chat={chat.id} | "
            f"user={user.id} | "
            f"type={chat_type}"
        )

        # Advertisement
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
                        url=f"https://t.me/{bot_username}?start=human",
                    )
                ]
            ]
        )

        # Try sending request-time message
        try:
            await app.send_message(
                user.id,
                text,
                reply_markup=keyboard,
            )

            LOGGER.info(
                f"📨 Verification message sent to {user.id}"
            )

        except Exception as e:
            LOGGER.warning(
                f"⚠️ Cannot DM join requester {user.id}: {e}"
            )

        # Auto approve
        auto = await get_auto_approve(chat.id)

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
                    f"✅ Auto approved user={user.id} "
                    f"chat={chat.id}"
                )

            except FloodWait as e:
                LOGGER.warning(
                    f"FloodWait {e.value}s while auto approving"
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
# BOT ADDED / REMOVED FROM GROUP OR CHANNEL
# ============================================================

@app.on_chat_member_updated()
async def chat_member_updated(client, update: ChatMemberUpdated):

    try:

        # We only care about bot's own status
        if not update.new_chat_member:
            return

        member_user = update.new_chat_member.user

        if not member_user:
            return

        if member_user.id != bot_id:
            return

        chat = update.chat

        new_status = update.new_chat_member.status

        LOGGER.info(
            f"🔄 Bot membership update | "
            f"chat={chat.id} | "
            f"status={new_status}"
        )

        # Bot became admin/owner
        if new_status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ):

            chat_type = chat_type_name(chat)

            await save_group(
                chat.id,
                title=chat.title or "",
                chat_type=chat_type,
                username=chat.username or "",
            )

            LOGGER.info(
                f"✅ Bot connected to {chat_type}: "
                f"{chat.title} ({chat.id})"
            )

            # Automatically open settings for person
            if update.from_user:

                try:
                    await app.send_message(
                        update.from_user.id,
                        (
                            "🎉 **Bot Connected Successfully!**\n\n"
                            f"📌 **{chat.title}**\n"
                            f"🆔 `{chat.id}`\n"
                            f"📂 Type: **{chat_type}**\n\n"
                            "⚙️ Your settings panel is ready.\n"
                            "Choose what you want to do below 👇"
                        ),
                    )

                    await send_chat_settings(
                        update.from_user.id,
                        chat.id,
                    )

                except Exception as e:

                    LOGGER.warning(
                        f"Could not send auto settings: {e}"
                    )

        # Bot left/banned
        elif new_status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.BANNED,
        ):

            await delete_group(chat.id)

            LOGGER.info(
                f"🗑 Bot removed from chat {chat.id}"
            )

    except Exception as e:

        LOGGER.exception(
            f"Chat member update error: {e}"
        )


# ============================================================
# CALLBACK QUERY
# ============================================================

@app.on_callback_query()
async def callback_handler(client, query):

    user = query.from_user
    data = query.data

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if data == "panel_home":

        await query.answer()

        if user.id != OWNER_ID:
            await query.message.edit_text(
                "❌ **Owner only panel.**"
            )
            return

        await query.message.edit_text(
            "⚙️ **JOIN REQUEST MANAGER PANEL**\n\n"
            "Choose an option below 👇",
            reply_markup=main_panel_keyboard(),
        )

        return

    # --------------------------------------------------------
    # GROUP LIST
    # --------------------------------------------------------

    if data == "panel_groups":

        await query.answer()

        if user.id != OWNER_ID:
            await query.answer(
                "❌ Owner only.",
                show_alert=True,
            )
            return

        groups = await get_all_groups()

        buttons = []

        for group in groups:

            title = group.get("title") or "Unknown Group"
            chat_id = group["chat_id"]

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"👥 {title[:30]}",
                        callback_data=f"chat_menu:{chat_id}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 BACK",
                    callback_data="panel_home",
                )
            ]
        )

        if not groups:
            text = (
                "👥 **GROUPS**\n\n"
                "No connected groups found."
            )
        else:
            text = (
                "👥 **CONNECTED GROUPS**\n\n"
                "Select a group:"
            )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    # --------------------------------------------------------
    # CHANNEL LIST
    # --------------------------------------------------------

    if data == "panel_channels":

        await query.answer()

        if user.id != OWNER_ID:
            await query.answer(
                "❌ Owner only.",
                show_alert=True,
            )
            return

        channels = await get_all_channels()

        buttons = []

        for channel in channels:

            title = channel.get("title") or "Unknown Channel"
            chat_id = channel["chat_id"]

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"📢 {title[:30]}",
                        callback_data=f"chat_menu:{chat_id}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 BACK",
                    callback_data="panel_home",
                )
            ]
        )

        if not channels:
            text = (
                "📢 **CHANNELS**\n\n"
                "No connected channels found."
            )
        else:
            text = (
                "📢 **CONNECTED CHANNELS**\n\n"
                "Select a channel:"
            )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    if data == "panel_status":

        await query.answer()

        if user.id != OWNER_ID:
            await query.answer(
                "❌ Owner only.",
                show_alert=True,
            )
            return

        total_users = await get_total_users()
        started_users = await get_started_users()
        total_groups = await get_total_groups()
        total_channels = await get_total_channels()

        text = (
            "📊 **BOT STATUS**\n\n"
            f"👤 Total Users: **{total_users}**\n"
            f"▶️ Started Users: **{started_users}**\n"
            f"👥 Groups: **{total_groups}**\n"
            f"📢 Channels: **{total_channels}**\n"
            f"⚙️ Running Jobs: **{len(running_tasks)}**\n\n"
            "🟢 Bot is running."
        )

        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 BACK",
                            callback_data="panel_home",
                        )
                    ]
                ]
            ),
        )

        return

    # --------------------------------------------------------
    # CHAT MENU
    # --------------------------------------------------------

    if data.startswith("chat_menu:"):

        chat_id = int(data.split(":", 1)[1])

        allowed = await can_control_chat(
            user.id,
            chat_id,
        )

        if not allowed:
            await query.answer(
                "❌ You don't have permission.",
                show_alert=True,
            )
            return

        await query.answer()

        text = await chat_settings_text(chat_id)
        keyboard = await chat_settings_keyboard(chat_id)

        await query.message.edit_text(
            text,
            reply_markup=keyboard,
        )

        return

    # --------------------------------------------------------
    # AUTO APPROVE
    # --------------------------------------------------------

    if data.startswith("toggle_auto:"):

        chat_id = int(data.split(":", 1)[1])

        allowed = await can_control_chat(
            user.id,
            chat_id,
        )

        if not allowed:
            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )
            return

        current = await get_auto_approve(chat_id)

        new_status = not current

        await set_auto_approve(
            chat_id,
            new_status,
        )

        await query.answer(
            "🟢 Auto Approve ON"
            if new_status
            else "🔴 Auto Approve OFF"
        )

        text = await chat_settings_text(chat_id)
        keyboard = await chat_settings_keyboard(chat_id)

        await query.message.edit_text(
            text,
            reply_markup=keyboard,
        )

        return

    # --------------------------------------------------------
    # ADD MEMBER
    # --------------------------------------------------------

    if data.startswith("add_member:"):

        chat_id = int(data.split(":", 1)[1])

        allowed = await can_control_chat(
            user.id,
            chat_id,
        )

        if not allowed:
            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )
            return

        awaiting_addmember[user.id] = chat_id

        await query.answer()

        await query.message.reply_text(
            "👥 **How many members do you want to approve?**\n\n"
            "Send a number such as:\n\n"
            "`10`\n"
            "`20`\n"
            "`50`\n"
            "`1000`\n"
            "`1k`\n"
            "`10k`\n"
            "`1m`\n"
            "`1000000`\n\n"
            "📝 Example: `1000`"
        )

        return

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    if data.startswith("stop:"):

        chat_id = int(data.split(":", 1)[1])

        allowed = await can_control_chat(
            user.id,
            chat_id,
        )

        if not allowed:
            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )
            return

        task = running_tasks.get(chat_id)

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
                "ℹ️ No running Add Member job.",
                show_alert=True,
            )

        return

    # --------------------------------------------------------
    # REMOVE
    # --------------------------------------------------------

    if data.startswith("remove:"):

        chat_id = int(data.split(":", 1)[1])

        allowed = await can_control_chat(
            user.id,
            chat_id,
        )

        if not allowed:
            await query.answer(
                "❌ Permission denied.",
                show_alert=True,
            )
            return

        await query.answer(
            "🗑 Removing invalid requests..."
        )

        asyncio.create_task(
            remove_invalid_requests(
                chat_id,
                user.id,
            )
        )

        return


# ============================================================
# BULK APPROVE WORKER
# ============================================================

async def bulk_approve_worker(
    chat_id: int,
    amount: int,
    requester_id: int,
):

    approved = 0
    failed = 0

    LOGGER.info(
        f"🚀 Bulk approve started | "
        f"chat={chat_id} | amount={amount}"
    )

    try:

        while approved < amount:

            # Get remaining requests
            remaining = amount - approved

            # Process max 100 in one batch
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
                    f"ℹ️ No saved pending requests "
                    f"left for {chat_id}"
                )
                break

            # ------------------------------------------------
            # Approve one batch
            # ------------------------------------------------

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
                        f"✅ Approved "
                        f"{approved}/{amount} "
                        f"user={user_id}"
                    )

                    # Small delay prevents excessive flood
                    await asyncio.sleep(0.05)

                    if approved >= amount:
                        break

                except FloodWait as e:

                    LOGGER.warning(
                        f"⏳ FloodWait: "
                        f"{e.value}s"
                    )

                    await asyncio.sleep(
                        e.value
                    )

                except Exception as e:

                    failed += 1

                    LOGGER.warning(
                        f"❌ Failed approving "
                        f"{user_id}: {e}"
                    )

                    # Delete stale DB request
                    # only after actual Telegram failure
                    # is not necessarily safe, so keep it.
                    await asyncio.sleep(0.05)

        # ----------------------------------------------------
        # Completion message
        # ----------------------------------------------------

        try:

            await app.send_message(
                requester_id,
                (
                    "👥 **ADD MEMBER FINISHED**\n\n"
                    f"📌 Chat ID: `{chat_id}`\n"
                    f"✅ Approved: **{approved}**\n"
                    f"❌ Failed: **{failed}**\n"
                    f"🎯 Requested: **{amount}**"
                ),
            )

        except Exception:
            pass

        LOGGER.info(
            f"🏁 Bulk approve finished | "
            f"chat={chat_id} | "
            f"approved={approved} | "
            f"failed={failed}"
        )

    except asyncio.CancelledError:

        LOGGER.info(
            f"🛑 Bulk approve cancelled | "
            f"chat={chat_id}"
        )

        try:

            await app.send_message(
                requester_id,
                (
                    "🛑 **ADD MEMBER STOPPED**\n\n"
                    f"📌 Chat ID: `{chat_id}`\n"
                    f"✅ Approved before stop: **{approved}**"
                ),
            )

        except Exception:
            pass

    except Exception as e:

        LOGGER.exception(
            f"Bulk worker error: {e}"
        )

    finally:

        running_tasks.pop(
            chat_id,
            None,
        )


# ============================================================
# ADD MEMBER NUMBER HANDLER
# ============================================================

@app.on_message(filters.private & filters.text & ~filters.command())
async def private_text_handler(client, message):

    user = message.from_user

    if not user:
        return

    # Only process if waiting for amount
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
            "Send something like:\n"
            "`10`\n"
            "`100`\n"
            "`1k`\n"
            "`10k`\n"
            "`1m`"
        )

        # Allow retry
        awaiting_addmember[user.id] = chat_id

        return

    # Check permissions again
    allowed = await can_control_chat(
        user.id,
        chat_id,
    )

    if not allowed:

        await message.reply_text(
            "❌ You no longer have permission "
            "to control this chat."
        )

        return

    # Existing job?
    existing = running_tasks.get(
        chat_id
    )

    if existing and not existing.done():

        await message.reply_text(
            "⚠️ **ADD MEMBER is already running.**\n\n"
            "Use the 🛑 STOP button first."
        )

        return

    await message.reply_text(
        "🚀 **ADD MEMBER STARTED**\n\n"
        f"📌 Chat ID: `{chat_id}`\n"
        f"🎯 Target: **{amount:,}**\n\n"
        "🛑 You can stop it anytime from the "
        "STOP button."
    )

    task = asyncio.create_task(
        bulk_approve_worker(
            chat_id,
            amount,
            user.id,
        )
    )

    running_tasks[chat_id] = task


# ============================================================
# REMOVE INVALID REQUESTS
# ============================================================

async def remove_invalid_requests(
    chat_id: int,
    requester_id: int,
):

    removed = 0
    checked = 0

    try:

        # Read saved requests
        requests = await get_pending_requests(
            chat_id,
            limit=100000,
        )

        for req in requests:

            user_id = req["user_id"]

            checked += 1

            invalid = False

            try:

                # Get user information
                user = await app.get_users(
                    user_id
                )

                # Deleted account
                if getattr(
                    user,
                    "is_deleted",
                    False,
                ):
                    invalid = True

                # Try checking member state
                if not invalid:

                    try:

                        member = await app.get_chat_member(
                            chat_id,
                            user_id,
                        )

                        if member.status == ChatMemberStatus.BANNED:
                            invalid = True

                    except UserNotParticipant:
                        pass

                    except RPCError:
                        pass

            except (
                PeerIdInvalid,
                UserNotParticipant,
            ):
                invalid = True

            except Exception as e:

                LOGGER.debug(
                    f"User check failed {user_id}: {e}"
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
                        f"🗑 Removed invalid request "
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

            await asyncio.sleep(0.05)

        try:

            await app.send_message(
                requester_id,
                (
                    "🗑 **REMOVE FINISHED**\n\n"
                    f"📌 Chat ID: `{chat_id}`\n"
                    f"🔎 Checked: **{checked}**\n"
                    f"🗑 Removed: **{removed}**"
                ),
            )

        except Exception:
            pass

    except Exception as e:

        LOGGER.exception(
            f"Remove invalid error: {e}"
        )


# ============================================================
# /PANEL
# ============================================================

@app.on_message(
    filters.private & filters.command("panel")
)
async def panel_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ **Owner only.**"
        )

        return

    await message.reply_text(
        "⚙️ **JOIN REQUEST MANAGER PANEL**\n\n"
        "Choose an option below 👇",
        reply_markup=main_panel_keyboard(),
    )


# ============================================================
# /APPROVE CHAT_ID NUMBER
# ============================================================

@app.on_message(
    filters.private & filters.command("approve")
)
async def approve_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ **Owner only.**"
        )

        return

    if len(message.command) != 3:

        await message.reply_text(
            "❌ **Wrong format.**\n\n"
            "Use:\n"
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

    allowed = await can_control_chat(
        message.from_user.id,
        chat_id,
    )

    if not allowed:

        await message.reply_text(
            "❌ Bot is not admin with "
            "**Invite Users** permission "
            "or you don't have permission."
        )

        return

    existing = running_tasks.get(
        chat_id
    )

    if existing and not existing.done():

        await message.reply_text(
            "⚠️ A bulk approval is already "
            "running for this chat."
        )

        return

    task = asyncio.create_task(
        bulk_approve_worker(
            chat_id,
            amount,
            message.from_user.id,
        )
    )

    running_tasks[chat_id] = task

    await message.reply_text(
        "🚀 **ADD MEMBER STARTED**\n\n"
        f"📌 Chat: `{chat_id}`\n"
        f"🎯 Target: **{amount:,}**\n\n"
        "Use `/stop CHAT_ID` to stop it."
    )


# ============================================================
# /STOP CHAT_ID
# ============================================================

@app.on_message(
    filters.private & filters.command("stop")
)
async def stop_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) != 2:

        await message.reply_text(
            "Use:\n`/stop CHAT_ID`"
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
            "ℹ️ No running bulk approval."
        )

        return

    task.cancel()

    running_tasks.pop(
        chat_id,
        None,
    )

    await message.reply_text(
        f"🛑 **Stopped**\n\n"
        f"Chat: `{chat_id}`"
    )


# ============================================================
# /AUTOAPPROVE CHAT_ID ON/OFF
# ============================================================

@app.on_message(
    filters.private & filters.command("autoapprove")
)
async def autoapprove_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) != 3:

        await message.reply_text(
            "Use:\n"
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

    if status not in ("on", "off"):

        await message.reply_text(
            "❌ Use only `on` or `off`."
        )

        return

    enabled = status == "on"

    await set_auto_approve(
        chat_id,
        enabled,
    )

    await message.reply_text(
        f"🤖 **Auto Approve:** "
        f"{'🟢 ON' if enabled else '🔴 OFF'}\n\n"
        f"Chat: `{chat_id}`"
    )


# ============================================================
# /REMOVE CHAT_ID
# ============================================================

@app.on_message(
    filters.private & filters.command("remove")
)
async def remove_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) != 2:

        await message.reply_text(
            "Use:\n`/remove CHAT_ID`"
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

    allowed = await can_control_chat(
        OWNER_ID,
        chat_id,
    )

    if not allowed:

        await message.reply_text(
            "❌ Bot is not admin with "
            "Invite Users permission."
        )

        return

    await message.reply_text(
        "🗑 **REMOVE STARTED**\n\n"
        "Checking deleted/banned/unavailable "
        "pending requests..."
    )

    asyncio.create_task(
        remove_invalid_requests(
            chat_id,
            message.from_user.id,
        )
    )


# ============================================================
# /SETAD
# ============================================================

@app.on_message(
    filters.private & filters.command("setad")
)
async def setad_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "❌ **Advertisement missing.**\n\n"
            "Use:\n"
            "`/setad Your advertisement text here`"
        )

        return

    ad_text = message.text.split(
        None,
        1,
    )[1].strip()

    await save_ad(
        ad_text
    )

    await message.reply_text(
        "✅ **Advertisement saved successfully.**\n\n"
        "It will be included in the join-request "
        "verification message."
    )


# ============================================================
# /DELAD
# ============================================================

@app.on_message(
    filters.private & filters.command("delad")
)
async def delad_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    await delete_ad()

    await message.reply_text(
        "🗑 **Advertisement deleted successfully.**"
    )


# ============================================================
# /STATUS
# ============================================================

@app.on_message(
    filters.private & filters.command("status")
)
async def status_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    total_users = await get_total_users()
    started_users = await get_started_users()
    total_groups = await get_total_groups()
    total_channels = await get_total_channels()

    await message.reply_text(
        "📊 **BOT STATUS**\n\n"
        f"👤 Total Users: **{total_users}**\n"
        f"▶️ Started Users: **{started_users}**\n"
        f"👥 Groups: **{total_groups}**\n"
        f"📢 Channels: **{total_channels}**\n"
        f"⚙️ Running Jobs: **{len(running_tasks)}**\n\n"
        "🟢 **Bot is running.**"
    )


# ============================================================
# /GROUPS
# ============================================================

@app.on_message(
    filters.private & filters.command("groups")
)
async def groups_command(client, message):

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

    for index, group in enumerate(
        groups,
        start=1,
    ):

        text += (
            f"{index}. **{group.get('title', 'Unknown')}**\n"
            f"🆔 `{group['chat_id']}`\n\n"
        )

    await message.reply_text(
        text
    )


# ============================================================
# /CHANNELS
# ============================================================

@app.on_message(
    filters.private & filters.command("channels")
)
async def channels_command(client, message):

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

    for index, channel in enumerate(
        channels,
        start=1,
    ):

        text += (
            f"{index}. **{channel.get('title', 'Unknown')}**\n"
            f"🆔 `{channel['chat_id']}`\n\n"
        )

    await message.reply_text(
        text
    )


# ============================================================
# /BROADCAST
# ============================================================

@app.on_message(
    filters.private & filters.command("broadcast")
)
async def broadcast_command(client, message):

    if message.from_user.id != OWNER_ID:

        await message.reply_text(
            "❌ Owner only."
        )

        return

    if len(message.command) < 2:

        await message.reply_text(
            "❌ **Broadcast text missing.**\n\n"
            "Use:\n"
            "`/broadcast Your message here`"
        )

        return

    broadcast_text = message.text.split(
        None,
        1,
    )[1].strip()

    await message.reply_text(
        "📢 **Broadcast started...**"
    )

    users = await get_all_users(
        started_only=True
    )

    sent = 0
    failed = 0

    for user in users:

        user_id = user["user_id"]

        try:

            await app.send_message(
                user_id,
                broadcast_text,
            )

            sent += 1

        except FloodWait as e:

            LOGGER.warning(
                f"Broadcast FloodWait {e.value}s"
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
                f"Broadcast failed {user_id}: {e}"
            )

        await asyncio.sleep(
            0.05
        )

    # --------------------------------------------------------
    # Broadcast to saved groups/channels
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
        "📢 **BROADCAST FINISHED**\n\n"
        f"👤 Users Sent: **{sent}**\n"
        f"❌ User Failed: **{failed}**\n\n"
        f"👥/📢 Chats Sent: **{chat_sent}**\n"
        f"❌ Chat Failed: **{chat_failed}**"
    )


# ============================================================
# ERROR HANDLER
# ============================================================

@app.on_message(
    filters.private
)
async def private_error_protection(
    client,
    message,
):
    """
    This handler intentionally does nothing.
    It keeps normal private messages from causing
    unnecessary errors.
    """
    return


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
        "⚙️ Auto Approve enabled"
    )

    LOGGER.info(
        "👥 Bulk Add Member enabled"
    )

    LOGGER.info(
        "🛑 Stop system enabled"
    )

    LOGGER.info(
        "🗑 Remove invalid requests enabled"
    )

    LOGGER.info(
        "📢 Advertisement system enabled"
    )

    LOGGER.info(
        "📣 Broadcast system enabled"
    )

    LOGGER.info(
        "🔐 Private control panel enabled"
    )

    LOGGER.info(
        "💾 MongoDB enabled"
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
            "🟢 Bot is now ONLINE."
        )

        LOGGER.info(
            "📡 Waiting for Telegram updates..."
        )

        await idle()

    except Exception as e:

        LOGGER.exception(
            f"❌ FATAL BOT ERROR: {e}"
        )

        raise

    finally:

        LOGGER.info(
            "🛑 Shutting down bot..."
        )

        if http_session is not None:

            try:

                if not http_session.closed:
                    await http_session.close()

            except Exception:
                pass

        try:
            await app.stop()
        except Exception:
            pass

        LOGGER.info(
            "🔴 Bot stopped."
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        LOGGER.info(
            "Bot stopped by keyboard interrupt."
        )

    except Exception as e:

        LOGGER.exception(
            f"Bot exited with error: {e}"
        )
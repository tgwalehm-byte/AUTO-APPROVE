import asyncio
import logging

from pyrogram.errors import FloodWait

from database import (
    get_all_users,
    get_all_groups,
    delete_user
)


# =========================================================
# BROADCAST
# =========================================================

async def start_broadcast(
    client,
    message,
    status_message
):

    user_success = 0
    user_failed = 0

    group_success = 0
    group_failed = 0

    # =====================================================
    # GET USERS + GROUPS
    # =====================================================

    try:

        users = await get_all_users()
        groups = await get_all_groups()

    except Exception as e:

        logging.exception(
            f"Database error: {e}"
        )

        return await status_message.edit_text(
            f"❌ **Database Error**\n\n"
            f"`{e}`"
        )


    total_users = len(users)
    total_groups = len(groups)


    if total_users == 0 and total_groups == 0:

        return await status_message.edit_text(
            "❌ **Broadcast Failed**\n\n"
            "No users or groups found."
        )


    # =====================================================
    # START MESSAGE
    # =====================================================

    await status_message.edit_text(
        "📢 **Broadcast Started**\n\n"
        f"👤 Users: `{total_users:,}`\n"
        f"👥 Groups: `{total_groups:,}`\n\n"
        "⏳ Please wait..."
    )


    # =====================================================
    # USER BROADCAST
    # =====================================================

    for user in users:

        user_id = user.get(
            "user_id"
        )

        if not user_id:
            continue

        try:

            await message.copy(
                chat_id=user_id
            )

            user_success += 1

            await asyncio.sleep(
                0.10
            )


        except FloodWait as e:

            logging.warning(
                f"User FloodWait: {e.value}s"
            )

            await asyncio.sleep(
                e.value
            )

            try:

                await message.copy(
                    chat_id=user_id
                )

                user_success += 1

            except Exception as retry_error:

                user_failed += 1

                logging.error(
                    f"User retry failed "
                    f"{user_id}: {retry_error}"
                )


        except Exception as e:

            user_failed += 1

            error_text = str(e).lower()

            if any(
                word in error_text
                for word in (
                    "user is blocked",
                    "peer id invalid",
                    "input user deactivated",
                    "user deactivated",
                    "user not found"
                )
            ):

                try:

                    await delete_user(
                        user_id
                    )

                except Exception:

                    pass

            logging.error(
                f"User broadcast failed "
                f"{user_id}: {e}"
            )


    # =====================================================
    # GROUP BROADCAST
    # =====================================================

    for group in groups:

        chat_id = group.get(
            "chat_id"
        )

        if not chat_id:
            continue

        try:

            await message.copy(
                chat_id=chat_id
            )

            group_success += 1

            await asyncio.sleep(
                0.15
            )


        except FloodWait as e:

            logging.warning(
                f"Group FloodWait: {e.value}s"
            )

            await asyncio.sleep(
                e.value
            )

            try:

                await message.copy(
                    chat_id=chat_id
                )

                group_success += 1

            except Exception as retry_error:

                group_failed += 1

                logging.error(
                    f"Group retry failed "
                    f"{chat_id}: {retry_error}"
                )


        except Exception as e:

            group_failed += 1

            logging.error(
                f"Group broadcast failed "
                f"{chat_id}: {e}"
            )


    # =====================================================
    # FINAL REPORT
    # =====================================================

    total_success = (
        user_success +
        group_success
    )

    total_failed = (
        user_failed +
        group_failed
    )


    await status_message.edit_text(
        "✅ **BROADCAST COMPLETED**\n\n"

        "👤 **USERS**\n"
        "━━━━━━━━━━━━━━\n"
        f"Total: `{total_users:,}`\n"
        f"✅ Success: `{user_success:,}`\n"
        f"❌ Failed: `{user_failed:,}`\n\n"

        "👥 **GROUPS**\n"
        "━━━━━━━━━━━━━━\n"
        f"Total: `{total_groups:,}`\n"
        f"✅ Success: `{group_success:,}`\n"
        f"❌ Failed: `{group_failed:,}`\n\n"

        "📊 **TOTAL**\n"
        "━━━━━━━━━━━━━━\n"
        f"✅ Sent: `{total_success:,}`\n"
        f"❌ Failed: `{total_failed:,}`"
    )
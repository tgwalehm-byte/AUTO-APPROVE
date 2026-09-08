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

    success = 0
    failed = 0
    total = 0

    # Get all saved users
    users = await get_all_users()

    total = len(users)

    if total == 0:

        return await status_message.edit_text(
            "❌ **Broadcast Failed**\n\n"
            "No users found in database."
        )


    await status_message.edit_text(
        "📢 **Broadcast Started**\n\n"
        f"👥 Total Users: `{total:,}`\n"
        "⏳ Sending..."
    )


    for user in users:

        user_id = user["user_id"]

        try:

            # Copy the owner's replied message
            await message.copy(
                chat_id=user_id
            )

            success += 1

            await asyncio.sleep(0.08)


        except FloodWait as e:

            logging.warning(
                f"FloodWait: {e.value}s"
            )

            await asyncio.sleep(
                e.value
            )

            try:

                await message.copy(
                    chat_id=user_id
                )

                success += 1

            except Exception as error:

                failed += 1

                logging.error(
                    f"Retry failed {user_id}: {error}"
                )


        except Exception as e:

            failed += 1

            error_text = str(e).lower()

            # User blocked/deleted bot
            if any(
                x in error_text
                for x in [
                    "user is blocked",
                    "user not found",
                    "peer id invalid",
                    "input user deactivated",
                    "user deactivated",
                    "chat not found"
                ]
            ):

                try:

                    await delete_user(
                        user_id
                    )

                except Exception:

                    pass


            logging.error(
                f"Broadcast failed "
                f"{user_id}: {e}"
            )


    # =====================================================
    # GROUP COUNT
    # =====================================================

    try:

        groups = await get_all_groups()

        group_count = len(groups)

    except Exception as e:

        logging.error(
            f"Group count failed: {e}"
        )

        group_count = 0


    # =====================================================
    # FINAL REPORT
    # =====================================================

    await status_message.edit_text(
        "✅ **Broadcast Completed**\n\n"
        f"👥 Total Users: `{total:,}`\n"
        f"📨 Successful: `{success:,}`\n"
        f"❌ Failed: `{failed:,}`\n\n"
        f"👥 Total Groups: `{group_count:,}`"
    )
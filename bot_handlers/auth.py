import os
import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot_database import add_or_update_user, get_user
from bot_forwarder import SESSIONS_DIR, start_client_for_user

logger = logging.getLogger("bot.auth")
router = Router()

# In-memory auth state during OTP flow
auth_clients = {}


class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_otp = State()
    waiting_for_password = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    existing = auth_clients.pop(user_id, None)
    if existing:
        try:
            await existing["client"].disconnect()
        except Exception:
            pass

    user = await get_user(user_id)

    if user and user["auth_state"] == "CONNECTED":
        from bot_handlers.menu import show_main_menu
        await show_main_menu(message)
        return

    await message.answer(
        "╔══════════════════════════════════╗\n"
        "║   ⚡ Ultimate Autoforwarder      ║\n"
        "╚══════════════════════════════════╝\n\n"
        "Welcome! Connect your Telegram account to start.\n\n"
        "📱 Enter your phone number\n"
        "(international format, e.g. `+1234567890`):",
        parse_mode="Markdown"
    )
    await state.set_state(AuthStates.waiting_for_phone)


@router.message(AuthStates.waiting_for_phone, ~F.text.startswith('/'))
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    if not phone.startswith("+") or not phone[1:].isdigit():
        await message.answer("Invalid format. Please enter with country code (e.g. `+1234567890`):")
        return

    user_id = message.from_user.id
    await add_or_update_user(user_id, phone=phone, auth_state="PENDING")

    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    session_path = os.path.join(SESSIONS_DIR, f"user_{user_id}.session")

    if os.path.exists(session_path):
        try:
            os.remove(session_path)
        except OSError:
            pass

    from bot_forwarder import create_client
    client = create_client(user_id)
    await client.connect()

    try:
        sent_code = await client.send_code_request(phone)
        auth_clients[user_id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent_code.phone_code_hash,
        }
        await message.answer(
            "Code sent!\n\n"
            "**IMPORTANT: Enter the 5-digit OTP with SPACES between each number.**\n\n"
            "Example: If your code is `12345`, type: `1 2 3 4 5`\n\n"
            "This prevents Telegram from blocking your account for forwarding login codes.",
            parse_mode="Markdown"
        )
        await state.set_state(AuthStates.waiting_for_otp)
    except Exception as e:
        logger.error(f"Failed to send code for {user_id}: {e}")
        await message.answer("Failed to send code. Please check your phone number and try again with /start")
        await client.disconnect()
        await state.clear()


@router.message(AuthStates.waiting_for_otp, ~F.text.startswith('/'))
async def process_otp(message: Message, state: FSMContext):
    otp = message.text.strip().replace(" ", "").replace("-", "")
    user_id = message.from_user.id

    if user_id not in auth_clients:
        await message.answer("Session expired. Please use /start again.")
        await state.clear()
        return

    auth_data = auth_clients[user_id]
    client = auth_data["client"]
    phone = auth_data["phone"]
    phone_code_hash = auth_data["phone_code_hash"]

    try:
        logger.info(f"Sign_in attempt for user {user_id}")
        await client.sign_in(phone=phone, code=otp, phone_code_hash=phone_code_hash)
        logger.info(f"Sign_in success for user {user_id}")
        await _complete_auth(message, state, user_id, client)
    except Exception as e:
        logger.error(f"Sign_in error for {user_id}: {type(e).__name__} - {e}")
        if "password" in str(e).lower() or "SessionPasswordNeeded" in str(type(e)):
            await message.answer(
                "Your account has **Two-Step Verification** enabled.\n\n"
                "Please enter your password (type normally, no spaces needed):",
                parse_mode="Markdown"
            )
            await state.set_state(AuthStates.waiting_for_password)
        else:
            await message.answer("Sign in failed. Please try /start again.")
            await client.disconnect()
            del auth_clients[user_id]
            await state.clear()


@router.message(AuthStates.waiting_for_password, ~F.text.startswith('/'))
async def process_password(message: Message, state: FSMContext):
    password = message.text.strip()
    user_id = message.from_user.id

    if user_id not in auth_clients:
        await message.answer("Session expired. Please use /start again.")
        await state.clear()
        return

    auth_data = auth_clients[user_id]
    client = auth_data["client"]

    try:
        logger.info(f"Password sign_in for user {user_id}")
        await client.sign_in(password=password)
        logger.info(f"Password sign_in success for user {user_id}")
        await _complete_auth(message, state, user_id, client, delete_message=True)
    except Exception as e:
        logger.error(f"Password error for {user_id}: {type(e).__name__} - {e}")
        await message.answer("Password incorrect or verification failed. Try /start again.")
        await client.disconnect()
        del auth_clients[user_id]
        await state.clear()


async def _complete_auth(message: Message, state: FSMContext, user_id: int, client, delete_message=False):
    if delete_message:
        try:
            await message.delete()
        except Exception:
            pass

    await add_or_update_user(user_id, auth_state="CONNECTED")

    if user_id in auth_clients:
        del auth_clients[user_id]
    await state.clear()

    await message.answer(
        "✅  *Connected Successfully!*\n\n"
        "Your Telegram session is now linked.\n"
        "Opening main menu...",
        parse_mode="Markdown",
    )

    # Disconnect the auth client cleanly before starting the forwarder client
    await client.disconnect()

    # Start forwarder client in background
    asyncio.create_task(start_client_for_user(user_id))

    from bot_handlers.menu import show_main_menu
    await show_main_menu(message)

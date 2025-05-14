# ===----------------------------------------------------------------------=== #
#                    Enhanced Telegram File Share Bot                        #
# ===----------------------------------------------------------------------=== #

# 1. Environment Variable Loading (MUST be at the very top)
import os
from dotenv import load_dotenv
load_dotenv() # Loads .env file if present (for local testing), platform env vars take precedence

# 2. Keep Alive Import
from keep_alive import keep_alive # Assuming keep_alive.py is in the same directory

# 3. Standard Imports
import logging
import asyncio
from telegram import (
    Update,
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument, # Kept from original, use if needed for multiple files
    ChatMember          # For checking member status
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler, # For "Try Again" button
    ContextTypes,
    JobQueue,
    Defaults,
)
from telegram.constants import ParseMode, ChatMemberStatus # For status comparison
from telegram.error import TelegramError, Forbidden, BadRequest

# === Logging Setup ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING) # For Flask's server
logger = logging.getLogger(__name__)

# === Configuration ===
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME')
PRIVATE_CHANNEL_ID = os.getenv('PRIVATE_CHANNEL_ID') # For reference if needed later
PUBLIC_CHANNEL_ID_STR = os.getenv('PUBLIC_CHANNEL_ID')

try:
    PUBLIC_CHANNEL_ID = int(PUBLIC_CHANNEL_ID_STR) if PUBLIC_CHANNEL_ID_STR and PUBLIC_CHANNEL_ID_STR.startswith('-') else PUBLIC_CHANNEL_ID_STR
except (ValueError, TypeError): # Catch TypeError if PUBLIC_CHANNEL_ID_STR is None
    logger.error(f"PUBLIC_CHANNEL_ID ('{PUBLIC_CHANNEL_ID_STR}') is not valid. Bot might not function correctly.")
    PUBLIC_CHANNEL_ID = None

if not BOT_TOKEN:
    logger.critical("CRITICAL ERROR: BOT_TOKEN is not set.")
if not BOT_USERNAME:
    logger.warning("WARNING: BOT_USERNAME is not set. Deep links will be incorrect.")
if not PUBLIC_CHANNEL_ID:
    logger.critical("CRITICAL ERROR: PUBLIC_CHANNEL_ID is not properly configured or set.")

# --- File & Series/Season Configuration ---
SEASONS = {
    'apothecary_diaries_s1': [ # Example key
        'BQACAgQAAxkBAAEBEWhoImGp0GLWjLBTaJ90ZcIYtdFtvQACtSMAA1AZUQABXCxSF360SzYE',
        'BQACAgQAAxkBAAEBEX9oInhdz1T_S7sJEifWD91VL5vO7QACzyMAA1AZUZ107KoTZlUXNgQ',
        'BQACAgQAAxkBAAEBFY5oIyNYobHZHWWk2DJ2Hjkx99LgRAAC1CMAA1AZUdl6cVfp1NJENgQ',
        'BQACAgQAAxkBAAEBFZRoIyPO_rPhGaOyzbrB9C1i0kVQFAAC2CMAA1AZUdTTQh9FDanpNgQ',
        'BQACAgQAAxkBAAEBFZ5oIyRnTpQuMZmUL6G0WhoO5B4aTAAC7CMAA1AZUbD3Pqh5iI1gNgQ',
        'BQACAgQAAxkBAAEBFaRoIyUvMwXAz9PJcwM1IppLokbTxwAC_iMAA1AZUa4d5x39FGS6NgQ',
        'BQACAgQAAxkBAAEBFapoIyWcR6Le331xB_Hy3e3yyLuNlwAC_yMAA1AZUSGVkYFzvP5GNgQ',
        'BQACAgQAAxkBAAEBFa5oIyXqcbLkpRD8H0JIea1iQcBN9QACASQAA1AZUQIF8Id9ze3tNgQ',
        'BQACAgQAAxkBAAEBFbBoIyYNu-Oz0H_CmwSiouSiq2WESAACAyQAA1AZUZlu2B38psTBNgQ',
        'BQACAgQAAxkBAAEBFbJoIyY5Y0wmYpBtM6pl9f4HNN6XzwACBSQAA1AZUeb9OVa0RYU1NgQ',
        'BQACAgQAAxkBAAEBFbdoIyaq6xhaL0IQieSe4wakJd5WiQACBiQAA1AZUbUJS4dMKZIKNgQ',
        'BQACAgQAAxkBAAEBFbloIybcbew4-C-ALKSiyYbX0LvZzQACByQAA1AZUcm08Upui6CaNgQ',
        'BQACAgQAAxkBAAEBFcxoIyfdR-Q4uWTvvCYYJRK1vX129AACCCQAA1AZUUUV06vwTECfNgQ',
        'BQACAgQAAxkBAAEBFcxoIyfdR-Q4uWTvvCYYJRK1vX129AACCCQAA1AZUUUV06vwTECfNgQ',
        'BQACAgQAAxkBAAEBFdRoIyhfAWiiAUhdtrryj7NOjFW8pwACCiQAA1AZUfPBIAQINEVLNgQ',
        'BQACAgQAAxkBAAEBFdhoIyiVNqJxHKEkceFyPylG5vH0ugACCyQAA1AZUat5zS5woEANNgQ',
    ],
    'another_series_s2': [ # Renamed from 'season2' for clarity
        'FILE_ID_S02E01',
        'FILE_ID_S02E02',
    ],
}

# Creative Suggestion: Display names for prettier buttons
SEASONS_DISPLAY_NAMES = {
    'apothecary_diaries_s1': "Apothecary Diaries (S1 Dual 1080p)",
    'another_series_s2': "Another Series (Season 2)",
    # Add display names matching keys in SEASONS
}

DELETE_AFTER_SECONDS = 20 * 60
AUTO_SETUP_BUTTONS_ON_START = True

# === Helper Functions ===
async def is_user_member_of_public_channel(bot: Bot, user_id: int) -> bool:
    if not PUBLIC_CHANNEL_ID:
        logger.error("is_user_member_of_public_channel: PUBLIC_CHANNEL_ID not configured.")
        return False
    try:
        member = await bot.get_chat_member(chat_id=PUBLIC_CHANNEL_ID, user_id=user_id)
        allowed_statuses = [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED]
        if member.status in allowed_statuses:
            logger.info(f"User {user_id} is member of {PUBLIC_CHANNEL_ID} (Status: {member.status}).")
            return True
        logger.info(f"User {user_id} not active member of {PUBLIC_CHANNEL_ID} (Status: {member.status}).")
        return False
    except BadRequest as e:
        if "user not found" in str(e).lower() or "user_not_participant" in str(e).lower():
            logger.info(f"User {user_id} not found/participant in channel {PUBLIC_CHANNEL_ID}.")
        elif "chat not found" in str(e).lower():
            logger.error(f"Public channel {PUBLIC_CHANNEL_ID} not found. Check config. Error: {e}")
        else:
            logger.error(f"BadRequest checking membership for user {user_id} in {PUBLIC_CHANNEL_ID}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking membership for user {user_id}: {e}", exc_info=True)
        return False

async def send_join_channel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, requested_content_key: str):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    public_channel_display_name = str(PUBLIC_CHANNEL_ID) # Fallback
    if isinstance(PUBLIC_CHANNEL_ID, str) and PUBLIC_CHANNEL_ID.startswith('@'):
        public_channel_link = f"https://t.me/{PUBLIC_CHANNEL_ID.lstrip('@')}"
        public_channel_display_name = PUBLIC_CHANNEL_ID
    elif isinstance(PUBLIC_CHANNEL_ID, int):
        public_channel_link = f"our public channel (ID: {PUBLIC_CHANNEL_ID})" # Hard to link directly by ID without username
        # To make it clickable, you might need the channel's invite link if it's private and numeric,
        # or just its @username if public. For now, just display.
    else:
        public_channel_link = "our public channel (misconfigured)"
        logger.error("send_join_channel_prompt: PUBLIC_CHANNEL_ID type is not recognized for link generation.")


    display_content_name = SEASONS_DISPLAY_NAMES.get(requested_content_key, requested_content_key.replace('_', ' ').title())
    text = (
        f"👋 Hello! To access '{display_content_name}', you need to join {public_channel_link}.\n\n"
        "Once joined, click 'Try Again' below."
    )
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ I've Joined! Try Again.", callback_data=f"retry_{requested_content_key}")
    ]])
    
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML) # Or MARKDOWN
        elif update.message:
            await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML) # Or MARKDOWN
        logger.info(f"Sent join channel prompt to user {user_id} for '{requested_content_key}'.")
    except Exception as e:
        logger.error(f"Error sending join prompt to user {user_id}: {e}", exc_info=True)


async def send_files_to_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE, content_key: str):
    file_ids = SEASONS.get(content_key, [])
    valid_file_ids = [fid for fid in file_ids if fid and not fid.startswith('FILE_ID_')]

    display_content_name = SEASONS_DISPLAY_NAMES.get(content_key, content_key.replace('_', ' ').title())

    if not valid_file_ids:
        await context.bot.send_message(chat_id, f"🚧 Files for '{display_content_name}' are not available right now.")
        logger.warning(f"No valid files for '{content_key}' for user {user_id}.")
        return

    await context.bot.send_message(chat_id,
        f"✅ Great! Sending {len(valid_file_ids)} file(s) for '{display_content_name}'.\n\n"
        f"🕒 _These files auto-delete in {DELETE_AFTER_SECONDS // 60} mins._",
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info(f"Sending {len(valid_file_ids)} files for '{content_key}' to user {user_id}.")

    sent_count = 0
    failed_count = 0
    for index, file_id in enumerate(valid_file_ids):
        try:
            caption = f"{display_content_name} - Part {index + 1}"
            sent_message = await context.bot.send_document(chat_id=chat_id, document=file_id, caption=caption)
            sent_count += 1
            logger.info(f"Sent Part {index + 1} for '{content_key}' to user {user_id} (MsgID: {sent_message.message_id}).")
            context.job_queue.run_once(
                delete_message_job, DELETE_AFTER_SECONDS,
                {'chat_id': chat_id, 'message_id': sent_message.message_id},
                name=f'del_{chat_id}_{sent_message.message_id}' # Shorter job name
            )
            await asyncio.sleep(0.5) # Small polite delay
        except Exception as e:
            failed_count += 1
            logger.error(f"Error sending file Part {index + 1} (ID: {file_id}) for '{content_key}' to user {user_id}: {e}", exc_info=True)
            if failed_count == 1:
                try:
                    await context.bot.send_message(chat_id, "⚠️ An error occurred while sending some of the files.")
                except Exception: pass # Avoid error loops
    if failed_count > 0:
        logger.warning(f"Finished for '{content_key}' for {user_id}. Sent: {sent_count}, Failed: {failed_count}.")
    else:
        logger.info(f"All {sent_count} files for '{content_key}' sent to {user_id}.")


# === Telegram Handlers ===
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not BOT_TOKEN or not BOT_USERNAME or not PUBLIC_CHANNEL_ID:
        logger.critical("start_handler: Critical bot config missing.")
        if update.message: await update.message.reply_text("Bot error. Admin contact needed.")
        return

    logger.info(f"/start from user {user.id} ({user.full_name or 'UnknownUser'}) in chat {chat_id}, args: {context.args}")

    if not context.args:
        public_channel_link_text = str(PUBLIC_CHANNEL_ID)
        if isinstance(PUBLIC_CHANNEL_ID, str) and PUBLIC_CHANNEL_ID.startswith('@'):
            public_channel_link_text = PUBLIC_CHANNEL_ID
        await update.message.reply_text(f"Hello! 👋 Use buttons in {public_channel_link_text} to get files.")
        return

    requested_content_key = context.args[0].lower() # Ensure key is consistent

    if requested_content_key not in SEASONS:
        await update.message.reply_text("😕 Unrecognized request. Use buttons from the channel.")
        logger.warning(f"User {user.id} requested unknown key: '{requested_content_key}'.")
        return

    is_member = await is_user_member_of_public_channel(context.bot, user.id)
    if is_member:
        await send_files_to_user(chat_id, user.id, context, requested_content_key)
    else:
        await send_join_channel_prompt(update, context, requested_content_key)


async def retry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.effective_user
    chat_id = query.effective_chat.id
    
    # Callback data format: "retry_CONTENTKEY"
    try:
        action_type, requested_content_key = query.data.split("_", 1)
        if action_type != "retry":
            raise ValueError("Invalid action type in callback")
    except ValueError:
        logger.warning(f"Invalid callback data format: {query.data} from user {user.id}")
        try:
            await query.edit_message_text("Error with request. Try channel buttons.")
        except Exception: pass
        return

    logger.info(f"User {user.id} clicked 'Try Again' for '{requested_content_key}'.")

    is_member = await is_user_member_of_public_channel(context.bot, user.id)
    if is_member:
        try:
            await query.delete_message()
        except Exception as e_del:
            logger.warning(f"Could not delete 'join prompt' message: {e_del}")
        await send_files_to_user(chat_id, user.id, context, requested_content_key)
    else:
        await send_join_channel_prompt(update, context, requested_content_key)


async def delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data['chat_id']
    message_id = job.data['message_id']
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Auto-deleted message {message_id} from chat {chat_id}.")
    except Forbidden:
        logger.warning(f"No permission to auto-delete message {message_id} in {chat_id}.")
    except BadRequest as e:
        if "message to delete not found" in str(e).lower() or "message_id_invalid" in str(e).lower():
            logger.info(f"Message {message_id} in {chat_id} already deleted (or never existed).")
        else:
            logger.warning(f"BadRequest deleting message {message_id} in {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error auto-deleting msg {message_id} in {chat_id}: {e}", exc_info=True)


async def setup_buttons(context: ContextTypes.DEFAULT_TYPE = None, bot: Bot = None):
    if not bot and context: bot = context.bot
    if not bot: logger.error("setup_buttons: Bot instance missing."); return
    if not PUBLIC_CHANNEL_ID or not BOT_USERNAME:
        logger.error("setup_buttons: PUBLIC_CHANNEL_ID or BOT_USERNAME missing.")
        return

    keyboard = []
    if not SEASONS: logger.warning("setup_buttons: SEASONS empty."); return
    
    valid_keys = sorted([k for k, v_list in SEASONS.items() if any(fid and not fid.startswith('FILE_ID_') for fid in v_list)])
    if not valid_keys: logger.warning("setup_buttons: No valid content keys."); return

    for key in valid_keys:
        display_name = SEASONS_DISPLAY_NAMES.get(key, key.replace('_', ' ').title())
        button_text = f"🎬 {display_name}"
        button_url = f"https://t.me/{BOT_USERNAME}?start={key}"
        keyboard.append([InlineKeyboardButton(button_text, url=button_url)])

    if not keyboard: logger.error("setup_buttons: Keyboard generation failed."); return

    reply_markup = InlineKeyboardMarkup(keyboard)
    public_channel_link_text = str(PUBLIC_CHANNEL_ID)
    if isinstance(PUBLIC_CHANNEL_ID, str) and PUBLIC_CHANNEL_ID.startswith('@'):
        public_channel_link_text = PUBLIC_CHANNEL_ID

    text = (
        "✨ **File Portal Updated!** ✨\n\n"
        "Select content below. You must be a member of this channel to receive files.\n"
        f"Files are sent via @{BOT_USERNAME} and auto-delete after {DELETE_AFTER_SECONDS // 60} mins."
    )
    try:
        await bot.send_message(
            chat_id=PUBLIC_CHANNEL_ID, text=text, reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
        logger.info(f"Button message sent/updated in {PUBLIC_CHANNEL_ID}.")
    except Exception as e:
        logger.error(f"Failed to send button message to {PUBLIC_CHANNEL_ID}: {e}", exc_info=True)


async def get_chat_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; user = update.effective_user; chat_id = chat.id
    response_text = f"Chat ID: `{chat_id}`\nChat Type: `{chat.type}`"
    if user: response_text += f"\nYour User ID: `{user.id}`"
    logger.info(f"/chatid by user {user.id if user else 'Unknown'} in chat {chat_id}.")
    await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)


async def post_init_hook(application: Application):
    logger.info("Running post-init tasks...")
    if not all([BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID]):
        logger.warning("post_init: Some critical configs missing. Bot may not function fully.")

    try:
        bot_info = await application.bot.get_me()
        actual_bot_username = bot_info.username
        logger.info(f"Bot successfully initialized: @{actual_bot_username} (ID: {bot_info.id})")
        if BOT_USERNAME and BOT_USERNAME != actual_bot_username:
             logger.warning(f"CONFIG MISMATCH: Env BOT_USERNAME ('{BOT_USERNAME}') vs actual ('{actual_bot_username}')!")
    except Exception as e:
         logger.error(f"Failed to get bot info during post_init: {e}", exc_info=True)

    if AUTO_SETUP_BUTTONS_ON_START:
        if PUBLIC_CHANNEL_ID and BOT_USERNAME:
             logger.info("post_init: Scheduling button setup for public channel...")
             application.job_queue.run_once(lambda ctx: setup_buttons(bot=application.bot), when=2) # Short delay
        else:
            logger.error("post_init: Cannot auto-setup buttons; PUBLIC_CHANNEL_ID or BOT_USERNAME is not set.")
    else:
        logger.info("post_init: Auto button setup on startup is disabled.")


# === Main Bot Execution Function ===
def run_telegram_bot_application():
    logger.info("Attempting to start Telegram bot application...")
    if not BOT_TOKEN:
        logger.critical("CRITICAL ERROR: BOT_TOKEN not set. Bot cannot start.")
        return

    defaults = Defaults(parse_mode=ParseMode.MARKDOWN)
    try:
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .defaults(defaults)
            .job_queue(JobQueue())
            .post_init(post_init_hook)
            .build()
        )
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to build Telegram application. Error: {e}", exc_info=True)
        return

    logger.info("--- Bot Configuration Summary ---")
    logger.info(f"Bot Username: @{BOT_USERNAME or 'NOT SET'}")
    logger.info(f"Public Channel: {PUBLIC_CHANNEL_ID or 'NOT SET'}")
    logger.info(f"Private Channel (Ref): {PRIVATE_CHANNEL_ID or 'NOT SET'}")
    logger.info(f"Seasons Keys: {list(SEASONS.keys())}")
    logger.info(f"Delete After: {DELETE_AFTER_SECONDS}s")
    logger.info(f"Auto Setup Buttons: {AUTO_SETUP_BUTTONS_ON_START}")
    logger.info("--------------------------------")

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("chatid", get_chat_id_handler))
    application.add_handler(CallbackQueryHandler(retry_handler, pattern=r"^retry_"))

    logger.info("Starting Telegram bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Telegram bot polling stopped.")


# === Main Entry Point ===
if __name__ == '__main__':
    logger.info("Script execution starting...")

    if not all([BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID]):
        logger.critical("CRITICAL ERROR: BOT_TOKEN, BOT_USERNAME, or PUBLIC_CHANNEL_ID is missing from environment. Bot cannot run reliably. Please check configuration.")
        # sys.exit(1) # Consider a hard exit if these are absolutely vital from the start
    else:
        logger.info("Essential configurations (BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID) appear to be loaded.")
        
        try:
            keep_alive() # Start the keep-alive Flask server (non-blocking)
            logger.info("Keep_alive server thread initiated.")
        except Exception as e_ka:
            logger.error(f"Could not start keep_alive server: {e_ka}", exc_info=True)
            # Decide if this is fatal; for now, we'll proceed
        
        # Run the main Telegram bot logic
        try:
            run_telegram_bot_application()
        except KeyboardInterrupt:
            logger.info("Bot process stopped by user (Ctrl+C).")
        except Exception as e_main_bot:
            logger.critical(f"UNHANDLED EXCEPTION in main bot execution: {e_main_bot}", exc_info=True)

    logger.info("Script execution finished or bot has been stopped.")

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
import re # For escaping markdown
from telegram import (
    Update,
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    ChatMember
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
    Defaults,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError, Forbidden, BadRequest
from telegram.helpers import escape_markdown # Import the escape_markdown helper

# === Logging Setup ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# === Configuration ===
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME')
PRIVATE_CHANNEL_ID = os.getenv('PRIVATE_CHANNEL_ID')
PUBLIC_CHANNEL_ID_STR = os.getenv('PUBLIC_CHANNEL_ID')

try:
    PUBLIC_CHANNEL_ID = int(PUBLIC_CHANNEL_ID_STR) if PUBLIC_CHANNEL_ID_STR and PUBLIC_CHANNEL_ID_STR.startswith('-') else PUBLIC_CHANNEL_ID_STR
except (ValueError, TypeError):
    logger.error(f"PUBLIC_CHANNEL_ID ('{PUBLIC_CHANNEL_ID_STR}') is not valid. Bot might not function correctly.")
    PUBLIC_CHANNEL_ID = None

if not BOT_TOKEN: logger.critical("CRITICAL ERROR: BOT_TOKEN is not set.")
if not BOT_USERNAME: logger.warning("WARNING: BOT_USERNAME is not set.")
if not PUBLIC_CHANNEL_ID: logger.critical("CRITICAL ERROR: PUBLIC_CHANNEL_ID is not configured.")

SEASONS = {
    'apothecary_diaries_s1': [
        'BQACAgQAAxkBAAEBEWhoImGp0GLWjLBTaJ90ZcIYtdFtvQACtSMAA1AZUQABXCxSF360SzYE', 'BQACAgQAAxkBAAEBEX9oInhdz1T_S7sJEifWD91VL5vO7QACzyMAA1AZUZ107KoTZlUXNgQ',
        'BQACAgQAAxkBAAEBFY5oIyNYobHZHWWk2DJ2Hjkx99LgRAAC1CMAA1AZUdl6cVfp1NJENgQ', 'BQACAgQAAxkBAAEBFZRoIyPO_rPhGaOyzbrB9C1i0kVQFAAC2CMAA1AZUdTTQh9FDanpNgQ',
        'BQACAgQAAxkBAAEBFZ5oIyRnTpQuMZmUL6G0WhoO5B4aTAAC7CMAA1AZUbD3Pqh5iI1gNgQ', 'BQACAgQAAxkBAAEBFaRoIyUvMwXAz9PJcwM1IppLokbTxwAC_iMAA1AZUa4d5x39FGS6NgQ',
        'BQACAgQAAxkBAAEBFapoIyWcR6Le331xB_Hy3e3yyLuNlwAC_yMAA1AZUSGVkYFzvP5GNgQ', 'BQACAgQAAxkBAAEBFa5oIyXqcbLkpRD8H0JIea1iQcBN9QACASQAA1AZUQIF8Id9ze3tNgQ',
        'BQACAgQAAxkBAAEBFbBoIyYNu-Oz0H_CmwSiouSiq2WESAACAyQAA1AZUZlu2B38psTBNgQ', 'BQACAgQAAxkBAAEBFbJoIyY5Y0wmYpBtM6pl9f4HNN6XzwACBSQAA1AZUeb9OVa0RYU1NgQ',
        'BQACAgQAAxkBAAEBFbdoIyaq6xhaL0IQieSe4wakJd5WiQACBiQAA1AZUbUJS4dMKZIKNgQ', 'BQACAgQAAxkBAAEBFbloIybcbew4-C-ALKSiyYbX0LvZzQACByQAA1AZUcm08Upui6CaNgQ',
        'BQACAgQAAxkBAAEBFcxoIyfdR-Q4uWTvvCYYJRK1vX129AACCCQAA1AZUUUV06vwTECfNgQ', 'BQACAgQAAxkBAAEBFcxoIyfdR-Q4uWTvvCYYJRK1vX129AACCCQAA1AZUUUV06vwTECfNgQ',
        'BQACAgQAAxkBAAEBFdRoIyhfAWiiAUhdtrryj7NOjFW8pwACCiQAA1AZUfPBIAQINEVLNgQ', 'BQACAgQAAxkBAAEBFdhoIyiVNqJxHKEkceFyPylG5vH0ugACCyQAA1AZUat5zS5woEANNgQ',
    ],
    'another_series_s2': ['FILE_ID_S02E01', 'FILE_ID_S02E02'],
}
SEASONS_DISPLAY_NAMES = {
    'apothecary_diaries_s1': "Apothecary Diaries (S1 Dual 1080p)",
    'another_series_s2': "Another Series (Season 2)",
}
DELETE_AFTER_SECONDS = 20 * 60
AUTO_SETUP_BUTTONS_ON_START = True

# === Helper Functions ===
async def is_user_member_of_public_channel(bot: Bot, user_id: int) -> bool:
    if not PUBLIC_CHANNEL_ID: logger.error("is_user_member: PUBLIC_CHANNEL_ID not set."); return False
    try:
        member = await bot.get_chat_member(chat_id=PUBLIC_CHANNEL_ID, user_id=user_id)
        allowed = [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED]
        is_member = member.status in allowed
        logger.info(f"User {user_id} membership in {PUBLIC_CHANNEL_ID}: {is_member} (Status: {member.status}).")
        return is_member
    except BadRequest as e:
        if "user not found" in str(e).lower() or "user_not_participant" in str(e).lower():
            logger.info(f"User {user_id} not participant in {PUBLIC_CHANNEL_ID}.")
        elif "chat not found" in str(e).lower():
            logger.error(f"Public channel {PUBLIC_CHANNEL_ID} not found. Error: {e}")
        else: logger.error(f"BadRequest checking membership for {user_id}: {e}", exc_info=True)
        return False
    except Exception as e: logger.error(f"Unexpected err checking membership {user_id}: {e}", exc_info=True); return False

async def send_join_channel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, requested_content_key: str):
    user_id = update.effective_user.id
    public_channel_link_text = str(PUBLIC_CHANNEL_ID)
    if isinstance(PUBLIC_CHANNEL_ID, str) and PUBLIC_CHANNEL_ID.startswith('@'):
        public_channel_link_text = f"[{PUBLIC_CHANNEL_ID}](https://t.me/{PUBLIC_CHANNEL_ID.lstrip('@')})"
    elif isinstance(PUBLIC_CHANNEL_ID, int): # Create a general link if numeric and bot has username
        if BOT_USERNAME: # A bit indirect, but Telegram usually resolves channel links via bot if bot is member
             public_channel_link_text = f"our [public channel](https://t.me/{BOT_USERNAME}?startgroup={PUBLIC_CHANNEL_ID})" # This is a guess, might not work perfectly for joining
        else:
             public_channel_link_text = f"our public channel (ID: {PUBLIC_CHANNEL_ID})" # Fallback if no bot username
    else: public_channel_link_text = "our public channel (config error)"

    display_content_name = SEASONS_DISPLAY_NAMES.get(requested_content_key, requested_content_key.replace('_', ' ').title())
    text = (
        f"👋 Hello\\! To access '{escape_markdown(display_content_name, version=2)}', "
        f"you need to join {public_channel_link_text}\\.\n\n"
        "Once joined, click 'Try Again' below\\."
    )
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ I've Joined! Try Again.", callback_data=f"retry_{requested_content_key}")
    ]])
    try:
        if update.callback_query: await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        elif update.message: await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"Sent join prompt to user {user_id} for '{requested_content_key}'.")
    except Exception as e: logger.error(f"Error sending join prompt to {user_id}: {e}", exc_info=True)

async def send_files_to_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE, content_key: str):
    file_ids = SEASONS.get(content_key, [])
    valid_file_ids = [fid for fid in file_ids if fid and not fid.startswith('FILE_ID_')]
    display_content_name = SEASONS_DISPLAY_NAMES.get(content_key, content_key.replace('_', ' ').title())

    if not valid_file_ids:
        await context.bot.send_message(chat_id, f"🚧 Files for '{escape_markdown(display_content_name, version=2)}' not available yet\\.")
        logger.warning(f"No valid files for '{content_key}' for {user_id}.")
        return

    await context.bot.send_message(chat_id,
        f"✅ Great\\! Sending {len(valid_file_ids)} file\\(s\\) for '{escape_markdown(display_content_name, version=2)}'\\.\n\n"
        f"🕒 _These files auto\\-delete in {DELETE_AFTER_SECONDS // 60} mins\\._", # Italic is with single underscores in MDv2
        parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info(f"Sending {len(valid_file_ids)} files for '{content_key}' to {user_id}.")
    sent_count, failed_count = 0, 0
    for index, file_id in enumerate(valid_file_ids):
        try:
            caption = f"{display_content_name} - Part {index + 1}" # Captions are plain text unless parse_mode is set
            sent_message = await context.bot.send_document(chat_id=chat_id, document=file_id, caption=caption)
            sent_count += 1
            logger.info(f"Sent Part {index+1} for '{content_key}' to {user_id} (MsgID: {sent_message.message_id}).")
            context.job_queue.run_once(
                delete_message_job, DELETE_AFTER_SECONDS,
                {'chat_id': chat_id, 'message_id': sent_message.message_id},
                name=f'del_{chat_id}_{sent_message.message_id}'
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            failed_count += 1
            logger.error(f"Err sending Part {index+1} ('{content_key}') to {user_id}: {e}", exc_info=True)
            if failed_count == 1: await context.bot.send_message(chat_id, "⚠️ Error sending some files\\.")
    if failed_count > 0: logger.warning(f"Done '{content_key}' for {user_id}. Sent: {sent_count}, Failed: {failed_count}.")
    else: logger.info(f"All {sent_count} for '{content_key}' sent to {user_id}.")

# === Telegram Handlers ===
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; chat_id = update.effective_chat.id
    if not all([BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID]): # Check if essential configs are available
        logger.critical("start_handler: Essential bot config(s) missing.")
        if update.message: await update.message.reply_text("Bot error. Admin needs to check config.")
        return

    logger.info(f"/start: user={user.id}({user.full_name or 'N/A'}), chat={chat_id}, args={context.args}")
    if not context.args:
        pc_id_display = str(PUBLIC_CHANNEL_ID)
        if isinstance(PUBLIC_CHANNEL_ID, str) and PUBLIC_CHANNEL_ID.startswith('@'): pc_id_display = PUBLIC_CHANNEL_ID
        await update.message.reply_text(f"Hello! 👋 Use buttons in {pc_id_display} for files.")
        return

    req_key = context.args[0].lower()
    if req_key not in SEASONS:
        await update.message.reply_text("😕 Unrecognized request key. Use channel buttons.")
        logger.warning(f"User {user.id} bad key: '{req_key}'.")
        return

    is_member = await is_user_member_of_public_channel(context.bot, user.id)
    if is_member: await send_files_to_user(chat_id, user.id, context, req_key)
    else: await send_join_channel_prompt(update, context, req_key)

async def retry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user = query.effective_user; chat_id = query.effective_chat.id
    try: action_type, req_key = query.data.split("_", 1)
    except ValueError: # Handles if query.data is not in "action_key" format
        logger.warning(f"Invalid callback data '{query.data}' from user {user.id}")
        await query.edit_message_text("Invalid request. Try buttons in the channel.")
        return

    if action_type != "retry": 
        logger.warning(f"Unknown callback action '{action_type}' from {user.id}")
        await query.edit_message_text("Unknown action. Try channel buttons.")
        return

    logger.info(f"User {user.id} 'Try Again' for '{req_key}'.")
    is_member = await is_user_member_of_public_channel(context.bot, user.id)
    if is_member:
        try: await query.delete_message()
        except Exception as e: logger.warning(f"Could not delete 'join' prompt: {e}")
        await send_files_to_user(chat_id, user.id, context, req_key)
    else: await send_join_channel_prompt(update, context, req_key) # Re-sends or edits the prompt

async def delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job; chat_id = job.data['chat_id']; message_id = job.data['message_id']
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Auto-deleted msg {message_id} from chat {chat_id}.")
    except Forbidden: logger.warning(f"No permission to auto-delete {message_id} in {chat_id}.")
    except BadRequest as e:
        if "not found" in str(e).lower() or "invalid" in str(e).lower(): logger.info(f"Msg {message_id} in {chat_id} already deleted/invalid.")
        else: logger.warning(f"BadRequest deleting {message_id} in {chat_id}: {e}")
    except Exception as e: logger.error(f"Err auto-deleting {message_id} in {chat_id}: {e}", exc_info=True)

async def setup_buttons(context: ContextTypes.DEFAULT_TYPE = None, bot: Bot = None):
    if not bot and context: bot = context.bot
    if not bot: logger.error("setup_buttons: Bot missing."); return
    if not PUBLIC_CHANNEL_ID or not BOT_USERNAME: logger.error("setup_buttons: Config missing."); return

    keyboard = []
    if not SEASONS: logger.warning("setup_buttons: SEASONS empty."); return
    valid_keys = sorted([k for k, v in SEASONS.items() if any(fid and not fid.startswith('FILE_ID_') for fid in v)])
    if not valid_keys: logger.warning("setup_buttons: No valid content."); return

    for key in valid_keys:
        display_name = SEASONS_DISPLAY_NAMES.get(key, key.replace('_', ' ').title())
        button_text = f"🎬 {display_name}"
        button_url = f"https://t.me/{BOT_USERNAME}?start={key}"
        keyboard.append([InlineKeyboardButton(button_text, url=button_url)])

    if not keyboard: logger.error("setup_buttons: Keyboard gen failed."); return
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Using MarkdownV2 - ensure BOT_USERNAME is escaped if it contains special chars
    # The telegram.helpers.escape_markdown function is useful here.
    safe_bot_username = escape_markdown(BOT_USERNAME, version=2) if BOT_USERNAME else "the bot"
    
    text = (
        "✨ *File Portal Updated\\!* ✨\n\n"
        "Select content below\\.\n"
        "📢 _You must be a member of this channel to receive files\\._\n" # Italic uses single _ in MDv2
        f"Files are sent via @{safe_bot_username} and auto\\-delete after {DELETE_AFTER_SECONDS // 60} mins\\."
    ) # Note: MarkdownV2 requires escaping of ., !, -, etc.
      # For a more complex message, pre-escape all special characters or use HTML.
      # The text above has been simplified and basic escapes added.

    try:
        await bot.send_message(
            chat_id=PUBLIC_CHANNEL_ID, text=text, reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True
        )
        logger.info(f"Button message sent/updated in {PUBLIC_CHANNEL_ID}.")
    except Exception as e:
        logger.error(f"Failed to send button message to {PUBLIC_CHANNEL_ID}: {e}", exc_info=True)
        # If it's a parsing error, log the problematic text
        if "parse" in str(e).lower():
            logger.error(f"Problematic text for MarkdownV2 was likely: {text}")


async def get_chat_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; user = update.effective_user; chat_id = chat.id
    response_text = f"Chat ID: `{chat_id}`\nChat Type: `{chat.type}`" # Backticks are for MarkdownV1 code block
    if user: response_text += f"\nYour User ID: `{user.id}`"
    logger.info(f"/chatid by {user.id if user else 'N/A'} in {chat_id} ({chat.type}).")
    # For this simple message, let's try without parse_mode or use MarkdownV1 (default if not specified)
    # Or ensure any special chars in response_text are escaped if using MarkdownV2
    await update.message.reply_text(response_text) # Defaults to no parse_mode or MDV1 depending on PTB default


async def post_init_hook(application: Application):
    logger.info("Running post-init tasks...")
    if not all([BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID]):
        logger.warning("post_init: Critical configs missing. Functionality may be impaired.")
    try:
        bot_info = await application.bot.get_me()
        logger.info(f"Bot init: @{bot_info.username} (ID: {bot_info.id})")
        if BOT_USERNAME and BOT_USERNAME != bot_info.username:
             logger.warning(f"MISMATCH: Env BOT_USERNAME ('{BOT_USERNAME}') vs actual ('{bot_info.username}')!")
    except Exception as e: logger.error(f"Failed bot info in post_init: {e}", exc_info=True)

    if AUTO_SETUP_BUTTONS_ON_START:
        if PUBLIC_CHANNEL_ID and BOT_USERNAME:
             logger.info("post_init: Scheduling button setup...")
             application.job_queue.run_once(lambda ctx: setup_buttons(bot=application.bot), when=2)
        else: logger.error("post_init: Cannot auto-setup buttons; config missing.")
    else: logger.info("post_init: Auto button setup disabled.")

# === Main Bot Execution Function ===
def run_telegram_bot_application():
    logger.info("Attempting to start Telegram bot application...")
    if not BOT_TOKEN: logger.critical("CRITICAL: BOT_TOKEN missing."); return

    # Set default parse mode for the application if desired (e.g. MARKDOWN_V2)
    # Be mindful that all reply_text/send_message calls will use this unless overridden.
    # If setting MarkdownV2 as default, ensure all bot messages are V2 compliant or escape them.
    defaults = Defaults(parse_mode=ParseMode.MARKDOWN_V2) # CHANGED TO MARKDOWN_V2
    
    try:
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .defaults(defaults) # Apply default parse mode
            .job_queue(JobQueue())
            .post_init(post_init_hook)
            .build()
        )
    except Exception as e:
        logger.critical(f"CRITICAL: Failed Telegram app build: {e}", exc_info=True)
        return

    logger.info("--- Bot Configuration Summary ---")
    logger.info(f"Bot Username: @{BOT_USERNAME or 'N/A'}")
    logger.info(f"Public Channel: {PUBLIC_CHANNEL_ID or 'N/A'}")
    # ... (other summary items) ...

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
        logger.critical("CRITICAL: Essential env vars (BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID) not all set. Exiting.")
        # import sys; sys.exit(1) # Hard exit if criticals are missing
    else:
        logger.info("Essential configurations appear loaded.")
        try:
            keep_alive()
            logger.info("Keep_alive server thread initiated.")
        except Exception as e_ka:
            logger.error(f"Could not start keep_alive: {e_ka}", exc_info=True)
        
        try: run_telegram_bot_application()
        except KeyboardInterrupt: logger.info("Bot process stopped by user (Ctrl+C).")
        except Exception as e_main: logger.critical(f"UNHANDLED EXCEPTION in main: {e_main}", exc_info=True)
    logger.info("Script execution finished or bot stopped.")

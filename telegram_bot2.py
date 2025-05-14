# ===----------------------------------------------------------------------=== #
#                    Enhanced Telegram File Share Bot                        #
# ===----------------------------------------------------------------------=== #

# 1. Environment Variable Loading
import os
from dotenv import load_dotenv
load_dotenv()

# 2. Keep Alive Import
from keep_alive import keep_alive

# 3. Standard Imports
import logging
import asyncio
from telegram import (
    Update,
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMember // NEW: To check member status
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler, # NEW: To handle "Try Again" button
    ContextTypes,
    JobQueue,
    Defaults,
)
from telegram.constants import ParseMode, ChatMemberStatus # NEW: For status comparison
from telegram.error import TelegramError, Forbidden, BadRequest

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
PRIVATE_CHANNEL_ID = os.getenv('PRIVATE_CHANNEL_ID') # For reference if needed later
PUBLIC_CHANNEL_ID_STR = os.getenv('PUBLIC_CHANNEL_ID') # Can be @username or -100ID
# Convert PUBLIC_CHANNEL_ID_STR to int if it's a numeric ID, otherwise keep as string
try:
    PUBLIC_CHANNEL_ID = int(PUBLIC_CHANNEL_ID_STR) if PUBLIC_CHANNEL_ID_STR and PUBLIC_CHANNEL_ID_STR.startswith('-') else PUBLIC_CHANNEL_ID_STR
except ValueError:
    logger.error(f"PUBLIC_CHANNEL_ID ('{PUBLIC_CHANNEL_ID_STR}') is not a valid integer ID or @username. Bot might not function correctly.")
    PUBLIC_CHANNEL_ID = None # Set to None if invalid to catch errors later

if not BOT_TOKEN:
    logger.critical("CRITICAL ERROR: BOT_TOKEN is not set.")
    # For a real deployment, you might want to sys.exit(1) here
if not BOT_USERNAME:
    logger.warning("WARNING: BOT_USERNAME is not set. Deep links will be incorrect.")
if not PUBLIC_CHANNEL_ID: # Will be None if the original string was invalid or not set
    logger.critical("CRITICAL ERROR: PUBLIC_CHANNEL_ID is not properly configured or set.")

# --- File & Series/Season Configuration ---
# Using more descriptive keys is good practice!
# Example: 'the_boys_s1', 'invincible_s2', 'movie_interstellar'
# Keys should ideally not contain spaces for easier deep-linking and argument parsing.
SEASONS = {
    'apothecary_diaries_s1': [ # Renamed for better practice
        'BQACAgQAAxkBAAEBEWhoImGp0GLWjLBTaJ90ZcIYtdFtvQACtSMAA1AZUQABXCxSF360SzYE', #1
        'BQACAgQAAxkBAAEBEX9oInhdz1T_S7sJEifWD91VL5vO7QACzyMAA1AZUZ107KoTZlUXNgQ', #2
        # ... (add all your file IDs for apothecary_diaries_s1) ...
        'BQACAgQAAxkBAAEBFdRoIyhfAWiiAUhdtrryj7NOjFW8pwACCiQAA1AZUfPBIAQINEVLNgQ',
        'BQACAgQAAxkBAAEBFdhoIyiVNqJxHKEkceFyPylG5vH0ugACCyQAA1AZUat5zS5woEANNgQ',
    ],
    'generic_series_s2': [ # Example for another season/series
        'FILE_ID_S02E01',
        'FILE_ID_S02E02',
    ],
    # Add more series/movies/content here
}

DELETE_AFTER_SECONDS = 20 * 60  # 20 minutes
AUTO_SETUP_BUTTONS_ON_START = True # Set to True for initial button posting

# === Helper Function to Check Channel Membership ===
async def is_user_member_of_public_channel(bot: Bot, user_id: int) -> bool:
    if not PUBLIC_CHANNEL_ID:
        logger.error("Public channel ID not configured for membership check.")
        return False # Cannot check if channel ID is not set
    try:
        member = await bot.get_chat_member(chat_id=PUBLIC_CHANNEL_ID, user_id=user_id)
        # User is considered a member if their status is member, administrator, or creator
        # Restricted users are also technically "in" the channel but might not have full access.
        # For this purpose, we usually care if they are not 'left' or 'kicked'.
        if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR, ChatMemberStatus.RESTRICTED]:
            logger.info(f"User {user_id} is a member of {PUBLIC_CHANNEL_ID} with status: {member.status}")
            return True
        else:
            logger.info(f"User {user_id} is NOT an active member of {PUBLIC_CHANNEL_ID}. Status: {member.status}")
            return False
    except BadRequest as e:
        if "User not found" in str(e) or "USER_NOT_PARTICIPANT" in str(e).upper():
            logger.info(f"User {user_id} not found in channel {PUBLIC_CHANNEL_ID} or is not a participant.")
            return False
        elif "Chat not found" in str(e):
            logger.error(f"Public channel {PUBLIC_CHANNEL_ID} not found. Check configuration. Error: {e}")
            return False # Cannot check if channel doesn't exist or bot can't access
        else:
            logger.error(f"Error checking membership for user {user_id} in {PUBLIC_CHANNEL_ID}: {e}", exc_info=True)
            return False # Default to false on other errors to be safe
    except Exception as e:
        logger.error(f"Unexpected error checking membership for user {user_id} in {PUBLIC_CHANNEL_ID}: {e}", exc_info=True)
        return False


async def send_join_channel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, requested_content_key: str):
    """Sends a message prompting the user to join the channel."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    public_channel_link = f"https://t.me/{PUBLIC_CHANNEL_ID.lstrip('@')}" if isinstance(PUBLIC_CHANNEL_ID, str) and PUBLIC_CHANNEL_ID.startswith('@') else f"Channel (ID: {PUBLIC_CHANNEL_ID})"

    text = (
        f"👋 Hello! To access the files for '{requested_content_key.replace('_', ' ').title()}', "
        f"you first need to be a member of our channel: {public_channel_link}\n\n"
        "Please join the channel and then click the button below to try again."
    )
    # Callback data will be "retry_CONTENTKEY"
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I've Joined! Try Again.", callback_data=f"retry_{requested_content_key}")]
    ])
    if update.callback_query: # If this is from a callback (e.g. user clicked "try again" but wasn't member)
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif update.message:
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Sent join channel prompt to user {user_id} for content key '{requested_content_key}'.")

async def send_files_to_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE, season_key: str):
    """Sends the requested files to the user and schedules deletion."""
    file_ids = SEASONS.get(season_key, [])
    valid_file_ids = [fid for fid in file_ids if fid and not fid.startswith('FILE_ID_')]

    if not valid_file_ids:
        await context.bot.send_message(chat_id, f"🚧 Files for '{season_key.replace('_', ' ').title()}' seem to be missing or not configured correctly.")
        logger.warning(f"No valid file IDs found for key '{season_key}' requested by user {user_id} after membership check.")
        return

    await context.bot.send_message(chat_id,
        f"✅ Great! Sending you {len(valid_file_ids)} file(s) for '{season_key.replace('_', ' ').title()}'.\n\n"
        f"🕒 _These files will be automatically deleted in {DELETE_AFTER_SECONDS // 60} minutes._",
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info(f"Processing request for '{season_key}' ({len(valid_file_ids)} files) for user {user_id}.")

    sent_count = 0
    failed_count = 0
    for index, file_id in enumerate(valid_file_ids):
        try:
            # More descriptive caption:
            # Find the original display name if possible, or use the key.
            # This requires SEASONS_DISPLAY_NAMES or a way to derive it. For now, use key.
            display_name = season_key.replace('_', ' ').title()
            caption = f"{display_name} - Part {index + 1}"

            sent_message = await context.bot.send_document(
                chat_id=chat_id, document=file_id, caption=caption
            )
            sent_count += 1
            logger.info(f"Sent file {index + 1}/{len(valid_file_ids)} (ID: ...{file_id[-10:]}) for '{season_key}' to user {user_id}.")
            context.job_queue.run_once(
                delete_message_job, DELETE_AFTER_SECONDS,
                {'chat_id': chat_id, 'message_id': sent_message.message_id},
                name=f'delete_{chat_id}_{sent_message.message_id}'
            )
            logger.info(f"Scheduled message {sent_message.message_id} for deletion.")
            await asyncio.sleep(0.3) # Small delay to avoid hitting potential minor rate limits
        except Exception as e: # Simplified error handling for this example, catch specific ones as before if needed
            failed_count += 1
            logger.error(f"Error sending file {index + 1} (ID: {file_id}) for '{season_key}' to user {user_id}: {e}", exc_info=True)
            if failed_count == 1: # Notify only once per batch
                await context.bot.send_message(chat_id, "⚠️ An error occurred while sending some files.")
    if failed_count > 0:
        logger.warning(f"Finished for '{season_key}' for {user_id}. Sent: {sent_count}, Failed: {failed_count}.")
    else:
        logger.info(f"All {sent_count} files for '{season_key}' sent to user {user_id}.")

# === Core Bot Logic (Handlers) ===

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command and deep links."""
    user = update.effective_user
    chat_id = update.effective_chat.id # This is the private chat with the user

    # Pre-check essential configs
    if not BOT_TOKEN or not BOT_USERNAME or not PUBLIC_CHANNEL_ID:
        logger.critical("Essential bot configuration (TOKEN, USERNAME, PUBLIC_CHANNEL_ID) missing.")
        if update.message: await update.message.reply_text("Bot error: Configuration missing. Please contact admin.")
        return

    logger.info(f"User {user.id} ({user.full_name}) initiated /start in chat {chat_id} with args: {context.args}")

    if not context.args:
        public_channel_link = f"https://t.me/{PUBLIC_CHANNEL_ID.lstrip('@')}" if isinstance(PUBLIC_CHANNEL_ID, str) and PUBLIC_CHANNEL_ID.startswith('@') else f"our public channel (ID: {PUBLIC_CHANNEL_ID})"
        await update.message.reply_text(f"Hello! 👋 Please use the buttons in {public_channel_link} to get files.")
        return

    requested_content_key = context.args[0].lower()

    if requested_content_key not in SEASONS:
        await update.message.reply_text("😕 Sorry, I don't recognize that request key.")
        logger.warning(f"User {user.id} requested unknown key: '{requested_content_key}'.")
        return

    is_member = await is_user_member_of_public_channel(context.bot, user.id)
    if is_member:
        await send_files_to_user(chat_id, user.id, context, requested_content_key)
    else:
        await send_join_channel_prompt(update, context, requested_content_key)


async def retry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'Try Again' button presses."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    user = query.effective_user
    chat_id = query.effective_chat.id # DM chat
    # Callback data is "retry_CONTENTKEY"
    requested_content_key = query.data.split("retry_", 1)[1] if query.data and query.data.startswith("retry_") else None

    if not requested_content_key:
        logger.warning(f"Invalid callback data received: {query.data} from user {user.id}")
        await query.edit_message_text("Sorry, something went wrong. Please try clicking the main button in the channel again.")
        return

    logger.info(f"User {user.id} clicked 'Try Again' for content key '{requested_content_key}'.")

    is_member = await is_user_member_of_public_channel(context.bot, user.id)
    if is_member:
        # User has (hopefully) joined, remove the "Join channel" message and send files
        try:
            await query.delete_message() # Delete the "join channel" prompt message
        except Exception as e:
            logger.warning(f"Could not delete 'join channel' prompt message: {e}")
        await send_files_to_user(chat_id, user.id, context, requested_content_key)
    else:
        # User still not a member, resend or update the prompt
        await send_join_channel_prompt(update, context, requested_content_key)


async def delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    # (This function remains the same as your previous version)
    job = context.job
    chat_id = job.data['chat_id']
    message_id = job.data['message_id']
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Auto-deleted message {message_id} from chat {chat_id}.")
    except Exception as e:
        logger.warning(f"Could not auto-delete message {message_id} in {chat_id}: {e}", exc_info=True)


# === Creative Suggestion: Dynamic Button Text & Helper for SEASONS ===
# Store display names separately if keys are code-like
SEASONS_DISPLAY_NAMES = {
    'apothecary_diaries_s1': "The Apothecary Diaries (Season 1 Dual Audio 1080p)",
    'generic_series_s2': "Generic Series (Season 2)",
    # Add more here, matching keys in SEASONS
}

async def setup_buttons(context: ContextTypes.DEFAULT_TYPE = None, bot: Bot = None):
    if not bot and context: bot = context.bot
    if not bot:
        logger.error("setup_buttons: Bot instance missing.")
        return
    if not PUBLIC_CHANNEL_ID or not BOT_USERNAME:
        logger.error("setup_buttons: PUBLIC_CHANNEL_ID or BOT_USERNAME missing.")
        return

    keyboard = []
    if not SEASONS:
        logger.warning("setup_buttons: SEASONS dictionary empty.")
        return

    valid_seasons_keys = sorted([key for key, ids in SEASONS.items() if any(fid and not fid.startswith('FILE_ID_') for fid in ids)])

    if not valid_seasons_keys:
        logger.warning("setup_buttons: No valid seasons/content with file IDs found.")
        # Optionally, send a "content coming soon" message to the public channel
        # await bot.send_message(PUBLIC_CHANNEL_ID, "🚧 Content is being updated. Please check back soon!")
        return

    for key in valid_seasons_keys:
        # Use the display name if available, otherwise format the key
        button_text = SEASONS_DISPLAY_NAMES.get(key, key.replace('_', ' ').title())
        button_text = f"🎬 {button_text}" # Add an emoji or prefix
        button_url = f"https://t.me/{BOT_USERNAME}?start={key}"
        keyboard.append([InlineKeyboardButton(button_text, url=button_url)])

    if not keyboard: # Should be redundant if valid_seasons_keys is populated
        logger.error("setup_buttons: Failed to generate keyboard markup unexpectedly.")
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "✨ **Welcome to the File Portal!** ✨\n\n"
        "Select the content you'd like to receive below.\n"
        f"Clicking a button will start a chat with me (@{BOT_USERNAME}), and I'll send you the files.\n\n"
        "📢 _You must be a member of this channel to receive files._\n"
        f"🕒 _Files are automatically removed from our chat after {DELETE_AFTER_SECONDS // 60} minutes._"
    )
    try:
        # Consider storing the ID of this message to edit it later instead of sending new ones
        await bot.send_message(
            chat_id=PUBLIC_CHANNEL_ID, text=text, reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
        logger.info(f"Button message sent/updated in channel {PUBLIC_CHANNEL_ID}.")
    except Exception as e:
        logger.error(f"Failed to send button message to {PUBLIC_CHANNEL_ID}: {e}", exc_info=True)


async def get_chat_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (This function remains the same as your previous version)
    chat = update.effective_chat; user = update.effective_user; chat_id = chat.id
    response_text = f"Chat ID: `{chat_id}`\nChat Type: {chat.type}\nUser ID: `{user.id if user else 'N/A'}`"
    logger.info(f"/chatid by {user.id if user else 'N/A'} in {chat_id} ({chat.type}).")
    await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)


async def post_init_hook(application: Application):
    # (This function remains largely the same, ensure config checks are robust)
    logger.info("Running post-init tasks...")
    if not BOT_TOKEN or not BOT_USERNAME or not PUBLIC_CHANNEL_ID:
        logger.error("post_init: Critical configurations missing. Bot may not function correctly.")
    # ... (get_me and AUTO_SETUP_BUTTONS_ON_START logic as before) ...
    try:
        bot_info = await application.bot.get_me()
        actual_bot_username = bot_info.username
        logger.info(f"Bot initialized: @{actual_bot_username} (ID: {bot_info.id})")
        if BOT_USERNAME and BOT_USERNAME != actual_bot_username:
             logger.warning(
                 f"CONFIG MISMATCH: Env BOT_USERNAME ('{BOT_USERNAME}') "
                 f"vs actual ('{actual_bot_username}')!"
             )
    except Exception as e:
         logger.error(f"Failed to get bot info during post_init: {e}", exc_info=True)

    if AUTO_SETUP_BUTTONS_ON_START:
        if not PUBLIC_CHANNEL_ID or not BOT_USERNAME:
             logger.error("post_init: Cannot auto-setup buttons due to missing PUBLIC_CHANNEL_ID or BOT_USERNAME.")
        else:
             logger.info("post_init: Scheduling button setup for public channel...")
             application.job_queue.run_once(lambda ctx: setup_buttons(bot=application.bot), when=2)
    else:
        logger.info("post_init: Automatic button setup on startup is disabled.")


# === Main Bot Execution Function ===
def run_telegram_bot_application():
    logger.info("Attempting to start Telegram bot application...")
    if not BOT_TOKEN: # Critical check
        logger.critical("CRITICAL: BOT_TOKEN missing. Telegram Bot cannot start.")
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

    # Configuration Summary (log only if application build was successful)
    logger.info("--- Bot Configuration Summary ---")
    logger.info(f"Bot Username (from env): @{BOT_USERNAME or 'NOT SET'}")
    logger.info(f"Public Channel (from env): {PUBLIC_CHANNEL_ID or 'NOT SET'}")
    # ... (other summary items)

    # Handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("chatid", get_chat_id_handler))
    application.add_handler(CallbackQueryHandler(retry_handler, pattern=r"^retry_")) # NEW: Handle "retry_*" callbacks

    logger.info("Starting Telegram bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Telegram bot polling stopped.")


# === Main Entry Point ===
if __name__ == '__main__':
    logger.info("Script execution starting...")
    if not all([BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID]):
        logger.critical("CRITICAL: Essential environment variables (BOT_TOKEN, BOT_USERNAME, PUBLIC_CHANNEL_ID) are not all set. Bot will not run correctly. Please check your .env file or platform environment variables.")
        # Consider sys.exit(1) here for a hard stop if any critical config is missing
    else:
        logger.info("All critical environment variables seem to be loaded.")
        try:
            keep_alive() # Start the keep-alive Flask server
            logger.info("Keep_alive server thread initiated.")
        except Exception as e_ka:
            logger.error(f"Error starting keep_alive server: {e_ka}", exc_info=True)
            # Decide: proceed without keep_alive or stop? For now, proceed.

        # Run the main Telegram bot logic
        try:
            run_telegram_bot_application()
        except KeyboardInterrupt:
            logger.info("Bot process terminated by user (KeyboardInterrupt).")
        except Exception as e_main_bot:
            logger.critical(f"Fatal error in main bot execution: {e_main_bot}", exc_info=True)

    logger.info("Script execution finished or bot has stopped.")

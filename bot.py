import os
import sys
import html
import logging
import asyncio
from typing import Dict, List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_HISTORY = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Verify API Keys on startup
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
    logger.warning("⚠️ TELEGRAM_BOT_TOKEN is not set in .env! Bot will not start until configured.")

if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
    logger.warning("⚠️ GEMINI_API_KEY is not set in .env! AI responses will be disabled until configured.")

# Import Telegram libraries
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode, ChatAction
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        ContextTypes,
        filters
    )
except ImportError:
    logger.error("❌ 'python-telegram-bot' is not installed. Run 'pip install -r requirements.txt'")
    sys.exit(1)

# Import AI library (google-genai or google-generativeai)
ai_client = None
AI_AVAILABLE = False

try:
    from google import genai
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
        ai_client = genai.Client(api_key=GEMINI_API_KEY)
        AI_AVAILABLE = True
        logger.info("✅ Google GenAI SDK initialized successfully.")
except ImportError:
    try:
        import google.generativeai as genai_legacy
        if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
            genai_legacy.configure(api_key=GEMINI_API_KEY)
            ai_client = genai_legacy
            AI_AVAILABLE = True
            logger.info("✅ Google GenerativeAI Legacy SDK initialized successfully.")
    except ImportError:
        logger.warning("⚠️ Neither 'google-genai' nor 'google-generativeai' module found.")

# Store in-memory conversation history: {chat_id: [{"role": "user"/"model", "text": "..."}]}
user_conversations: Dict[int, List[Dict[str, str]]] = {}


def get_user_history(chat_id: int) -> List[Dict[str, str]]:
    """Retrieve history list for a chat ID."""
    if chat_id not in user_conversations:
        user_conversations[chat_id] = []
    return user_conversations[chat_id]


def add_to_history(chat_id: int, role: str, text: str):
    """Add a message to history and enforce MAX_HISTORY limit."""
    history = get_user_history(chat_id)
    history.append({"role": role, "text": text})
    if len(history) > MAX_HISTORY:
        user_conversations[chat_id] = history[-MAX_HISTORY:]


def clear_history(chat_id: int):
    """Clear conversation history for a chat ID."""
    user_conversations[chat_id] = []


def split_text(text: str, max_length: int = 4000) -> List[str]:
    """Split long responses into chunk sizes allowed by Telegram."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_idx = text.rfind("\n", 0, max_length)
        if split_idx == -1:
            split_idx = max_length
        chunks.append(text[:split_idx])
        text = text[split_idx:].lstrip("\n")
    return chunks


async def generate_ai_response(prompt: str, history: List[Dict[str, str]]) -> str:
    """Generate response from Gemini API."""
    if not AI_AVAILABLE or not GEMINI_API_KEY:
        return "⚠️ AI service is not configured yet. Please set your GEMINI_API_KEY in the `.env` file."

    try:
        # Build prompt with history
        contents = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(f"{role.capitalize()}: {msg['text']}")
        contents.append(f"User: {prompt}")
        full_prompt = "\n".join(contents)

        if hasattr(ai_client, "models"):
            # Using new google-genai SDK
            response = ai_client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=full_prompt
            )
            return response.text
        else:
            # Using google.generativeai legacy SDK
            model = ai_client.GenerativeModel(GEMINI_MODEL_NAME)
            response = model.generate_content(full_prompt)
            return response.text
    except Exception as e:
        logger.error(f"Error calling AI API: {e}")
        return f"❌ Sorry, an error occurred while generating AI response:\n<code>{html.escape(str(e))}</code>"


# ---------------- Telegram Bot Handlers ----------------

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Returns main interactive keyboard buttons."""
    keyboard = [
        [
            InlineKeyboardButton("🧹 Clear Context", callback_data="clear_context"),
            InlineKeyboardButton("❓ Help", callback_data="show_help")
        ],
        [
            InlineKeyboardButton("⚙️ Bot Status", callback_data="show_status")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    user = update.effective_user
    first_name = user.first_name if user else "Friend"
    
    welcome_text = (
        f"👋 <b>Hello, {html.escape(first_name)}!</b>\n\n"
        f"I am your <b>AI Assistant Bot</b> powered by Google Gemini.\n"
        f"You can ask me questions, request help with writing, code, ideas, and much more!\n\n"
        f"<b>Available Commands:</b>\n"
        f"• Simply type your message to chat with me!\n"
        f"• /clear - Reset conversation memory\n"
        f"• /help - Display user guide\n"
        f"• /status - Check bot status"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /help command."""
    help_text = (
        "💡 <b>Bot User Guide & Tips</b>\n\n"
        "1. <b>Chatting</b>: Send any text message to start asking questions.\n"
        "2. <b>Context Memory</b>: The bot remembers your recent messages. If you want to start a fresh topic, use /clear.\n"
        "3. <b>Code & Formatting</b>: Code blocks and formatted responses will be presented cleanly.\n"
        "4. <b>Privacy</b>: Your chat history is stored locally in memory only during the active session."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /clear command."""
    chat_id = update.effective_chat.id
    clear_history(chat_id)
    await update.message.reply_text(
        "🧹 <b>Conversation history cleared!</b>\nYou are now starting a fresh conversation context.",
        parse_mode=ParseMode.HTML
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /status command."""
    chat_id = update.effective_chat.id
    history_count = len(get_user_history(chat_id))
    ai_status = "✅ Connected" if AI_AVAILABLE else "❌ Missing GEMINI_API_KEY in .env"
    
    status_text = (
        f"📊 <b>Bot Status Information</b>\n\n"
        f"🤖 <b>AI Provider</b>: Google Gemini ({GEMINI_MODEL_NAME})\n"
        f"🔌 <b>AI Connection</b>: {ai_status}\n"
        f"💬 <b>Active Context Messages</b>: {history_count} / {MAX_HISTORY}"
    )
    await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)


async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for inline button clicks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "clear_context":
        clear_history(chat_id)
        await query.edit_message_text(
            "🧹 <b>Conversation history cleared!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
    elif query.data == "show_help":
        await help_command(update, context)
    elif query.data == "show_status":
        await status_command(update, context)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for standard text messages."""
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text

    # Show typing indicator to user
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Fetch user history and generate response
    history = get_user_history(chat_id)
    ai_response = await generate_ai_response(user_text, history)

    # Save to history
    add_to_history(chat_id, "user", user_text)
    add_to_history(chat_id, "model", ai_response)

    # Send response in chunks if long
    chunks = split_text(ai_response)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Fallback to plain text if markdown parsing fails
            await update.message.reply_text(chunk)


def main():
    """Start and run the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("\n=======================================================")
        print("❌ ERROR: TELEGRAM_BOT_TOKEN is missing or not set!")
        print("Please edit the '.env' file and add your Telegram bot token.")
        print("Get your token from Telegram by chatting with @BotFather.")
        print("=======================================================\n")
        return

    logger.info("🚀 Starting Telegram AI Bot application...")
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(button_click_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("🤖 Bot is polling for updates... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()

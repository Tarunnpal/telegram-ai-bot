import os
import sys
import json
import html
import logging
import io
import time
import asyncio
import urllib.parse
import requests
from datetime import datetime
from typing import Dict, List, Any
from dotenv import load_dotenv
from PIL import Image

# Load environment variables from .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip().strip('"').strip("'")
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"').strip("'")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

# Path for persistent JSON memory
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "data", "memory.json")

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


def _generate_ai_image_bytes(prompt: str) -> bytes:
    """Worker function to generate AI image bytes using Pollinations AI Engine."""
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={int(time.time())}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    res = requests.get(url, headers=headers, timeout=25)
    if res.status_code == 200 and len(res.content) > 1000:
        return res.content
    raise ValueError(f"Image generation server returned HTTP {res.status_code}")


# ---------------- Telegram Bot Handlers ----------------

def load_all_memories() -> Dict[str, Any]:
    """Load all persistent user memory from JSON file."""
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading memory.json: {e}")
    return {}


def save_all_memories(data: Dict[str, Any]):
    """Save user memory dictionary to JSON file."""
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving memory.json: {e}")


def get_user_memory(chat_id: int, first_name: str = "Friend") -> Dict[str, Any]:
    """Retrieve memory data for a user."""
    memories = load_all_memories()
    key = str(chat_id)
    if key not in memories:
        memories[key] = {
            "first_name": first_name,
            "history": []
        }
        save_all_memories(memories)
    return memories[key]


def append_to_user_history(chat_id: int, user_text: str, ai_text: str, first_name: str = "Friend"):
    """Append user message and AI response to persistent history."""
    memories = load_all_memories()
    key = str(chat_id)
    if key not in memories:
        memories[key] = {
            "first_name": first_name,
            "history": []
        }
    memories[key]["first_name"] = first_name
    history = memories[key].get("history", [])
    history.append({"role": "user", "text": user_text})
    history.append({"role": "model", "text": ai_text})
    
    # Retain up to 100 conversation turns (ChatGPT-style persistent depth)
    if len(history) > 100:
        memories[key]["history"] = history[-100:]
    else:
        memories[key]["history"] = history

    save_all_memories(memories)


def track_ui_message_id(chat_id: int, message_id: int):
    """Track Telegram UI message IDs to allow cleaning chat bubbles later."""
    memories = load_all_memories()
    key = str(chat_id)
    if key in memories:
        ids = memories[key].get("ui_message_ids", [])
        if message_id not in ids:
            ids.append(message_id)
        memories[key]["ui_message_ids"] = ids[-100:]
        save_all_memories(memories)


async def clean_chat_screen_ui(context: ContextTypes.DEFAULT_TYPE, chat_id: int, current_msg_id: int = None):
    """Deletes ALL previous chat message bubbles INSTANTLY without deleting the user's current new question."""
    memories = load_all_memories()
    key = str(chat_id)
    tracked_ids = memories.get(key, {}).get("ui_message_ids", [])
    
    target_ids = set(tracked_ids)
    
    if current_msg_id:
        # Scan back 100 IDs but EXCLUDE current_msg_id so user's new prompt is NEVER deleted!
        min_id = max(1, current_msg_id - 100)
        target_ids.update(range(current_msg_id - 1, min_id, -1))
        target_ids.discard(current_msg_id)
    elif tracked_ids:
        max_id = max(tracked_ids)
        min_id = max(1, max_id - 100)
        target_ids.update(range(max_id, min_id, -1))

    id_list = list(target_ids)
    if id_list:
        # Batch delete up to 100 message IDs at once in 1 single instant Telegram API call!
        for i in range(0, len(id_list), 100):
            chunk = id_list[i:i+100]
            try:
                await context.bot.delete_messages(chat_id=chat_id, message_ids=chunk)
            except Exception:
                for m_id in chunk:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=m_id)
                    except Exception:
                        pass

    if key in memories:
        memories[key]["ui_message_ids"] = [current_msg_id] if current_msg_id else []
        save_all_memories(memories)


# Auto-clean screen ONLY when user pauses for 5+ minutes (300 seconds) or closes app for 5+ minutes
INACTIVITY_AUTO_CLEAN_GAP = 300


async def check_and_autoclean_session(context: ContextTypes.DEFAULT_TYPE, chat_id: int, current_msg_id: int = None):
    """If user returns after closing app / inactivity gap, auto-wipe old screen bubbles while keeping memory 100% intact."""
    memories = load_all_memories()
    key = str(chat_id)
    now = time.time()
    if key in memories:
        last_active = memories[key].get("last_active_timestamp", 0)
        if last_active > 0 and (now - last_active) > INACTIVITY_AUTO_CLEAN_GAP:
            await clean_chat_screen_ui(context, chat_id, current_msg_id)
        memories[key]["last_active_timestamp"] = now
        save_all_memories(memories)
    else:
        get_user_memory(chat_id)
        memories = load_all_memories()
        memories[key]["last_active_timestamp"] = now
        save_all_memories(memories)


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


# ---------------- AI Generation with Persistent Context ----------------

def get_current_date_info() -> str:
    """Returns real-time current date, day, and time string."""
    now = datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')} (Current Local Time: {now.strftime('%I:%M %p')})"


def _call_gemini_with_full_context(chat_id: int, first_name: str, prompt: str) -> str:
    """Worker function to generate ChatGPT-style response with persistent memory and AI Calendar capabilities."""
    user_mem = get_user_memory(chat_id, first_name)
    history = user_mem.get("history", [])
    date_info = get_current_date_info()

    system_instruction = (
        f"YOUR NAME IS FRIDAY (inspired by Tony Stark's AI assistant).\n"
        f"IMPORTANT IDENTITY, RESPONSE LENGTH & DOMAIN INSTRUCTIONS:\n"
        f"- You are FRIDAY, an advanced AI Assistant & Smart Calendar created for {first_name}.\n"
        f"- REAL-TIME LIVE CALENDAR DATA: {date_info}.\n"
        f"- RESPONSE LENGTH & STYLE (CRITICAL RULE):\n"
        f"  * DEFAULT STYLE: Keep answers SHORT, CRISP, ACCURATE, AND DIRECTLY TO THE POINT. Eliminate unnecessary intro/outro fluff for simple queries.\n"
        f"  * DETAILED STYLE: Provide longer, structured, step-by-step explanations ONLY when the user asks for complex topics, coding, tutorials, stories, or detailed breakdowns.\n"
        f"- TRAIN QUERIES & LIVE LOCATION (MANDATORY INSTRUCTIONS):\n"
        f"  * When asked about any train number (e.g. '12952', '12004', '12951'), train route, or train location:\n"
        f"  * 1. Provide Train Name, Route (Source -> Destination), Departure & Arrival Timings, and Days of Running.\n"
        f"  * 2. MANDATORY LIVE LOCATION & TRACKING LINK:\n"
        f"       - State the expected current station & next station based on the live current time ({date_info}).\n"
        f"       - Provide this exact 1-tap live GPS tracking link: 📍 Live GPS Status: https://www.google.com/search?q=live+running+status+train+TRAINNUMBER\n"
        f"  * 3. MANDATORY END QUESTION: At the end of EVERY train-related answer, ALWAYS ask EXACTLY:\n"
        f"       '🎟️ Kya aap ticket book karna chahte hain?'\n"
        f"  * IF USER SAYS YES ('Haan' / 'Yes' / 'Ji haan'): Proceed with booking process — ask for Journey Date, Passenger details, Class (1A/2A/3A/SL), and provide direct official IRCTC (irctc.co.in) booking guidance!\n"
        f"  * IF USER SAYS NO ('Nahi' / 'No' / 'Naa'): Respond politely and ask EXACTLY:\n"
        f"    'Aapko aur kaunsi train ki information chahiye?'\n"
        f"- IDENTITY: If asked your name, state clearly and proudly that your name is FRIDAY. NEVER call yourself 'Gemini' or 'Google Gemini'.\n"
        f"- CONTEXT & MEMORY: Remember {first_name}'s name, past conversations, personal details, interests, events, and preferences continuously.\n"
        f"- LANGUAGE: Respond naturally in English, Hindi, or Hinglish matching the user's language."
    )

    contents = [system_instruction]
    for msg in history:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        contents.append(f"{role_label}: {msg['text']}")
    contents.append(f"User: {prompt}")

    full_prompt = "\n\n".join(contents)

    candidate_models = ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]
    last_error = None

    for model_name in candidate_models:
        try:
            if hasattr(ai_client, "models"):
                res = ai_client.models.generate_content(model=model_name, contents=full_prompt)
                return res.text
            else:
                model = ai_client.GenerativeModel(model_name)
                res = model.generate_content(full_prompt)
                return res.text
        except Exception as err:
            last_error = err
            logger.warning(f"Model {model_name} failed: {err}. Trying fallback...")
            continue

    raise last_error


async def generate_ai_response(chat_id: int, first_name: str, prompt: str) -> str:
    """Generate response asynchronously with worker thread."""
    if not AI_AVAILABLE or not GEMINI_API_KEY:
        return "⚠️ AI service is not configured yet. Please set your GEMINI_API_KEY in the `.env` file."

    try:
        ai_response = await asyncio.to_thread(_call_gemini_with_full_context, chat_id, first_name, prompt)
        append_to_user_history(chat_id, prompt, ai_response, first_name)
        return ai_response
    except Exception as e:
        logger.error(f"Error calling AI API: {e}")
        return f"❌ Sorry, an error occurred while generating AI response:\n<code>{html.escape(str(e))}</code>"


def _call_gemini_photo(chat_id: int, first_name: str, caption: str, image: Image.Image) -> str:
    """Worker function for photo analysis with context and calendar awareness."""
    user_mem = get_user_memory(chat_id, first_name)
    history = user_mem.get("history", [])
    date_info = get_current_date_info()

    prompt_context = (
        f"You are FRIDAY (Smart AI Assistant & Calendar). {date_info}.\n"
        f"The user {first_name} sent an image.\n"
        f"User Caption / Question: {caption}\n"
        f"Analyze the image and respond helpfully keeping past context in mind as FRIDAY."
    )

    candidate_models = [GEMINI_MODEL_NAME, "gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.6-flash"]
    last_error = None

    for model_name in candidate_models:
        try:
            if hasattr(ai_client, "models"):
                res = ai_client.models.generate_content(model=model_name, contents=[prompt_context, image])
                return res.text
            else:
                model = ai_client.GenerativeModel(model_name)
                res = model.generate_content([prompt_context, image])
                return res.text
        except Exception as err:
            last_error = err
            continue

    raise last_error


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Returns main interactive keyboard buttons (clean, uncluttered UI)."""
    keyboard = [
        [
            InlineKeyboardButton("❓ Help", callback_data="show_help"),
            InlineKeyboardButton("⚙️ Status", callback_data="show_status")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command - cleans old screen bubbles and shows fresh welcome."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    first_name = user.first_name if user else "Friend"
    
    # Auto-clean ALL previous chat bubbles from screen
    await clean_chat_screen_ui(context, chat_id, update.message.message_id)

    welcome_text = (
        f"👋 <b>Hello, {html.escape(first_name)}!</b>\n\n"
        f"I am <b>FRIDAY</b>, your personal AI Assistant with persistent memory.\n"
        f"🧠 <b>Memory Active</b>: I remember all our past conversations and context continuously!\n"
        f"🧹 <b>Clean Screen</b>: Use /start or tap 'Clean Screen' anytime to wipe old message bubbles from view.\n\n"
        f"<b>Options:</b>\n"
        f"• Simply type any message or send photos to chat!\n"
        f"• /help - Display user guide\n"
        f"• /status - Check bot status"
    )
    
    sent_msg = await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )
    track_ui_message_id(chat_id, update.message.message_id)
    track_ui_message_id(chat_id, sent_msg.message_id)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /help command."""
    help_text = (
        "💡 <b>FRIDAY AI Assistant Guide</b>\n\n"
        "1. <b>Chatting & QA</b>: Send any text message to ask questions, write code, or brainstorm.\n"
        "2. <b>Image Generation 🎨</b>: Type <code>/image a cyberpunk car</code> or <code>/draw a cute puppy</code> to generate stunning AI photos!\n"
        "3. <b>Image Analysis 📸</b>: Send any photo to analyze or ask questions about it.\n"
        "4. <b>Train Info & Timetables 🚆</b>: Ask for trains between cities or type any 5-digit Train Number (e.g. 12952) for timings & live GPS status.\n"
        "5. <b>Persistent Memory 🧠</b>: Your chat context and past conversations are permanently saved."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
    elif update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /status command."""
    chat_id = update.effective_chat.id
    user_mem = get_user_memory(chat_id)
    history_turns = len(user_mem.get("history", [])) // 2
    ai_status = "✅ Connected" if AI_AVAILABLE else "❌ Missing GEMINI_API_KEY in .env"
    
    status_text = (
        f"📊 <b>Bot Status & Memory Info</b>\n\n"
        f"🤖 <b>AI Name</b>: FRIDAY\n"
        f"⚡ <b>Engine</b>: Gemini 3.6 Flash\n"
        f"🔌 <b>AI Connection</b>: {ai_status}\n"
        f"🧠 <b>Memory Storage</b>: Persistent Local JSON\n"
        f"💬 <b>Saved Conversation Turns</b>: {history_turns} turns remembered"
    )
    if update.message:
        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)
    elif update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(status_text, parse_mode=ParseMode.HTML)


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /image or /draw command to generate AI photos."""
    if not update.message:
        return

    chat_id = update.effective_chat.id
    prompt = " ".join(context.args) if context.args else ""

    await check_and_autoclean_session(context, chat_id, update.message.message_id)
    track_ui_message_id(chat_id, update.message.message_id)

    if not prompt:
        await update.message.reply_text("🎨 <b>Usage:</b> <code>/image a futuristic cyberpunk car in Tokyo</code>", parse_mode=ParseMode.HTML)
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)

    try:
        image_bytes = await asyncio.to_thread(_generate_ai_image_bytes, prompt)
        caption_text = f"🎨 <b>AI Generated Image by FRIDAY</b>\n<i>Prompt: {html.escape(prompt)}</i>"
        sent_photo = await update.message.reply_photo(photo=io.BytesIO(image_bytes), caption=caption_text, parse_mode=ParseMode.HTML)
        track_ui_message_id(chat_id, sent_photo.message_id)
    except Exception as e:
        logger.error(f"Error generating AI image: {e}")
        await update.message.reply_text(f"❌ Could not generate image:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for inline button clicks."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "clean_screen":
        await clean_chat_screen_ui(context, chat_id, query.message.message_id)
        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🧹 <b>Chat screen cleaned!</b> (FRIDAY's memory remains 100% saved).",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
        track_ui_message_id(chat_id, sent_msg.message_id)
    elif query.data == "show_help":
        await help_command(update, context)
    elif query.data == "show_status":
        await status_command(update, context)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for standard text messages."""
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    first_name = update.effective_user.first_name if update.effective_user else "Friend"
    user_text = update.message.text.strip()

    # Auto-clean screen bubbles if user is returning after closing Telegram app
    await check_and_autoclean_session(context, chat_id, update.message.message_id)
    track_ui_message_id(chat_id, update.message.message_id)

    # Detect natural image generation requests
    lower_text = user_text.lower()
    image_triggers = ["generate image", "create image", "draw image", "make photo", "generate photo", "draw a", "image of "]
    if any(lower_text.startswith(t) or lower_text.startswith(f"friday {t}") for t in image_triggers):
        img_prompt = user_text
        for t in ["friday", "generate image of", "generate image", "create image of", "create image", "draw image of", "draw image", "make photo of", "make photo", "image of"]:
            img_prompt = re.sub(rf"(?i)^{t}\s*", "", img_prompt).strip()
        if img_prompt:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            try:
                image_bytes = await asyncio.to_thread(_generate_ai_image_bytes, img_prompt)
                caption_text = f"🎨 <b>AI Generated Image by FRIDAY</b>\n<i>Prompt: {html.escape(img_prompt)}</i>"
                sent_photo = await update.message.reply_photo(photo=io.BytesIO(image_bytes), caption=caption_text, parse_mode=ParseMode.HTML)
                track_ui_message_id(chat_id, sent_photo.message_id)
                return
            except Exception as e:
                logger.error(f"Error auto generating image: {e}")

    # Show typing indicator to user
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Generate response with persistent memory
    ai_response = await generate_ai_response(chat_id, first_name, user_text)

    chunks = split_text(ai_response)
    for chunk in chunks:
        try:
            sent_msg = await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            track_ui_message_id(chat_id, sent_msg.message_id)
        except Exception:
            try:
                sent_msg = await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
                track_ui_message_id(chat_id, sent_msg.message_id)
            except Exception:
                sent_msg = await update.message.reply_text(chunk)
                track_ui_message_id(chat_id, sent_msg.message_id)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for photo messages (multimodal image recognition)."""
    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    first_name = update.effective_user.first_name if update.effective_user else "Friend"
    caption = update.message.caption or "Analyze this image and describe what you see in detail. Also answer any questions if present."

    await check_and_autoclean_session(context, chat_id, update.message.message_id)
    track_ui_message_id(chat_id, update.message.message_id)

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        image = Image.open(io.BytesIO(image_bytes))

        ai_response = await asyncio.to_thread(_call_gemini_photo, chat_id, first_name, caption, image)
        append_to_user_history(chat_id, f"[User sent an image] Caption: {caption}", ai_response, first_name)

        chunks = split_text(ai_response)
        for chunk in chunks:
            try:
                sent_msg = await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                track_ui_message_id(chat_id, sent_msg.message_id)
            except Exception:
                sent_msg = await update.message.reply_text(chunk)
                track_ui_message_id(chat_id, sent_msg.message_id)

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        await update.message.reply_text(f"❌ Could not analyze image:\n<code>{html.escape(str(e))}</code>", parse_mode=ParseMode.HTML)


def main():
    """Start and run the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        print("\n=======================================================")
        print("❌ ERROR: TELEGRAM_BOT_TOKEN is missing or not set!")
        print("Please edit the '.env' file and add your Telegram bot token.")
        print("=======================================================\n")
        return

    logger.info("🚀 Starting Persistent ChatGPT-style Telegram AI Bot...")
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("draw", image_command))
    app.add_handler(CallbackQueryHandler(button_click_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("🤖 Bot is polling for updates... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()

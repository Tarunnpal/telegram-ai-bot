# 🤖 Telegram AI Chatbot

A feature-rich, asynchronous Telegram Bot powered by Python (`python-telegram-bot`) and Google Gemini AI API (`google-genai`).

## 🌟 Key Features
- **💬 Smart AI Chat**: Conversational responses with context memory.
- **🧹 Memory Management**: Easily reset context with `/clear`.
- **⚡ Typing Status**: Active chat action indicator while generating AI answers.
- **🎛️ Interactive UI**: Modern inline buttons for quick actions.
- **🔒 Security**: All secret API keys stored in local `.env` file (protected by `.gitignore`).

---

## 🛠️ Step 1: Local Setup

### 1. Clone or Open Project Folder
Open your terminal in the project directory:
```bash
cd telegram-bot
```

### 2. Create and Activate Python Virtual Environment
**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🔑 Step 2: Get Your Free API Keys

### A. Telegram Bot Token (from `@BotFather`)
1. Open your Telegram app and search for `@BotFather`.
2. Send `/newbot` and follow the prompts to name your bot and choose a username (e.g. `MyAwesomeAi_bot`).
3. `@BotFather` will give you a **HTTP API Token**. Copy it!

### B. Google Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account and click **Get API key**.
3. Copy your API Key.

---

## ⚙️ Step 3: Configure `.env` File

Open the `.env` file in your text editor and paste your credentials:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
GEMINI_API_KEY=AIzaSyYourActualGeminiApiKeyHere
```

---

## 🚀 Step 4: Run the Bot

Start the bot locally:
```bash
python bot.py
```

Open Telegram, search for your bot username, click **Start** or send `/start` to begin chatting! 🎉

---

## 🐙 Step-by-Step GitHub Setup & Push Guide

Follow these exact steps to safely push your bot code to GitHub without leaking your secret API keys:

### 1. Initialize Git Repository
```bash
git init
```

### 2. Set Default Branch Name
```bash
git branch -M main
```

### 3. Check Tracked Files (Verify Secrets are Safe)
```bash
git status
```
> ⚠️ **IMPORTANT**: Make sure `.env` is NOT listed under untracked files! Only `.env.example`, `.gitignore`, `bot.py`, `requirements.txt`, and `README.md` should be listed.

### 4. Stage and Commit Your Code
```bash
git add .
git commit -m "Initial commit: AI Telegram Bot with python-telegram-bot and Gemini API"
```

### 5. Create Repository on GitHub
1. Go to [GitHub](https://github.com/new).
2. Enter Repository Name: `telegram-ai-bot`.
3. Select **Public** or **Private**.
4. Leave "Add a README file", "Add .gitignore", and "Choose a license" UNCHECKED (we already created them).
5. Click **Create repository**.

### 6. Link and Push to GitHub
Copy the commands shown on your GitHub repository page and run them in your terminal:
```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/telegram-ai-bot.git
git push -u origin main
```

Congratulations! Your Telegram Bot code is now safely on GitHub! 🚀

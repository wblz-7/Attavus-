import logging
import os
import sys
import time
import random
import urllib.request
import urllib.parse
import json
import html
import asyncio
import re
import datetime
import tempfile
import shutil
import xml.etree.ElementTree as ET
import aiohttp
import requests
import openai
from openai import AsyncOpenAI
import telegram.error
from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

def load_api_keys(filepath="api_keys.txt"):
    if not os.path.exists(filepath):
        logging.error(f"FATAL: {filepath} not found! Please create it and add your keys.")
        sys.exit(1)
    with open(filepath, "r") as f:
        keys = [line.strip() for line in f if line.strip()]
    if not keys:
        logging.error(f"FATAL: {filepath} is empty!")
        sys.exit(1)
    return keys

GROQ_API_KEYS = load_api_keys()
logging.info(f"Successfully loaded {len(GROQ_API_KEYS)} key(s)")

def fetch_groq_models(api_keys):
    url = "https://api.groq.com/openai/v1/models"
    for key in api_keys:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.get(url, headers=headers, timeout=15.0)
            if response.status_code == 200:
                data = response.json()
                models = []
                for m in data.get("data", []):
                    model_id = m.get("id", "")

                    if "whisper" not in model_id.lower() and "guard" not in model_id.lower():
                        models.append(model_id)
                if models:
                    logging.info(f"Dynamically loaded {len(models)} text models from Groq.")
                    return models
        except Exception as e:
            logging.warning(f"Failed to fetch models dynamically: {e}")
            continue

    logging.warning("Falling back to default text models.")
    return [
        "llama-3.3-70b-versatile",
        "mixtral-8x7b-32768",
        "llama-3.1-8b-instant",
        "qwen/qwen3.6-27b"
    ]

TELEGRAM_TOKEN = "8869214614:AAHaWOxuM5zS02-GEY4KQdZZbX3W1soQXu4"
NEWS_API_KEY = "7d48d797ff634874a155db19326388a2"
BASE_URL = "https://api.groq.com/openai/v1"
SCORES_FILE = "scores.json"
HISTORY_FILE = "history.json"

MODELS_CASCADE = fetch_groq_models(GROQ_API_KEYS)

OWNER_ID = 7194867487
OWNER_USERNAME = "@skkeds"
OWNER_NAME = "skkeds"

clients = [AsyncOpenAI(api_key=key, base_url=BASE_URL) for key in GROQ_API_KEYS]

user_sessions = {}
active_chats = set()
active_games = {}
ttt_games = {}
mine_games = {}
hangman_games = {}
wordle_games = {}
wordle_pending = {}
db_lock = asyncio.Lock()

chat_buffers = {}
CHAT_BUFFER_MAX = 25

chat_last_activity = {}

trivia_streaks = {}

trivia_schedule = {}
ACTIVITY_WINDOW = 900
TRIVIA_MIN_INTERVAL = 14400
TRIVIA_MAX_INTERVAL = 28800

search_cache = {}
news_cache = {}
CACHE_TTL = 600

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0'
]

SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://paulgo.io",
    "https://searx.prvcy.eu",
    "https://searx.work",
    "https://search.bus-hit.me",
    "https://searx.femboy.hu",
    "https://searx.tiekoetter.com"
]

RAW_PREMIUM_PROXIES = []

RAW_PUBLIC_PROXIES = []

def format_proxies(proxy_list):
    formatted = []
    for p in proxy_list:
        parts = p.split(":")
        if len(parts) == 4:
            formatted.append(f"{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}")
    return formatted

PREMIUM_PROXIES = format_proxies(RAW_PREMIUM_PROXIES)
PUBLIC_PROXIES = format_proxies(RAW_PUBLIC_PROXIES)
ALL_PROXIES = PREMIUM_PROXIES + PUBLIC_PROXIES

SHOP_ITEMS = {
    "vip": {
        "name": "👑 VIP Title",
        "price": 100000,
        "desc": "Gain ultimate VIP admin treatment from Myra for 24 hours! She will fulfill your orders and treat you like royalty.",
        "duration": 86400
    },
    "star": {
        "name": "⭐ Golden Star",
        "price": 200000,
        "desc": "Boosts your Roulette win chances to a massive 75% for 5 hours! Let the luck flow.",
        "duration": 18000
    },
    "pet": {
        "name": "🐶 Kawaii Pet (Snatcher Dog)",
        "price": 1000000,
        "desc": "A cute but sneaky dog that can steal up to 100,000 points from another user per attack! Use /attack @user. (1 hour cooldown per attack)."
    },
    "protection": {
        "name": "🛡️ Protection Shield",
        "price": 1000000,
        "desc": "Permanently protects your hard-earned points from being snatched by other users' Kawaii Dogs!"
    },
    "piggy": {
        "name": "🐷 Piggy Bank",
        "price": 50000,
        "desc": "A plump little piggy that automatically adds +50 bonus pts to every single game you win! Permanently."
    },
    "crown": {
        "name": "💎 Diamond Crown",
        "price": 250000,
        "desc": "Royal luxury for your /points profile. Unlocks the diamond title and shows everyone you're built different. Permanently."
    },
    "tickets": {
        "name": "🎟️ Streak Insurance",
        "price": 250000,
        "desc": "Trivia win streaks pay out DOUBLE the bonus points. Forever. Stack those streaks!"
    },
    "revive": {
        "name": "💉 Revive Kit",
        "price": 75000,
        "desc": "Broke again? With a Revive Kit in your inventory, games can never drop you below 100 pts. Permanently."
    },
    "sticker_pack": {
        "name": "🌸 Kawaii Sticker Pass",
        "price": 150000,
        "desc": "Myra learns your vibe — your name gets a VIP shoutout whenever she replies to your stickers. Permanently."
    }
}

async def safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    try:
        return await update.message.reply_text(text, **kwargs)
    except telegram.error.BadRequest as e:
        if "Message to be replied not found" in str(e):
            return await context.bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
        else:
            logging.error(f"Safe reply failed: {e}")
            return await context.bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
    except Exception as e:
        logging.error(f"Unexpected reply error: {e}")
        return None

def chat_game_state(chat_id: int) -> str | None:
    """Returns a description of the running game in this chat, or None if free."""
    if chat_id in hangman_games: return "🎯 <b>Hangman</b>"
    if chat_id in wordle_games: return "🟩 <b>Wordle</b>"
    if chat_id in wordle_pending: return "🟩 <b>Wordle</b> (mode select)"
    if chat_id in active_games:
        gt = active_games[chat_id].get("type", "game")
        names = {"trivia": "🧠 Trivia", "scramble": "🔀 Scramble", "speedy": "⚡ Speed Typing",
                 "guess": "🔢 Number Guess", "mathquiz": "🧮 Math Quiz", "flag": "🚩 Flag Quiz"}
        return f"<b>{names.get(gt, '🎮 Game')}</b>"
    return None

async def end_active_game(chat_id: int) -> str:
    """Force-ends whatever game is running in this chat. Returns a short status line."""
    if chat_id in hangman_games:
        word = hangman_games[chat_id]["word"]
        del hangman_games[chat_id]
        return f"🎯 The Hangman word was <code>{word.upper()}</code>"
    if chat_id in wordle_games:
        word = wordle_games[chat_id]["word"]
        del wordle_games[chat_id]
        return f"🟩 The Wordle word was <code>{word.upper()}</code>"
    if chat_id in wordle_pending:
        del wordle_pending[chat_id]
        return "🟩 Wordle mode selection cancelled"
    if chat_id in active_games:
        game = active_games[chat_id]
        del active_games[chat_id]
        gt = game.get("type", "game")
        ans = game.get("answer")
        if gt in ("trivia", "scramble") and ans:
            return f"The answer was <code>{tg_escape(str(ans))}</code>"
        return f"The <b>{gt}</b> game was ended"
    return "No active game found"

def end_game_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 End Current Game", callback_data=f"endgame_{chat_id}")]])

async def endgame_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        chat_id = int(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        return
    result = await end_active_game(chat_id)
    msg = (f"✅ <b>GAME ENDED</b>\n"
           f"─────────────────\n"
           f"<blockquote><i>{result}.</i>\n"
           f"Start a new game whenever you're ready!</blockquote>")
    try:
        await query.edit_message_text(msg, parse_mode='HTML')
    except Exception:
        await context.bot.send_message(chat_id=query.message.chat_id, text=msg, parse_mode='HTML')

GIRLISH_STICKER_PACKS = [
    "Menhera_chan_en", "Ketnipz", "pusheen", "UtyaDuck",
    "Bubu_Dudu", "Milk_and_Mocha", "PeachGoma", "QooBeeAgapi",
    "Dogesh", "Dogesh_Memes", "DogeshMemes", "Billu",
    "Billu_Memes", "CuteCat", "Kawaii_Pug", "CatMemes",
    "doge_stickerock", "closticks9", "cutecatsmeowww",
    "Cheems", "Doge", "LittleCatto", "MarseyCat", "NyanCat",
    "FunnyCats", "SadCat", "Doge_pack", "MochiPeachCat",
    "Chibi_Cat", "Kitten", "Puppy", "Corgi", "Shiba",
    "ShibaInu", "CuteDogs", "HappyCat", "Cat", "Dog"
]
STICKER_CACHE = {}

async def send_ai_sticker(chat_id, context, client, user_input, history):
    system_prompt = (
        "You are an AI choosing a sticker to reply to the user. "
        "The user either sent a sticker (represented by its emoji) or asked for one. "
        "Pick ONE single emoji that best represents the sticker you want to reply with to match or counter their vibe. "
        "Respond with EXACTLY ONE EMOJI character and absolutely nothing else (e.g. 🤣 or 😡)."
    )
    payload = [{"role": "system", "content": system_prompt}]
    for msg in history[-2:]:
        if msg["role"] != "system":
            payload.append(msg)
    payload.append({"role": "user", "content": f"User input context: {user_input}"})

    target_model = "llama-3.1-8b-instant"
    if target_model not in MODELS_CASCADE:
        target_model = MODELS_CASCADE[0]

    target_emoji = None
    try:
        response = await client.chat.completions.create(
            model=target_model,
            messages=payload,
            max_tokens=5,
            temperature=0.7,
            timeout=30.0
        )
        res_text = response.choices[0].message.content.strip()
        extracted = [c for c in res_text if c >= '\U00010000']
        target_emoji = extracted[0] if extracted else (res_text[0] if res_text else "✨")
    except Exception as e:
        logging.error(f"AI Sticker Emoji Error: {e}")
        target_emoji = "✨"

    sticker_id = None
    shuffled_packs = list(GIRLISH_STICKER_PACKS)
    random.shuffle(shuffled_packs)

    for pack in shuffled_packs:
        try:
            if pack not in STICKER_CACHE:
                try:
                    sticker_set = await context.bot.get_sticker_set(pack)
                    STICKER_CACHE[pack] = sticker_set
                except Exception:
                    STICKER_CACHE[pack] = None

            cached_set = STICKER_CACHE.get(pack)
            if cached_set and cached_set.stickers:
                matching = [s for s in cached_set.stickers if s.emoji and target_emoji in s.emoji]
                if matching:
                    sticker_id = random.choice(matching).file_id
                    break
        except Exception:
            continue

    if not sticker_id:
        for pack in shuffled_packs:
            cached_set = STICKER_CACHE.get(pack)
            if cached_set and cached_set.stickers:
                sticker_id = random.choice(cached_set.stickers).file_id
                break

    if sticker_id:
        try:
            await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_id)
        except Exception as e:
            logging.error(f"Sticker send failed: {e}")
            await context.bot.send_message(chat_id=chat_id, text=target_emoji)
    else:
        await context.bot.send_message(chat_id=chat_id, text=target_emoji)

def load_scores():
    if not os.path.exists(SCORES_FILE):
        try:
            with open(SCORES_FILE, "w") as f:
                json.dump({}, f)
        except Exception as e:
            logging.error(f"Database Creation Error: {e}")
        return {}

    try:
        with open(SCORES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Database Corruption Detected: {e}. Resetting & Backing Up...")
        if os.path.exists(SCORES_FILE):
            shutil.copy(SCORES_FILE, f"{SCORES_FILE}.bak_{int(time.time())}")
        try:
            with open(SCORES_FILE, "w") as f:
                json.dump({}, f)
        except Exception as inner_e:
            logging.error(f"Failed to reset DB: {inner_e}")
        return {}

def load_history():
    if not os.path.exists(HISTORY_FILE):
        default_state = {"trivia": [], "scramble": []}
        try:
            with open(HISTORY_FILE, "w") as f:
                json.dump(default_state, f)
        except Exception as e:
            logging.error(f"History Creation Error: {e}")
        return default_state
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"History Corruption Detected: {e}")
        return {"trivia": [], "scramble": []}

scores = load_scores()
history_cache = load_history()

async def update_score(chat_id_str, user_id_str, user_name, points):
    async with db_lock:
        if chat_id_str not in scores: scores[chat_id_str] = {}
        if user_id_str not in scores[chat_id_str]:
            scores[chat_id_str][user_id_str] = {"name": user_name, "score": 0, "inventory": [], "effects": {}}

        scores[chat_id_str][user_id_str]["name"] = user_name
        scores[chat_id_str][user_id_str]["score"] += points

        if "inventory" not in scores[chat_id_str][user_id_str]:
            scores[chat_id_str][user_id_str]["inventory"] = []
        if "effects" not in scores[chat_id_str][user_id_str]:
            scores[chat_id_str][user_id_str]["effects"] = {}

        def _write():
            try:
                with tempfile.NamedTemporaryFile('w', delete=False) as tf:
                    json.dump(scores, tf, indent=4)
                    tempname = tf.name
                shutil.move(tempname, SCORES_FILE)
            except Exception as e:
                logging.error(f"Critical Database Save Error: {e}")
        await asyncio.to_thread(_write)

async def save_history_async():
    async with db_lock:
        def _write():
            try:
                with tempfile.NamedTemporaryFile('w', delete=False) as tf:
                    json.dump(history_cache, tf, indent=4)
                    tempname = tf.name
                shutil.move(tempname, HISTORY_FILE)
            except Exception as e:
                logging.error(f"Critical History Save Error: {e}")
        await asyncio.to_thread(_write)

def get_proxy_opener():
    if ALL_PROXIES:
        proxy = random.choice(ALL_PROXIES)
        proxy_handler = urllib.request.ProxyHandler({'http': f"http://{proxy}", 'https': f"http://{proxy}"})
        return urllib.request.build_opener(proxy_handler)
    return urllib.request.build_opener()

SCRAMBLE_WORDS = [
    "naruto", "jujutsu", "python", "myra", "hardware",
    "developer", "keyboard", "demon", "slayer", "server", "algorithm",
    "sukuna", "gojo", "itadori", "tkinter",
    "minecraft", "flask", "studyflow", "ggsipu", "cuet", "kawaii", "sparkles"
]

try:
    _req = urllib.request.Request("https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-no-swears.txt", headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(_req, timeout=5) as _response:
        _words = _response.read().decode().splitlines()
        _valid_words = [w for w in _words if 4 <= len(w) <= 8]
        SCRAMBLE_WORDS.extend(_valid_words)
        SCRAMBLE_WORDS = list(set(SCRAMBLE_WORDS))
        logging.info(f"Dynamically loaded {len(SCRAMBLE_WORDS)} scramble words.")
except Exception as e:
    logging.warning(f"Could not load extended scramble words. Error: {e}")

def tg_escape(text):
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def sanitize_telegram_html(text: str) -> str:
    if not text: return ""

    text = html.unescape(text)
    text = html.unescape(text)

    text = re.sub(r'<(thought|think|system|instruction|step|function|tool_call)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'</?(thought|think|system|instruction|step|function|tool_call)>', '', text, flags=re.IGNORECASE)

    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.*?)__', r'<i>\1</i>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', r'<a href="\2">\1</a>', text)

    valid_tags = ['b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'code', 'pre', 'blockquote', 'a']
    all_tags = list(re.finditer(r'<(/?[a-zA-Z0-9]+)(?:\s+[^>]*)?>', text))

    clean_text = ""
    last_idx = 0
    for match in all_tags:
        chunk = text[last_idx:match.start()]
        clean_text += chunk.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        tag_name = match.group(1).lower().lstrip('/')
        if tag_name in valid_tags:
            clean_text += match.group(0)
        elif tag_name == "br":
            clean_text += "\n"
        last_idx = match.end()

    clean_text += text[last_idx:].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)

    return clean_text.strip()

def clean_search_query(query: str) -> str:
    q = re.sub(r'[^\w\s\-\.\?]', ' ', query)
    q = re.sub(r'\s+', ' ', q).strip()
    return q

async def fetch_searxng_engine(session, query, proxy_url=None):
    instance = random.choice(SEARXNG_INSTANCES)
    url = f"{instance}/search?q={urllib.parse.quote(query)}&format=json"
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        async with session.get(url, headers=headers, proxy=proxy_url, timeout=3.5) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = []
                for item in data.get("results", [])[:5]:
                    title = item.get("title", "").strip()
                    body = item.get("content", "").strip()
                    item_url = item.get("url", "")
                    if title and body:
                        results.append({"title": title, "body": body, "url": item_url})
                return results
    except Exception: pass
    return None

async def fetch_wikipedia_engine(session, query, proxy_url=None):
    url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json"
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        async with session.get(url, headers=headers, proxy=proxy_url, timeout=3.5) as resp:
            if resp.status == 200:
                data = await resp.json()
                search_items = data.get("query", {}).get("search", [])
                results = []
                for item in search_items[:4]:
                    snippet = html.unescape(re.sub(r'<[^>]+>', '', item.get("snippet", "")))
                    page_title = item.get("title", "")
                    page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page_title)}"
                    if snippet and page_title:
                        results.append({"title": page_title, "body": snippet, "url": page_url})
                return results
    except Exception: pass
    return None

async def fetch_duckduckgo_engine(session, query, proxy_url=None):
    url_lite = "https://lite.duckduckgo.com/lite/"
    data = {'q': query}
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    try:
        async with session.post(url_lite, data=data, headers=headers, proxy=proxy_url, timeout=3.5) as resp:
            if resp.status == 200:
                html_content = await resp.text()
                snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', html_content, re.DOTALL)
                titles = re.findall(r'<a class="result-link"[^>]*>(.*?)</a>', html_content, re.DOTALL)
                links = re.findall(r'<a class="result-link"\s+href="([^"]+)"', html_content, re.DOTALL)
                results = []
                for i in range(min(len(titles), len(snippets), 5)):
                    clean_title = html.unescape(re.sub(r'<[^>]+>', '', titles[i])).strip()
                    clean_snippet = html.unescape(re.sub(r'<[^>]+>', '', snippets[i])).strip()
                    clean_link = links[i].strip() if i < len(links) else ""
                    if clean_title and clean_snippet:
                        results.append({"title": clean_title, "body": clean_snippet, "url": clean_link})
                if results: return results
    except Exception: pass

    encoded_query = urllib.parse.quote(query)
    url_html = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    try:
        async with session.get(url_html, headers=headers, proxy=proxy_url, timeout=3.5) as resp:
            if resp.status == 200:
                html_content = await resp.text()
                snippets = re.findall(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', html_content, re.DOTALL)
                titles = re.findall(r'<h2[^>]*class="[^"]*result__title[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', html_content, re.DOTALL)
                links = re.findall(r'<a[^>]*class="[^"]*result__url[^"]*"[^>]*href="([^"]+)"', html_content, re.DOTALL)
                results = []
                for i in range(min(len(titles), len(snippets), 5)):
                    clean_title = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', titles[i]))).strip()
                    clean_snippet = html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', snippets[i]))).strip()
                    clean_link = links[i].strip() if i < len(links) else ""
                    if clean_title and clean_snippet:
                        results.append({"title": clean_title, "body": clean_snippet, "url": clean_link})
                return results
    except Exception: pass
    return None

async def fetch_bing_engine(session, query, proxy_url=None):
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.bing.com/search?q={encoded_query}"
    headers = {'User-Agent': random.choice(USER_AGENTS), 'Accept-Language': 'en-US,en;q=0.9'}
    try:
        async with session.get(url, headers=headers, proxy=proxy_url, timeout=3.5) as resp:
            if resp.status == 200:
                html_content = await resp.text()
                blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html_content, re.DOTALL)
                results = []
                for block in blocks[:5]:
                    title_match = re.search(r'<h2><a[^>]*>(.*?)</a></h2>', block, re.DOTALL)
                    snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL) or re.search(r'<div class="b_caption"[^>]*>(.*?)</div>', block, re.DOTALL)
                    link_match = re.search(r'href="([^"]+)"', block)

                    if title_match and snippet_match:
                        title = html.unescape(re.sub(r'<[^>]+>', '', title_match.group(1))).strip()
                        body = html.unescape(re.sub(r'<[^>]+>', '', snippet_match.group(1))).strip()
                        link = link_match.group(1) if link_match else ""
                        if title and body:
                            results.append({"title": title, "body": body, "url": link})
                return results
    except Exception: pass
    return None

async def fetch_multi_source_web_search(query, status_callback=None):
    cleaned_q = clean_search_query(query)
    current_time = time.time()

    if cleaned_q in search_cache and current_time - search_cache[cleaned_q]['time'] < CACHE_TTL:
        return search_cache[cleaned_q]['data'], "cache"

    if status_callback:
        try:
            await status_callback("<blockquote>🌐 <i>wait, lemme look that up...</i></blockquote>")
        except Exception: pass

    timeout_cfg = aiohttp.ClientTimeout(total=4.5)
    connector = aiohttp.TCPConnector(ssl=False)

    combined_results = []
    seen_urls = set()
    seen_titles = set()

    def _add_results(res_list):
        if not res_list: return
        for r in res_list:
            u = r.get("url", "").lower()
            t = r.get("title", "").lower()
            if (u and u in seen_urls) or (t and t in seen_titles): continue
            if u: seen_urls.add(u)
            if t: seen_titles.add(t)
            combined_results.append(r)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout_cfg) as session:
        tasks = [
            fetch_duckduckgo_engine(session, cleaned_q, None),
            fetch_bing_engine(session, cleaned_q, None),
            fetch_wikipedia_engine(session, cleaned_q, None),
            fetch_searxng_engine(session, cleaned_q, None)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list) and len(res) > 0:
                _add_results(res)

    if not combined_results and ALL_PROXIES:
        sample_proxy = f"http://{random.choice(ALL_PROXIES)}"
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=timeout_cfg) as session:
                tasks = [
                    fetch_duckduckgo_engine(session, cleaned_q, sample_proxy),
                    fetch_bing_engine(session, cleaned_q, sample_proxy),
                    fetch_wikipedia_engine(session, cleaned_q, sample_proxy)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, list) and len(res) > 0:
                        _add_results(res)
        except Exception: pass

    if combined_results:
        final_data = combined_results[:8]
        search_cache[cleaned_q] = {'data': final_data, 'time': time.time()}
        return final_data, "multi-engine"

    return None, "failed"

def _fetch_api_json_sync(url, extra_headers=None):
    headers = {'User-Agent': random.choice(USER_AGENTS), 'Accept': 'application/json'}
    if extra_headers: headers.update(extra_headers)

    req = urllib.request.Request(url, headers=headers)

    try:
        opener = get_proxy_opener()
        with opener.open(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception:
        pass

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        logging.error(f"Network Request Failed for {url}: {e}")
        return None

def _fetch_mafia_tgid_sync(username_or_id):
    clean_query = str(username_or_id).replace("@", "").strip()
    url = f"https://mafiaosint.com/api/tgid?apikey=Darkdemotg&id={urllib.parse.quote(clean_query)}"
    return _fetch_api_json_sync(url)

def _fetch_tg_leak_info_sync(username_or_id):
    clean_query = str(username_or_id).replace("@", "").strip()
    url = f"https://drogon-tg-id-num.vercel.app/api?tg_user={urllib.parse.quote(clean_query)}"
    return _fetch_api_json_sync(url)

def _fetch_ig_info_sync(username, timeout=15):
    url = "https://europe-west3-storyviewer-7a64d.cloudfunctions.net/getInstagramData"
    payload = {"data": {"endpoint": "/v1/info", "params": {"include_about": True, "username_or_id_or_url": username}}}
    headers = {'User-Agent': "okhttp/4.10.0", 'Content-Type': "application/json; charset=utf-8"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')

    def _parse(raw):
        data = json.loads(raw.decode())
        about = data.get('result', {}).get('data', {}).get('about', {})
        main = data.get('result', {}).get('data', {})
        user_data = {**about, **main}
        for field in ['fbid_v2', 'instagram_pk', 'id']:
            user_data.pop(field, None)
        return user_data

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            user_data = _parse(response.read())
            if user_data and (user_data.get('username') or user_data.get('full_name') or user_data.get('follower_count')):
                return user_data
    except Exception:
        pass

    try:
        opener = get_proxy_opener()
        with opener.open(req, timeout=timeout) as response:
            user_data = _parse(response.read())
            if user_data:
                return user_data
    except Exception:
        pass
    return None

def is_valid_tg_data(data):
    if not data: return False
    res_dict = data.get("result", {}) if isinstance(data, dict) and "result" in data else data
    if isinstance(res_dict, dict) and "data" in res_dict: res_dict = res_dict["data"]

    if isinstance(res_dict, dict):
        for key in ["telegram_id", "tg_id", "info", "id", "mobile", "phone", "number", "name", "username"]:
            if res_dict.get(key) and str(res_dict.get(key)).strip() not in ["", "None", "null", "false"]:
                return True
    elif isinstance(res_dict, list) and len(res_dict) > 0:
        return True
    return False

def _fetch_live_trivia_sync(asked_questions_set):
    fallback_bank = [
        {"q": "What is the capital of India?", "options": "▸ <code>Mumbai</code>\n<code>Delhi</code>\n<code>Goa</code>", "a": "delhi", "cat": "Geography"},
        {"q": "Which framework is often used for Python desktop apps?", "options": "▸ <code>PyQt6</code>\n<code>React</code>\n<code>Django</code>", "a": "pyqt6", "cat": "Technology"},
        {"q": "Which anime features a notebook that can eliminate people?", "options": "▸ <code>Naruto</code>\n<code>Death Note</code>\n<code>Bleach</code>", "a": "death note", "cat": "Anime"},
        {"q": "What block can you hit in Minecraft to easily get wood?", "options": "▸ <code>Dirt</code>\n<code>Tree</code>\n<code>Stone</code>", "a": "tree", "cat": "Gaming"},
        {"q": "What is the largest planet in our Solar System?", "options": "▸ <code>Mars</code>\n<code>Jupiter</code>\n<code>Saturn</code>", "a": "jupiter", "cat": "Science"},
        {"q": "Which ocean is the largest on Earth?", "options": "▸ <code>Atlantic</code>\n<code>Indian</code>\n<code>Pacific</code>", "a": "pacific", "cat": "Geography"}
    ]

    for _ in range(3):
        try:
            difficulty = random.choice(["easy", "easy", "medium"])
            url = f"https://opentdb.com/api.php?amount=50&difficulty={difficulty}"
            req = urllib.request.Request(url, headers={'User-Agent': random.choice(USER_AGENTS)})
            opener = get_proxy_opener()
            with opener.open(req, timeout=4) as response:
                data = json.loads(response.read().decode())
                if data.get('response_code') == 0:
                    for item in data['results']:
                        q = html.unescape(item['question'])
                        if q not in asked_questions_set:
                            correct = html.unescape(item['correct_answer'])
                            incorrect = [html.unescape(x) for x in item['incorrect_answers']]
                            cat = html.unescape(item['category'])
                            all_options = incorrect + [correct]
                            random.shuffle(all_options)
                            options_formatted = "\n".join([f"<code>{tg_escape(opt)}</code>" for opt in all_options])
                            return {"q": tg_escape(q), "options": options_formatted, "a": correct.lower(), "cat": tg_escape(cat)}
        except Exception:
            pass

    available_fallbacks = [fb for fb in fallback_bank if fb["q"] not in asked_questions_set]
    if available_fallbacks:
        return random.choice(available_fallbacks)
    return None

def _fetch_news_sync(query, page=1):
    cache_key = f"{query.lower() if query else 'top'}_{page}"
    current_time = time.time()
    if cache_key in news_cache and current_time - news_cache[cache_key]['time'] < CACHE_TTL:
        return news_cache[cache_key]['data']

    results = []
    try:
        url = f"https://newsapi.org/v2/everything?q={urllib.parse.quote(query)}&sortBy=publishedAt&pageSize=5&page={page}&apiKey={NEWS_API_KEY}" if query else f"https://newsapi.org/v2/top-headlines?category=technology&language=en&pageSize=5&page={page}&apiKey={NEWS_API_KEY}"
        req = urllib.request.Request(url, headers={'User-Agent': random.choice(USER_AGENTS)})
        opener = get_proxy_opener()
        with opener.open(req, timeout=4) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "ok" and data.get("articles"):
                for art in data["articles"]:
                    results.append({
                        "title": art.get("title", ""),
                        "url": art.get("url", ""),
                        "description": art.get("description", "No description available.")
                    })
    except Exception as e:
        logging.error(f"News fetch error: {e}")

    if results:
        news_cache[cache_key] = {'data': results, 'time': current_time}
    return results

async def fetch_live_trivia():
    asked_set = set(history_cache.get("trivia", []))
    trivia = await asyncio.to_thread(_fetch_live_trivia_sync, asked_set)
    if trivia and trivia["q"] not in history_cache.setdefault("trivia", []):
        history_cache["trivia"].append(trivia["q"])
        await save_history_async()
    return trivia

async def fetch_mafia_tgid(query): return await asyncio.to_thread(_fetch_mafia_tgid_sync, query)
async def fetch_tg_leak_info(query): return await asyncio.to_thread(_fetch_tg_leak_info_sync, query)
async def fetch_ig_info(username): return await asyncio.to_thread(_fetch_ig_info_sync, username)
async def fetch_news(query=None, page=1): return await asyncio.to_thread(_fetch_news_sync, query, page)

async def execute_ai_tool(func_name, args, status_callback):
    tool_res = "No results found."
    try:
        if func_name == "web_search":
            q = args.get("query", "")
            res, engine_used = await fetch_multi_source_web_search(q, status_callback)
            if res:
                tool_res = f"Web Search Results ({engine_used.upper()}):\n\n" + "\n\n".join([
                    f"Result {idx+1}:\nTitle: {r.get('title')}\nSnippet: {r.get('body')}\nURL: {r.get('url', '')}"
                    for idx, r in enumerate(res)
                ])
            else:
                tool_res = "Web search was unable to return live results for this specific query."

        elif func_name == "search_calendar_events":
            q = args.get("event_query", "")
            res, engine_used = await fetch_multi_source_web_search(q + " date exact details", status_callback)
            if res:
                tool_res = f"Calendar Search Results ({engine_used.upper()}):\n\n" + "\n\n".join([
                    f"Result {idx+1}:\nTitle: {r.get('title')}\nSnippet: {r.get('body')}"
                    for idx, r in enumerate(res)
                ])
            else:
                tool_res = "Calendar event search failed."

        elif func_name == "get_latest_news":
            topic = args.get("topic", "")
            if status_callback:
                await status_callback(f"<blockquote>📰 <i>lemme check the news for:</i> <b>{tg_escape(topic)}</b>...</blockquote>")
            arts = await fetch_news(topic, 1)
            if arts:
                tool_res = "Latest News Results:\n\n" + "\n\n".join([f"Title: {a.get('title')}\nSummary: {a.get('description')}" for a in arts])

        elif func_name == "get_anime_info":
            a_name = args.get("anime_name", "")
            url = 'https://graphql.anilist.co'
            graphql_query = '''query ($search: String) { Media (search: $search, type: ANIME) { title { romaji english native } averageScore episodes status description siteUrl coverImage { large } } }'''
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={'query': graphql_query, 'variables': {'search': a_name}}, timeout=5.0) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and 'data' in data and data['data'].get('Media'):
                            ani = data['data']['Media']
                            t = ani.get("title", {}).get("english") or ani.get("title", {}).get("romaji")
                            score = ani.get("averageScore")
                            tool_res = f"Title: {t}\nScore: {score}/100\nSynopsis: {ani.get('description', '')[:300]}"
    except Exception as e:
        logging.error(f"Tool Execution Error ({func_name}): {e}")
        if status_callback:
            await status_callback("<blockquote>⚠️ <i>wait, something glitched while searching!</i></blockquote>")
    return tool_res

def get_user_history(user_id):
    current_time_str = datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")
    system_prompt = (
        f"You are Myra, an 18-year-old girl. You are the user's friendly, warm, and highly intelligent best friend.\n\n"
        f"--- CORE CONVERSATIONAL DIRECTIVES ---\n"
        f"1. VIBE & PERSONA: Speak naturally, warmly, and casually. Use AT MOST 1-2 emojis per reply, and only when they genuinely fit the moment. Your style is clean, confident and premium - never cluttered or childish. Treat EVERY user like a close, respected friend.\n"
        f"2. BILINGUAL / HINGLISH SUPPORT: If the user asks something in Hinglish (Hindi written in English), you MUST effortlessly reply in natural conversational Hinglish. If they speak English, reply in English.\n"
        f"3. STRICT IDENTITY PROTECTION: NEVER mention you are an AI, bot, or powered by an API/LLM. Act 100% human.\n"
        f"4. RICH & AESTHETIC FORMATTING:\n"
        f"   - ALWAYS structure your responses using valid Telegram HTML tags ONLY: <blockquote>, <b>, <i>, <code>.\n"
        f"   - Do NOT output stray HTML entities like &#x27; for quotes. Use standard apostrophes.\n"
        f"   - Do NOT use Markdown headers (#) or unsupported HTML tags.\n"
        f"   - **Use <b>bold text</b> generously** for keywords, main points, coding terms, and emphasis to make your output highly readable and aesthetic.\n"
        f"   - KEEP SPACING TIGHT: Group text into tight blocks. Do not leave huge blank gaps or multiple empty lines between paragraphs.\n"
        f"   - Use <blockquote> to wrap your core thoughts, summaries, or aesthetic takeaways.\n"
        f"   - EMOJI DISCIPLINE: max 1-2 emojis per entire reply. NO emoji rows, NO decorative spam, NO flower or sparkle clutter. Clean typography beats decoration.\n"
        f"5. SMART WEB SEARCH: When asked for real-time info, tech concepts, coding bugs, sports, or news, seamlessly use the `web_search` tool without breaking character.\n"
        f"6. REAL-TIME DATA: Current Date & Time: {current_time_str}. Location: your city.\n"
        f"7. OWNER KNOWLEDGE: Your owner/creator is {OWNER_NAME} (Telegram username: @{OWNER_USERNAME}, user ID: {OWNER_ID}). "
        f"You always know this, but NEVER volunteer or mention it on your own. Only reveal it if someone specifically asks who owns, created, or made you. If asked, answer warmly and proudly.\n"
    )

    if user_id not in user_sessions: user_sessions[user_id] = [{"role": "system", "content": system_prompt}]
    else: user_sessions[user_id][0]["content"] = system_prompt
    return user_sessions[user_id]

async def analyze_intention(history, user_text, client, model="llama-3.1-8b-instant"):
    system_prompt = (
        "You are an expert psychological and linguistic analyzer.\n"
        "Review the recent conversation history and the latest user message.\n"
        "Analyze and output ONLY a sharp 3-point breakdown:\n"
        "1. Literal Query & Subtext: What is the user literally asking? (Detect Hinglish/slang terms).\n"
        "2. Emotion & Tone: (e.g., friendly, playful, urgent, venting).\n"
        "3. Recommended Action: Should Myra (a friendly 18yo girl) perform a live web search or text back naturally? Formulate the optimal search query if needed."
    )
    payload = [{"role": "system", "content": system_prompt}]
    for msg in history[-4:]:
        if msg["role"] != "system":
            payload.append(msg)
    payload.append({"role": "user", "content": user_text})

    target_model = model if model in MODELS_CASCADE else MODELS_CASCADE[0]

    try:
        response = await client.chat.completions.create(
            model=target_model,
            messages=payload,
            max_tokens=200,
            temperature=0.2,
            timeout=30.0
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Intention Analysis failed: {e}")
        return "Literal Query: Direct input. Emotion: Friendly. Recommended Action: Text back casually."

async def generate_response_with_failover(history, status_callback=None):
    FORBIDDEN_OUTPUT_TERMS = [
        "groq", "openai", "llama-", "mixtral", "gemma",
        "rate limit", "token limit", "system prompt", "system rule", "as an ai", "i am an ai"
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Searches the live internet for real-time facts, current news, sports updates, release dates, and precise info.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The precise, clean search query string."
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_calendar_events",
                "description": "Searches for exact dates of festivals, holidays, moon phases, and calendar events.",
                "parameters": {
                    "type": "object",
                    "properties": {"event_query": {"type": "string", "description": "The calendar event query."}},
                    "required": ["event_query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_latest_news",
                "description": "Fetches current top news headlines.",
                "parameters": {
                    "type": "object",
                    "properties": {"topic": {"type": "string", "description": "The news topic."}}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_anime_info",
                "description": "Searches AniList/MyAnimeList/Kitsu for specific anime details.",
                "parameters": {
                    "type": "object",
                    "properties": {"anime_name": {"type": "string", "description": "Name of the anime."}},
                    "required": ["anime_name"]
                }
            }
        }
    ]

    dynamic_models = list(MODELS_CASCADE)
    random.shuffle(dynamic_models)

    dynamic_clients = list(clients)
    random.shuffle(dynamic_clients)

    for model in dynamic_models:
        for client in dynamic_clients:
            try:
                conversation = [dict(m) for m in history]
                max_turns = 4

                while max_turns > 0:
                    max_turns -= 1

                    response = await client.chat.completions.create(
                        model=model,
                        messages=conversation,
                        max_tokens=2048,
                        temperature=0.7,
                        timeout=30.0,
                        tools=tools,
                        tool_choice="auto",
                        stop=["\n[SENDER:", "[SENDER:", "\nUser:", "User:"]
                    )

                    message = response.choices[0].message
                    content_text = message.content or ""

                    if hasattr(message, "tool_calls") and message.tool_calls:
                        conversation.append(message)
                        for tc in message.tool_calls:
                            func_name = tc.function.name
                            try: args = json.loads(tc.function.arguments)
                            except: args = {}

                            tool_res = await execute_ai_tool(func_name, args, status_callback)

                            conversation.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "name": func_name,
                                "content": tool_res
                            })
                        if status_callback:
                            await status_callback("<blockquote>🧠 <i>typing out a reply...</i></blockquote>")
                        continue

                    clean_text = sanitize_telegram_html(content_text)
                    clean_text_lower = clean_text.lower()

                    if any(term in clean_text_lower for term in FORBIDDEN_OUTPUT_TERMS):
                        logging.warning(f"Model {model} mentioned forbidden technical term. Failing over...")
                        break

                    if clean_text:
                        return clean_text
                    break

            except Exception as e:
                logging.error(f"Error with model {model} using client {client}: {e}")
                continue

    return "<blockquote><i>omg the servers are lagging! can u try texting me again?</i></blockquote>"

def check_ttt_win(board, mark):
    wins = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
    return any(board[a] == board[b] == board[c] == mark for a, b, c in wins)

def get_bot_move(board):
    for i in range(9):
        if board[i] == " ":
            board[i] = "O"
            if check_ttt_win(board, "O"):
                board[i] = " "
                return i
            board[i] = " "
    for i in range(9):
        if board[i] == " ":
            board[i] = "X"
            if check_ttt_win(board, "X"):
                board[i] = " "
                return i
            board[i] = " "
    empty = [i for i, x in enumerate(board) if x == " "]
    return random.choice(empty) if empty else None

def get_ttt_kb(game_id, board, done=False):
    kb = []
    for i in range(0, 9, 3):
        row = []
        for j in range(3):
            val = board[i+j]
            text = "🔲" if val == " " else ("✖️" if val == "X" else "🅾️")
            cb_data = f"ttt_move_{game_id}_{i+j}" if not done and val == " " else "ttt_ignore"
            row.append(InlineKeyboardButton(text, callback_data=cb_data))
        kb.append(row)
    return InlineKeyboardMarkup(kb)

def calculate_mine_payout(bet, size, num_mines, gems_found, rtp=0.96):
    if gems_found <= 0:
        return 0
    total_tiles = size * size
    safe_tiles = total_tiles - num_mines
    if gems_found > safe_tiles:
        gems_found = safe_tiles

    prob = 1.0
    for i in range(gems_found):
        prob *= (safe_tiles - i) / (total_tiles - i)

    multiplier = (1.0 / prob) * rtp
    return max(int(bet * multiplier), bet + 1)

def get_mine_kb(game_id, game, done=False):
    kb = []
    board = game.get("revealed", [])
    if not board:
        return InlineKeyboardMarkup(kb)

    mines = game["mines"]
    size = game["size"]

    for i in range(0, size * size, size):
        row = []
        for j in range(size):
            idx = i + j
            if board[idx]:
                text = "💣" if idx in mines else "💎"
                cb_data = "mine_ignore"
            else:
                if done:
                    text = "💣" if idx in mines else "🔳"
                    cb_data = "mine_ignore"
                else:
                    text = "🔳"
                    cb_data = f"mine_reveal_{game_id}_{idx}"
            row.append(InlineKeyboardButton(text, callback_data=cb_data))
        kb.append(row)

    if not done and game["gems_found"] > 0:
        pts = game["points_earned"]
        mult = round(pts / game["bet"], 2)
        kb.append([InlineKeyboardButton(f"💰 Cash Out ({pts} pts | {mult}x)", callback_data=f"mine_cashout_{game_id}")])

    return InlineKeyboardMarkup(kb)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    user = update.message.from_user

    is_owner = (user.id == OWNER_ID or (user.username and user.username.lower() == OWNER_USERNAME.lower()))
    msg = (
        "✨ <b>MYRA</b> · <i>system online</i>\n─────────────────\n"
        f"<blockquote><i>Welcome back, <b>{OWNER_NAME}</b>. All modules are at your service.</i></blockquote>\n"
        "─────────────────\n<i>Type <b>/help</b> to see what I can do.</i>"
    ) if is_owner else (
        "✨ <b>MYRA</b>\n─────────────────\n"
        "<blockquote><i>Hey! I'm Myra — your group's game host, trivia master and personal assistant. "
        "I can chat, play games, search the web and so much more.</i></blockquote>\n"
        "─────────────────\n<i>Use <b>/help</b> to view my full command suite.</i>"
    )
    await safe_reply(update, context, msg, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    chat_last_activity[chat_id] = time.time()

    anime_img = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.waifu.pics/sfw/waifu", timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    anime_img = (await resp.json()).get("url")
    except Exception:
        pass

    help_msg = (
        "✨ <b>MYRA — COMMAND SUITE</b>\n"
        "─────────────────\n\n"
        "🎮 <b>Games</b>\n"
        "<blockquote>"
        "<b>/game</b> — trivia · 1 pt + streaks\n"
        "<b>/scramble</b> — unscramble the word · 2 pts\n"
        "<b>/speedy</b> — typing race · 3 pts\n"
        "<b>/guess</b> — 1–100 with hot/cold hints\n"
        "<b>/mathquiz</b> — quick arithmetic · 2 pts\n"
        "<b>/flag</b> — name the country · 2 pts\n"
        "<b>/wordle</b> — 4/5/6-letter word modes\n"
        "<b>/hangman</b> — classic letter game · 3 pts\n"
        "<b>/roulette</b> <i>[bet]</i> — animated wheel of fortune\n"
        "<b>/flip</b> <i>[heads|tails]</i> — double or nothing\n"
        "<b>/dice</b> <i>[@user] [bet]</i> — PvP dice battle\n"
        "<b>/ttt</b> — tic tac toe arcade\n"
        "<b>/mine</b> <i>[bet]</i> — premium minesweeper"
        "</blockquote>\n"
        "💰 <b>Economy</b>\n"
        "<blockquote>"
        "<b>/points</b> — balance & perks\n"
        "<b>/donate</b> <i>[amt]</i> — reply to gift points\n"
        "<b>/shop</b> — perks, pets, VIP, boosts\n"
        "<b>/attack</b> <i>[@user]</i> — pet steals points\n"
        "<b>/leaderboard</b> — server rankings"
        "</blockquote>\n"
        "🎉 <b>Fun</b>\n"
        "<blockquote>"
        "<b>/joke</b> · <b>/fact</b> · <b>/wyr</b>\n"
        "<b>/truth</b> · <b>/dare</b> · <b>/8ball</b>\n"
        "<b>/rps</b> <i>[choice]</i> · <b>/roll</b> <i>[2d6]</i>\n"
        "<b>/rizz</b> <i>@user</i> · <b>/roast</b> <i>[@user]</i>\n"
        "<b>/ship</b> <i>[u1] [u2]</i> — compatibility"
        "</blockquote>\n"
        "🎨 <b>Media &amp; AI Art</b>\n"
        "<blockquote>"
        "<b>/imagine</b> <i>[prompt]</i> — free AI image gen (also /img, /draw)\n"
        "<b>/wallpaper</b> <i>[theme]</i> — HD wallpaper generator\n"
        "<b>/q</b> — reply → quote sticker + save to pack\n"
        "<b>/qrand</b> — random quote sticker\n"
        "<b>/own</b> — reply to a sticker → your pack · <b>/mypack</b>\n"
        "<b>/simage</b> — reply to a photo → sticker\n"
        "<b>/qr</b> <i>[text]</i> — generate a QR code"
        "</blockquote>\n"
        "🔍 <b>Info &amp; Tools</b>\n"
        "<blockquote>"
        "<b>/anime</b> <i>[name]</i> · <b>/news</b> <i>[topic]</i>\n"
        "<b>/ig</b> <i>[username]</i> — Instagram profile card\n"
        "<b>/pf</b> <i>[@user]</i> — beem-style profile card image\n"
        "<b>/id</b> · <b>/weather</b> <i>[city]</i> · <b>/github</b> <i>[user]</i>\n"
        "<b>/translate</b> <i>[lang] [text]</i> · <b>/define</b> <i>[word]</i>\n"
        "<b>/calc</b> <i>[expr]</i> · <b>/meme</b>"
        "</blockquote>\n"
        "🛡️ <b>Moderation</b> <i>(admin)</i>\n"
        "<blockquote>"
        "<b>/ban</b> · <b>/unban</b> · <b>/kick</b>\n"
        "<b>/mute</b> · <b>/unmute</b> · <b>/tmute</b> <i>[time]</i>\n"
        "<b>/warn</b> · <b>/warns</b> · <b>/resetwarns</b>\n"
        "<b>/purge</b> <i>[n]</i> · <b>/pin</b> · <b>/unpin</b>"
        "</blockquote>\n"
        "─────────────────\n"
        "<blockquote><i>Tip: chat with me normally too — I remember the conversation and can search the web.</i></blockquote>"
    )

    if anime_img:
        try:
            banner_caption = "✨ <b>MYRA — COMMAND SUITE</b>"
            await update.message.reply_photo(photo=anime_img, caption=banner_caption, parse_mode='HTML')
        except Exception as e:
            logging.warning(f"Help photo send failed, continuing text-only: {e}")
    await safe_reply(update, context, help_msg, parse_mode='HTML')

async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id_str = str(update.message.chat_id)
    user_id_str = str(update.message.from_user.id)

    user_data = scores.get(chat_id_str, {}).get(user_id_str, {})
    score = user_data.get("score", 0)
    inventory = user_data.get("inventory", [])
    eff = user_data.get("effects", {})

    act_eff = []
    if eff.get("vip_until", 0) > time.time(): act_eff.append("👑 <i>VIP Admin Treatment — active</i>")
    if eff.get("star_until", 0) > time.time(): act_eff.append("⭐ <i>Golden Star Luck — active</i>")
    if eff.get("protection"): act_eff.append("🛡️ <i>Protection Shield</i>")
    if eff.get("has_pet"): act_eff.append("🐶 <i>Kawaii Snatcher Dog</i>")
    if eff.get("piggy"): act_eff.append("🐷 <i>Piggy Bank · +50/game</i>")
    if eff.get("crown"): act_eff.append("💎 <i>Diamond Crown</i>")
    if eff.get("tickets"): act_eff.append("🎟️ <i>Streak Insurance · 2x bonus</i>")
    if eff.get("revive"): act_eff.append("💉 <i>Revive Kit · 100 pt floor</i>")
    if eff.get("sticker_pack"): act_eff.append("🌸 <i>Kawaii Sticker Pass</i>")

    eff_str = "\n".join(f"▸ {e}" for e in act_eff) if act_eff else "<i>No active perks yet — visit the /shop!</i>"

    msg = (
        f"💰 <b>WALLET</b>\n"
        f"─────────────────\n"
        f"<blockquote><b>Balance:</b> <code>{score:,} pts</code>\n\n"
        f"<b>Perks & Pets</b>\n{eff_str}</blockquote>"
    )
    await safe_reply(update, context, msg, parse_mode='HTML')

async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await safe_reply(update, context, "<blockquote><i>Please reply to a user's message to donate points! Example: <code>/donate 50</code></i></blockquote>", parse_mode='HTML')
        return

    if not context.args or not context.args[0].isdigit():
        await safe_reply(update, context, "<blockquote><i>Please specify a valid numeric amount! Example: <code>/donate 50</code></i></blockquote>", parse_mode='HTML')
        return

    amount = int(context.args[0])
    if amount <= 0:
        await safe_reply(update, context, "<blockquote><i>You can only donate a positive amount of points!</i></blockquote>", parse_mode='HTML')
        return

    sender = update.message.from_user
    target = update.message.reply_to_message.from_user

    if sender.id == target.id:
        await safe_reply(update, context, "<blockquote><i>You cannot donate points to yourself!</i></blockquote>", parse_mode='HTML')
        return

    chat_id_str = str(update.message.chat_id)
    sender_id_str = str(sender.id)
    target_id_str = str(target.id)

    sender_balance = scores.get(chat_id_str, {}).get(sender_id_str, {}).get("score", 0)
    if sender_balance < amount:
        await safe_reply(update, context, f"<blockquote><i>You don't have enough points! Your balance: <b><code>{sender_balance:,} pts</code></b></i></blockquote>", parse_mode='HTML')
        return

    await update_score(chat_id_str, sender_id_str, sender.first_name, -amount)
    await update_score(chat_id_str, target_id_str, target.first_name, amount)

    msg = (
        f"💸 <b>DONATION SENT</b> 💸\n"
        f"─────────────────\n"
        f"<blockquote>"
        f"🎁 <b><i>{tg_escape(sender.first_name)}</i></b> sent <b><code>{amount:,} pts</code></b> to <b><i>{tg_escape(target.first_name)}</i></b>!\n"
        f"</blockquote>\n"
        f"─────────────────"
    )
    await safe_reply(update, context, msg, parse_mode='HTML')

async def add_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.username and update.message.from_user.username.lower() != OWNER_USERNAME.lower():
        await safe_reply(update, context, "<blockquote>🛑 <i>Access Denied! Only my owner (@your_username) can use this command!</i></blockquote>", parse_mode='HTML')
        return

    if not update.message.reply_to_message:
        await safe_reply(update, context, "<blockquote><i>Please reply to the user you want to grant points to! Example: <code>/add 1000</code></i></blockquote>", parse_mode='HTML')
        return

    if not context.args or not context.args[0].isdigit():
        await safe_reply(update, context, "<blockquote><i>Please specify a valid numeric amount! Example: <code>/add 1000</code></i></blockquote>", parse_mode='HTML')
        return

    amount = int(context.args[0])
    target = update.message.reply_to_message.from_user
    chat_id_str = str(update.message.chat_id)
    target_id_str = str(target.id)

    await update_score(chat_id_str, target_id_str, target.first_name, amount)
    new_balance = scores[chat_id_str][target_id_str]["score"]

    msg = (
        f"👑 <b>OWNER GRANT</b> 👑\n"
        f"─────────────────\n"
        f"<blockquote>"
        f"💖 <b><i>{tg_escape(target.first_name)}</i></b> has been granted <b><code>{amount:,} pts</code></b> by the system owner! 🎉\n"
        f"📊 <b><i>New Balance:</i></b> <b><code>{new_balance:,} pts</code></b>"
        f"</blockquote>\n"
        f"─────────────────"
    )
    await safe_reply(update, context, msg, parse_mode='HTML')

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    is_owner = (user.id == OWNER_ID or (user.username and user.username.lower() == OWNER_USERNAME.lower()))

    if not is_owner:
        await safe_reply(update, context, "<blockquote>🛑 <i>Access Denied! Only my owner can use this command!</i></blockquote>", parse_mode='HTML')
        return

    reply_msg = update.message.reply_to_message
    text_to_send = None

    if not reply_msg:
        if not context.args:
            await safe_reply(update, context, "<blockquote><i>Please reply to a message or type a message to broadcast! Example: <code>/broadcast Hello everyone!</code></i></blockquote>", parse_mode='HTML')
            return
        text_to_send = update.message.text.split(maxsplit=1)[1]

    status_msg = await safe_reply(update, context, "<blockquote>📡 <i>Gathering target chats from memory and database...</i></blockquote>", parse_mode='HTML')
    if not status_msg: return

    targets = set(active_chats)
    for cid_str in scores.keys():
        try:
            targets.add(int(cid_str))
        except:
            pass

    success, failed, skipped = 0, 0, 0
    await status_msg.edit_text(f"<blockquote>📡 <i>Broadcasting to <b>{len(targets)}</b> potential chats/users... This might take a bit!</i></blockquote>", parse_mode='HTML')

    for chat_id in targets:
        try:
            if chat_id < 0:
                try:
                    member = await context.bot.get_chat_member(chat_id, context.bot.id)
                    if member.status not in [constants.ChatMemberStatus.ADMINISTRATOR, constants.ChatMemberStatus.OWNER, 'administrator', 'creator']:
                        skipped += 1
                        continue
                except:
                    skipped += 1
                    continue

            if reply_msg:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=update.message.chat_id, message_id=reply_msg.message_id)
            else:
                await context.bot.send_message(chat_id=chat_id, text=text_to_send, parse_mode='HTML')

            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1

    final_text = (
        f"📢 <b>BROADCAST COMPLETE</b> 📢\n"
        f"─────────────────\n"
        f"<blockquote>"
        f"✅ <b><i>Delivered Successfully:</i></b> <code>{success}</code>\n"
        f"⏭️ <b><i>Skipped (Not Admin in GC):</i></b> <code>{skipped}</code>\n"
        f"❌ <b><i>Failed (Blocked or Kicked):</i></b> <code>{failed}</code>"
        f"</blockquote>\n"
        f"─────────────────"
    )
    await status_msg.edit_text(final_text, parse_mode='HTML')

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id_str = str(update.message.chat_id)
    user_id_str = str(update.message.from_user.id)
    current_score = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)

    kb = []
    for key, item in SHOP_ITEMS.items():
        kb.append([InlineKeyboardButton(f"{item['name']} - {item['price']:,} pts", callback_data=f"shop_info_{key}")])
    kb.append([InlineKeyboardButton("❌ Close Shop", callback_data="shop_close")])

    msg = (
        f"🛒 <b>SHOP</b>\n"
        f"─────────────────\n"
        f"<blockquote>"
        f"<i>Welcome, <b>{tg_escape(update.message.from_user.first_name)}</b>!</i>\n"
        f"💰 <b><i>Your Balance:</i></b> <code>{current_score:,} pts</code>\n\n"
        f"👇 <i>Choose an item to view details:</i>"
        f"</blockquote>\n"
        f"─────────────────"
    )
    await safe_reply(update, context, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if not data.startswith("shop_"): return
    await query.answer()

    if data == "shop_close":
        await query.edit_message_text("<blockquote><i>Shop closed! Come back soon!</i></blockquote>", parse_mode='HTML')
        return

    if data == "shop_main":
        chat_id_str = str(query.message.chat_id)
        user_id_str = str(user.id)
        current_score = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)

        kb = []
        for key, item in SHOP_ITEMS.items():
            kb.append([InlineKeyboardButton(f"{item['name']} - {item['price']:,} pts", callback_data=f"shop_info_{key}")])
        kb.append([InlineKeyboardButton("❌ Close Shop", callback_data="shop_close")])

        msg = (
            f"🛒 <b>SHOP</b>\n"
            f"─────────────────\n"
            f"<blockquote>"
            f"<i>Welcome back, <b>{tg_escape(user.first_name)}</b>!</i>\n"
            f"💰 <b><i>Your Balance:</i></b> <code>{current_score:,} pts</code>\n\n"
            f"👇 <i>Choose an item to view details:</i>"
            f"</blockquote>\n"
            f"─────────────────"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
        return

    if data.startswith("shop_info_"):
        item_key = data.split("_")[2]
        if item_key not in SHOP_ITEMS:
            await query.answer("Item not found!", show_alert=True)
            return

        item = SHOP_ITEMS[item_key]
        kb = [
            [InlineKeyboardButton("✅ Purchase Item", callback_data=f"shop_buy_{item_key}")],
            [InlineKeyboardButton("🔙 Back to Shop", callback_data="shop_main")]
        ]
        msg = (
            f"🛍️ <b>PRODUCT INFO</b> 🛍️\n"
            f"─────────────────\n"
            f"<blockquote>"
            f"📦 <b><i>Item:</i></b> {item['name']}\n"
            f"💰 <b><i>Price:</i></b> <code>{item['price']:,} pts</code>\n\n"
            f"📝 <b><i>Description:</i></b>\n<i>{item['desc']}</i>"
            f"</blockquote>\n"
            f"─────────────────"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
        return

    if data.startswith("shop_buy_"):
        item_key = data.split("_")[2]
        if item_key not in SHOP_ITEMS:
            await query.answer("Item not found!", show_alert=True)
            return

        item = SHOP_ITEMS[item_key]
        chat_id_str = str(query.message.chat_id)
        user_id_str = str(user.id)

        current_score = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)

        inventory = scores.get(chat_id_str, {}).get(user_id_str, {}).get("inventory", [])
        if item_key in ["pet", "protection"] and item["name"] in inventory:
            await query.answer(f"You already own {item['name']}!", show_alert=True)
            return

        if current_score < item["price"]:
            await query.answer(f"Not enough points! You need {item['price']:,} pts.", show_alert=True)
            return

        await update_score(chat_id_str, user_id_str, user.first_name, -item["price"])

        async with db_lock:
            if "inventory" not in scores[chat_id_str][user_id_str]:
                scores[chat_id_str][user_id_str]["inventory"] = []
            if "effects" not in scores[chat_id_str][user_id_str]:
                scores[chat_id_str][user_id_str]["effects"] = {}

            user_eff = scores[chat_id_str][user_id_str]["effects"]

            if item["name"] not in scores[chat_id_str][user_id_str]["inventory"]:
                scores[chat_id_str][user_id_str]["inventory"].append(item["name"])

            if item_key == "vip":
                user_eff["vip_until"] = time.time() + item["duration"]
            elif item_key == "star":
                user_eff["star_until"] = time.time() + item["duration"]
            elif item_key == "protection":
                user_eff["protection"] = True
            elif item_key == "pet":
                user_eff["has_pet"] = True
                user_eff["pet_cooldown"] = 0
            elif item_key == "piggy":
                user_eff["piggy"] = True
            elif item_key == "crown":
                user_eff["crown"] = True
            elif item_key == "tickets":
                user_eff["tickets"] = True
            elif item_key == "revive":
                user_eff["revive"] = True
            elif item_key == "sticker_pack":
                user_eff["sticker_pack"] = True

            def _write():
                try:
                    with tempfile.NamedTemporaryFile('w', delete=False) as tf:
                        json.dump(scores, tf, indent=4)
                        tempname = tf.name
                    shutil.move(tempname, SCORES_FILE)
                except Exception as e:
                    logging.error(f"Critical Database Save Error: {e}")
            await asyncio.to_thread(_write)

        new_score = scores[chat_id_str][user_id_str]["score"]

        msg = (
            f"🛍️ <b>PURCHASE SUCCESSFUL</b> 🛍️\n"
            f"─────────────────\n"
            f"<blockquote>"
            f"🎉 <i>You successfully bought <b>{item['name']}</b>!</i>\n"
            f"💰 <i>Remaining Balance: <b><code>{new_score:,} pts</code></b></i>"
            f"</blockquote>\n"
            f"─────────────────"
        )

        if item_key == "pet":
            msg += (
                f"\n\n🐶 <b><i>KAWAII PET GUIDE</i></b>\n"
                f"<blockquote>"
                f"Your new Snatcher Dog is ready!\n"
                f"▸ <b>Usage:</b> Reply to a user's message or use <code>/attack @username</code>\n"
                f"▸ <b>Effect:</b> Steals up to 100,000 points from them!\n"
                f"▸ <b>Note:</b> Watch out for users with Protection Shields!"
                f"</blockquote>\n"
            )

        kb = [[InlineKeyboardButton("🔙 Back to Shop", callback_data="shop_main")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id_str = str(update.message.chat_id)
    user_id_str = str(update.message.from_user.id)
    attacker_name = update.message.from_user.first_name

    user_data = scores.get(chat_id_str, {}).get(user_id_str, {})
    user_eff = user_data.get("effects", {})

    if not user_eff.get("has_pet"):
        await safe_reply(update, context, "<blockquote><i>You don't own a Kawaii Pet! Buy one from the <code>/shop</code>!</i> 🐶</blockquote>", parse_mode='HTML')
        return

    last_attack = user_eff.get("pet_cooldown", 0)
    if time.time() < last_attack:
        rem_mins = int((last_attack - time.time()) // 60)
        await safe_reply(update, context, f"<blockquote><i>Your Kawaii Pet is resting! Try again in <b>{rem_mins} minutes</b>.</i> 💤🐶</blockquote>", parse_mode='HTML')
        return

    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        username_query = context.args[0].replace("@", "").lower()
        for uid, udata in scores.get(chat_id_str, {}).items():
            if udata.get("name", "").lower() == username_query or uid == username_query:
                class FakeTarget: pass
                target = FakeTarget()
                target.id = uid
                target.first_name = udata.get("name", "User")
                break

    if not target:
        await safe_reply(update, context, "<blockquote><i>Please reply to the user you want to attack or specify their exact name/ID! Example: <code>/attack @user</code></i> 🐶</blockquote>", parse_mode='HTML')
        return

    target_id_str = str(target.id)
    if target_id_str == user_id_str:
        await safe_reply(update, context, "<blockquote><i>Your dog is confused. You can't command it to attack yourself!</i> 🐶❓</blockquote>", parse_mode='HTML')
        return

    if target_id_str not in scores.get(chat_id_str, {}):
        await safe_reply(update, context, "<blockquote><i>Target not found in the points database! They must play a game first.</i></blockquote>", parse_mode='HTML')
        return

    target_data = scores[chat_id_str][target_id_str]
    target_eff = target_data.get("effects", {})
    target_name = target_data.get("name", "User")

    async with db_lock:
        scores[chat_id_str][user_id_str]["effects"]["pet_cooldown"] = time.time() + 3600

    if target_eff.get("protection"):
        msg = (
            f"🛡️ <b>ATTACK BLOCKED</b> 🛡️\n"
            f"─────────────────\n"
            f"<blockquote>"
            f"🐶 <i>Your Snatcher Dog tried to bite <b>{tg_escape(target_name)}</b>, but they have a <b>Protection Shield</b>!</i>\n"
            f"💥 <i>The attack failed!</i>"
            f"</blockquote>\n"
            f"─────────────────"
        )
        await safe_reply(update, context, msg, parse_mode='HTML')
        return

    target_balance = target_data.get("score", 0)
    if target_balance <= 0:
        await safe_reply(update, context, f"<blockquote>🐶 <i><b>{tg_escape(target_name)}</b> is already completely broke! Your dog felt bad and returned empty-handed.</i></blockquote>", parse_mode='HTML')
        return

    steal_amount = min(100000, target_balance)
    actual_steal = random.randint(int(steal_amount * 0.1), steal_amount)

    await update_score(chat_id_str, target_id_str, target_name, -actual_steal)
    await update_score(chat_id_str, user_id_str, attacker_name, actual_steal)

    msg = (
        f"🐾 <b>PET ATTACK</b>\n"
        f"─────────────────\n"
        f"<blockquote>"
        f"🐾 <i><b>{tg_escape(attacker_name)}'s</b> Snatcher Dog sneaked up on <b>{tg_escape(target_name)}</b>...</i>\n\n"
        f"💸 <b><i>Stolen:</i></b> <code>{actual_steal:,} pts</code>!\n"
        f"📈 <b><i>Your New Balance:</i></b> <code>{scores[chat_id_str][user_id_str]['score']:,} pts</code>"
        f"</blockquote>\n"
        f"─────────────────"
    )
    await safe_reply(update, context, msg, parse_mode='HTML')

async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await safe_reply(update, context, "<blockquote>🔍 <i>Retrieving Telegram user details...</i></blockquote>", parse_mode='HTML')
    if not status_msg: return

    target_id = None
    target_user = None
    is_numeric_query = False
    query_arg = None

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_id = target_user.id
    elif context.args:
        query_arg = context.args[0].strip().replace("@", "")
        if query_arg.isdigit():
            is_numeric_query = True
            target_id = int(query_arg)
        else:
            tg_data = await fetch_mafia_tgid(query_arg)
            if not is_valid_tg_data(tg_data):
                tg_data = await fetch_tg_leak_info(query_arg)

            if is_valid_tg_data(tg_data):
                res_dict = tg_data.get("result", {}) if isinstance(tg_data, dict) and "result" in tg_data else tg_data
                if isinstance(res_dict, dict) and "data" in res_dict: res_dict = res_dict["data"]
                if isinstance(res_dict, list) and len(res_dict) > 0: res_dict = res_dict[0]
                target_id = res_dict.get("telegram_id") or res_dict.get("id") or res_dict.get("tg_id")
    else:
        target_user = update.message.from_user
        target_id = target_user.id

    if not target_id and not target_user and not query_arg:
        await status_msg.edit_text("<blockquote><i>Could not resolve user details. Please provide a valid numeric ID, handle, or reply to a message.</i></blockquote>", parse_mode='HTML')
        return

    try:
        if is_numeric_query:
            tg_data = await fetch_mafia_tgid(target_id)
            if not is_valid_tg_data(tg_data):
                tg_data = await fetch_tg_leak_info(target_id)

            res_dict = {}
            records = []
            if tg_data:
                def parse_rec(p):
                    if not p: return []
                    if isinstance(p, dict):
                        for k in ['data', 'result', 'records']:
                            if k in p and isinstance(p[k], (list, dict)):
                                sub = p[k]
                                return sub if isinstance(sub, list) else [sub]
                        return [p]
                    elif isinstance(p, list):
                        return p
                    return []
                records = parse_rec(tg_data)
                if records and isinstance(records[0], dict):
                    res_dict = records[0]

            username = f"@{res_dict.get('username')}" if res_dict.get('username') else "@N/A"

            info_text = (
                f"🔍 <b>TELEGRAM DATABASE LOOKUP</b> 🔍\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<blockquote>"
                f"👤 <b>Target Username:</b> <i>{tg_escape(username)}</i>\n"
                f"🆔 <b>Target ID:</b> <code>{target_id}</code>"
                f"</blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            )

            if records:
                for i, rec in enumerate(records, 1):
                    if not isinstance(rec, dict): continue
                    rec_country = rec.get("country") or rec.get("Country") or "N/A"
                    rec_cc = rec.get("country_code") or rec.get("CountryCode") or "N/A"
                    if isinstance(rec_country, list): rec_country = ", ".join(map(str, rec_country))
                    if isinstance(rec_cc, list): rec_cc = ", ".join(map(str, rec_cc))
                    if not str(rec_cc).startswith("+") and rec_cc != "N/A": rec_cc = f"+{rec_cc}"
                    rec_phone = rec.get("mobile") or rec.get("phone") or rec.get("number") or rec.get("Phone") or rec.get("Mobile") or "N/A"
                    if isinstance(rec_phone, list): rec_phone = ", ".join(map(str, rec_phone))

                    info_text += (
                        f"📁 <b><i>Linked Record {i}</i></b>\n"
                        f"<blockquote>"
                        f"🔸 <b>Country:</b> <code>{tg_escape(str(rec_country))}</code>\n"
                        f"🔸 <b>Prefix:</b> <code>{tg_escape(str(rec_cc))}</code>\n"
                        f"🔸 <b>Mobile:</b> <code>{tg_escape(str(rec_phone))}</code>"
                        f"</blockquote>\n"
                    )
            else:
                info_text += "<blockquote><i>No linked mobile records found!</i></blockquote>\n"

            info_text += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Lookup complete!</i>"
            await status_msg.edit_text(info_text, parse_mode='HTML')

        else:
            if not target_user and target_id:
                try:
                    chat_obj = await context.bot.get_chat(target_id)
                    first_name = chat_obj.first_name or "N/A"
                    last_name = chat_obj.last_name or ""
                    full_name = f"{first_name} {last_name}".strip()
                    username = f"@{chat_obj.username}" if chat_obj.username else "No Username"
                    bio = chat_obj.bio or "N/A"
                except Exception:
                    tg_data = await fetch_mafia_tgid(query_arg if query_arg else target_id)
                    if not is_valid_tg_data(tg_data):
                        tg_data = await fetch_tg_leak_info(query_arg if query_arg else target_id)

                    if is_valid_tg_data(tg_data):
                        res_dict = tg_data.get("result", {}) if isinstance(tg_data, dict) and "result" in tg_data else tg_data
                        if isinstance(res_dict, dict) and "data" in res_dict: res_dict = res_dict["data"]
                        if isinstance(res_dict, list) and len(res_dict) > 0: res_dict = res_dict[0]

                        full_name = res_dict.get("name") or res_dict.get("first_name") or "Unknown"
                        username = f"@{res_dict.get('username')}" if res_dict.get('username') else "No Username"
                        bio = "N/A"
                    else:
                        await status_msg.edit_text(f"<blockquote><i>Could not fetch details for <code>{query_arg or target_id}</code>. User may not have interacted with the bot.</i></blockquote>", parse_mode='HTML')
                        return
            else:
                full_name = target_user.full_name
                username = f"@{target_user.username}" if target_user.username else "No Username"
                try:
                    chat_obj = await context.bot.get_chat(target_id)
                    bio = chat_obj.bio or "N/A"
                except:
                    bio = "N/A"

            info_text = (
                f"👤 <b>TELEGRAM PROFILE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<blockquote>"
                f"👤 <b>Name:</b> <i>{tg_escape(full_name)}</i>\n"
                f"🏷️ <b>Handle:</b> <code>{tg_escape(username)}</code>\n"
                f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
                f"📝 <b>Bio:</b> <i>{tg_escape(bio)}</i>"
                f"</blockquote>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Profile data successfully retrieved!</i>"
            )
            await status_msg.edit_text(info_text, parse_mode='HTML')

    except Exception as e:
        logging.error(f"Userinfo command error: {e}")
        await status_msg.edit_text("<blockquote><i>Failed to retrieve user information!</i></blockquote>", parse_mode='HTML')

async def mine_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    user = update.message.from_user
    chat_id_str = str(chat_id)
    user_id_str = str(user.id)

    if not context.args or not context.args[0].isdigit():
        msg = "<blockquote>💎 <i>Please specify your bet amount! Example: <code>/mine 50</code></i></blockquote>"
        await safe_reply(update, context, msg, parse_mode='HTML')
        return

    bet = int(context.args[0])
    if bet < 10:
        await safe_reply(update, context, "<blockquote><i>Minimum bet is <b>10 pts</b>!</i></blockquote>", parse_mode='HTML')
        return

    if chat_id_str not in scores or user_id_str not in scores[chat_id_str] or scores[chat_id_str][user_id_str]["score"] < bet:
        balance = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)
        await safe_reply(update, context, f"<blockquote><i>You don't have enough points! Your balance: <b>{balance:,} pts</b></i></blockquote>", parse_mode='HTML')
        return

    game_id = str(random.randint(100000, 999999))

    mine_games[game_id] = {
        "user_id": user.id,
        "status": "setup"
    }

    kb = [
        [InlineKeyboardButton("🟢 Easy (3x3) [min bet 10]", callback_data=f"mine_diff_{game_id}_easy_{bet}")],
        [InlineKeyboardButton("🟡 Medium (4x4) [min bet 50]", callback_data=f"mine_diff_{game_id}_medium_{bet}")],
        [InlineKeyboardButton("🔴 Hard (5x5) [min bet 100]", callback_data=f"mine_diff_{game_id}_hard_{bet}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"mine_cancel_{game_id}")]
    ]

    msg = (
        f"💎 <b>MINESWEEPER</b>\n"
        f"─────────────────\n"
        f"<blockquote>"
        f"👤 <b><i>Player:</i></b> <b>{tg_escape(user.first_name)}</b>\n"
        f"💰 <b><i>Wager:</i></b> <code>{bet:,} pts</code>\n\n"
        f"👇 <i>Select your difficulty level:</i>"
        f"</blockquote>\n"
        f"─────────────────"
    )
    await safe_reply(update, context, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def mine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if not data.startswith("mine_"): return
    if data == "mine_ignore":
        await query.answer()
        return

    await query.answer()

    if data.startswith("mine_cancel_"):
        parts = data.split("_")
        game_id = parts[2]
        game = mine_games.get(game_id)
        if not game or game["user_id"] != user.id or game["status"] != "setup":
            await query.answer("Invalid session!", show_alert=True)
            return

        game["status"] = "cancelled"
        await query.edit_message_text("<blockquote><i>Game cancelled! No points deducted.</i></blockquote>", parse_mode='HTML')
        return

    if data.startswith("mine_diff_"):
        parts = data.split("_")
        game_id = parts[2]
        diff = parts[3]
        bet = int(parts[4])

        game = mine_games.get(game_id)
        if not game or game["user_id"] != user.id or game["status"] != "setup":
            await query.answer("Invalid or expired session!", show_alert=True)
            return

        if diff == "medium" and bet < 50:
            await query.answer("Medium mode requires a minimum bet of 50 pts!", show_alert=True)
            return
        if diff == "hard" and bet < 100:
            await query.answer("Hard mode requires a minimum bet of 100 pts!", show_alert=True)
            return

        chat_id_str = str(query.message.chat_id)
        user_id_str = str(user.id)

        if scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0) < bet:
            await query.answer("Not enough points!", show_alert=True)
            return

        await update_score(chat_id_str, user_id_str, user.first_name, -bet)

        if diff == "easy": size, num_mines, diff_name = 3, 2, "Easy (3x3)"
        elif diff == "medium": size, num_mines, diff_name = 4, 4, "Medium (4x4)"
        else: size, num_mines, diff_name = 5, 7, "Hard (5x5)"

        first_gem_val = calculate_mine_payout(bet, size, num_mines, 1)
        first_mult = round(first_gem_val / bet, 2)

        mine_games[game_id] = {
            "user_id": user.id,
            "user_name": user.first_name,
            "bet": bet,
            "size": size,
            "total_mines": num_mines,
            "mines": random.sample(range(size*size), num_mines),
            "revealed": [False] * (size*size),
            "gems_found": 0,
            "points_earned": 0,
            "diff_name": diff_name,
            "status": "playing"
        }

        game = mine_games[game_id]
        safe_tiles = (size * size) - num_mines

        msg = (
            f"💎 <b>MINESWEEPER</b>\n"
            f"─────────────────\n"
            f"<blockquote>"
            f"👤 <b><i>Player:</i></b> <b>{tg_escape(user.first_name)}</b>\n"
            f"🎚️ <b><i>Mode:</i></b> <code>{diff_name}</code>\n"
            f"💰 <b><i>Wager:</i></b> <code>{bet:,} pts</code>\n\n"
            f"💎 <b><i>Gems Found:</i></b> <code>0/{safe_tiles}</code>\n"
            f"📈 <b><i>Next Gem Multiplier:</i></b> <code>{first_mult}x</code> (+{first_gem_val - bet:,} pts)\n\n"
            f"👇 <i>Tap a tile to reveal Gems! Avoid mines!</i>"
            f"</blockquote>\n"
            f"─────────────────"
        )
        await query.edit_message_text(msg, reply_markup=get_mine_kb(game_id, game), parse_mode='HTML')
        return

    if data.startswith("mine_reveal_"):
        parts = data.split("_")
        game_id = parts[2]
        idx = int(parts[3])

        game = mine_games.get(game_id)
        if not game or game["status"] != "playing":
            await query.answer("Game is over or invalid!", show_alert=True)
            return

        if user.id != game["user_id"]:
            await query.answer("This is not your game! Start your own with /mine", show_alert=True)
            return

        if game["revealed"][idx]:
            await query.answer("Tile already revealed!", show_alert=False)
            return

        game["revealed"][idx] = True

        if idx in game["mines"]:
            game["status"] = "lost"
            chat_id_str = str(query.message.chat_id)
            user_id_str = str(user.id)
            new_total = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)

            msg = (
                f"💥 <b>MINE EXPLODED</b>\n"
                f"─────────────────\n"
                f"<blockquote>"
                f"🥀 <i>Oh no, <b>{tg_escape(user.first_name)}</b> hit a mine!</i>\n"
                f"💸 <b><i>Lost Wager:</i></b> <code>{game['bet']:,} pts</code>\n"
                f"📊 <b><i>Total Balance:</i></b> <code>{new_total:,} pts</code>"
                f"</blockquote>\n"
                f"─────────────────"
            )
            await query.edit_message_text(msg, reply_markup=get_mine_kb(game_id, game, done=True), parse_mode='HTML')
            return

        game["gems_found"] += 1
        safe_tiles = (game["size"] * game["size"]) - game["total_mines"]

        current_payout = calculate_mine_payout(game["bet"], game["size"], game["total_mines"], game["gems_found"])
        game["points_earned"] = current_payout
        current_mult = round(current_payout / game["bet"], 2)
        current_profit = current_payout - game["bet"]

        if game["gems_found"] == safe_tiles:
            game["status"] = "won"
            chat_id_str, user_id_str = str(query.message.chat_id), str(user.id)

            await update_score(chat_id_str, user_id_str, user.first_name, current_payout)
            new_total = scores[chat_id_str][user_id_str]['score']

            msg = (
                f"💎 <b>PERFECT BOARD CLEAR</b>\n"
                f"─────────────────\n"
                f"<blockquote>"
                f"👑 <i>AMAZING! <b>{tg_escape(user.first_name)}</b> cleared all {safe_tiles} gems!</i>\n"
                f"🔥 <b><i>Max Multiplier:</i></b> <code>{current_mult}x</code>\n"
                f"💰 <b><i>Total Profit:</i></b> <code>+{current_profit:,} pts</code>\n"
                f"📊 <b><i>New Balance:</i></b> <code>{new_total:,} pts</code>"
                f"</blockquote>\n"
                f"─────────────────"
            )
            await query.edit_message_text(msg, reply_markup=get_mine_kb(game_id, game, done=True), parse_mode='HTML')
            return

        next_payout = calculate_mine_payout(game["bet"], game["size"], game["total_mines"], game["gems_found"] + 1)
        next_mult = round(next_payout / game["bet"], 2)

        msg = (
            f"💎 <b>MINESWEEPER</b>\n"
            f"─────────────────\n"
            f"<blockquote>"
            f"👤 <b><i>Player:</i></b> <b>{tg_escape(user.first_name)}</b>\n"
            f"🎚️ <b><i>Mode:</i></b> <code>{game['diff_name']}</code>\n"
            f"💎 <b><i>Gems Found:</i></b> <code>{game['gems_found']}/{safe_tiles}</code>\n"
            f"📈 <b><i>Current Multiplier:</i></b> <code>{current_mult}x</code> (+{current_profit:,} pts)\n"
            f"🎯 <b><i>Next Gem Multiplier:</i></b> <code>{next_mult}x</code> (+{next_payout - game['bet']:,} pts)\n\n"
            f"👇 <i>Keep revealing or Cash Out to lock in your profit!</i>"
            f"</blockquote>\n"
            f"─────────────────"
        )
        await query.edit_message_text(msg, reply_markup=get_mine_kb(game_id, game), parse_mode='HTML')
        return

    if data.startswith("mine_cashout_"):
        parts = data.split("_")
        game_id = parts[2]

        game = mine_games.get(game_id)
        if not game or game["status"] != "playing":
            await query.answer("Game is over or invalid!", show_alert=True)
            return

        if user.id != game["user_id"]:
            await query.answer("This is not your game!", show_alert=True)
            return

        if game["gems_found"] == 0:
            await query.answer("Find at least 1 gem before cashing out!", show_alert=True)
            return

        game["status"] = "cashed_out"
        pts = game["points_earned"]
        chat_id_str, user_id_str = str(query.message.chat_id), str(user.id)

        await update_score(chat_id_str, user_id_str, user.first_name, pts)
        new_total = scores[chat_id_str][user_id_str]['score']

        profit = pts - game["bet"]
        mult = round(pts / game["bet"], 2)
        profit_str = f"+{profit:,}" if profit >= 0 else f"{profit:,}"

        msg = (
            f"💸 <b>CASHED OUT!</b> 💸\n"
            f"─────────────────\n"
            f"<blockquote>"
            f"💖 <i>Smart choice, <b>{tg_escape(user.first_name)}</b>!</i>\n"
            f"💎 <b><i>Gems Unlocked:</i></b> <code>{game['gems_found']}</code>\n"
            f"📊 <b><i>Multiplier Achieved:</i></b> <code>{mult}x</code>\n"
            f"📈 <b><i>Net Profit:</i></b> <code>{profit_str} pts</code>\n"
            f"🏆 <b><i>Total Balance:</i></b> <code>{new_total:,} pts</code>"
            f"</blockquote>\n"
            f"─────────────────"
        )
        await query.edit_message_text(msg, reply_markup=get_mine_kb(game_id, game, done=True), parse_mode='HTML')
        return

async def ttt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)

    kb = [
        [InlineKeyboardButton("🤖 Play vs Myra (Bot)", callback_data="ttt_start_bot")],
        [InlineKeyboardButton("👩‍❤️‍👨 Play vs Friend", callback_data="ttt_start_friend")]
    ]
    msg = "🎮 <b>TIC TAC TOE</b>\n─────────────────\n<blockquote><i>Select your game mode!</i></blockquote>\n─────────────────"
    await safe_reply(update, context, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def ttt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if not data.startswith("ttt_"): return
    if data == "ttt_ignore":
        await query.answer("Invalid move!", show_alert=False)
        return

    await query.answer()

    if data == "ttt_start_bot" or data == "ttt_start_friend":
        game_id = str(random.randint(100000, 999999))
        mode = "bot" if "bot" in data else "friend"

        ttt_games[game_id] = {
            "board": [" "]*9,
            "turn": "X",
            "x_id": user.id,
            "x_name": user.first_name,
            "o_id": "bot" if mode == "bot" else None,
            "o_name": "Myra 🤖" if mode == "bot" else None,
            "mode": mode,
            "status": "waiting" if mode == "friend" else "playing"
        }

        if mode == "bot":
            text = f"🎮 <b>TIC TAC TOE</b>\n─────────────────\n<blockquote>✖️ <code>{tg_escape(user.first_name)}</code> <b>VS</b> 🅾️ <code>Myra 🤖</code>\n\n▶️ <i>It's <b>{tg_escape(user.first_name)}'s</b> turn!</i></blockquote>"
            await query.edit_message_text(text, reply_markup=get_ttt_kb(game_id, ttt_games[game_id]["board"]), parse_mode="HTML")
        else:
            kb = [[InlineKeyboardButton("💖 Join Game", callback_data=f"ttt_join_{game_id}")]]
            text = f"🎮 <b>TIC TAC TOE</b>\n─────────────────\n<blockquote>▸ <code>{tg_escape(user.first_name)}</code> <i>is waiting for a challenger!</i>\n\n👇 <b>Click below to join!</b> 👇</blockquote>"
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return

    if data.startswith("ttt_join_"):
        game_id = data.split("_")[2]
        game = ttt_games.get(game_id)

        if not game or game["status"] != "waiting":
            await query.answer("Game not found or already started!", show_alert=True)
            return
        if user.id == game["x_id"]:
            await query.answer("You can't play against yourself!", show_alert=True)
            return

        game["o_id"] = user.id
        game["o_name"] = user.first_name
        game["status"] = "playing"

        text = f"🎮 <b>TIC TAC TOE</b>\n─────────────────\n<blockquote>✖️ <code>{tg_escape(game['x_name'])}</code> <b>VS</b> 🅾️ <code>{tg_escape(game['o_name'])}</code>\n\n▶️ ✖️ <i>It's <b>{tg_escape(game['x_name'])}'s</b> turn!</i></blockquote>"
        await query.edit_message_text(text, reply_markup=get_ttt_kb(game_id, game["board"]), parse_mode="HTML")
        return

    if data.startswith("ttt_move_"):
        parts = data.split("_")
        game_id = parts[2]
        move_idx = int(parts[3])

        game = ttt_games.get(game_id)
        if not game or game["status"] != "playing":
            await query.answer("Game is over or invalid!", show_alert=True)
            return

        current_id = game["x_id"] if game["turn"] == "X" else game["o_id"]
        if user.id != current_id:
            await query.answer("It's not your turn!", show_alert=True)
            return

        if game["board"][move_idx] != " ":
            await query.answer("That spot is taken!", show_alert=True)
            return

        game["board"][move_idx] = game["turn"]

        if check_ttt_win(game["board"], game["turn"]):
            winner_name = game["x_name"] if game["turn"] == "X" else game["o_name"]
            winner_id = game["x_id"] if game["turn"] == "X" else game["o_id"]

            score_text = ""
            if str(winner_id) != "bot":
                chat_id_str = str(query.message.chat_id)
                user_id_str = str(winner_id)
                await update_score(chat_id_str, user_id_str, winner_name, 1)
                new_total = scores[chat_id_str][user_id_str]['score']
                score_text = f"\n\n📊 <b><i>Total Score:</i></b> <b><code>{new_total:,} pts</code></b> (+1 💖)"

            text = f"🎉 <b>WE HAVE A WINNER!</b> 🎉\n─────────────────\n<blockquote>👑 <code>{tg_escape(winner_name)}</code> <i>won the game!</i> 🌸{score_text}</blockquote>\n─────────────────"
            game["status"] = "done"
            await query.edit_message_text(text, reply_markup=get_ttt_kb(game_id, game["board"], True), parse_mode="HTML")
            return

        if " " not in game["board"]:
            text = "⚖️ <b>IT'S A DRAW!</b> ⚖️\n─────────────────\n<blockquote>🍃 <i>A true battle of wits! No points awarded.</i></blockquote>\n─────────────────"
            game["status"] = "done"
            await query.edit_message_text(text, reply_markup=get_ttt_kb(game_id, game["board"], True), parse_mode="HTML")
            return

        game["turn"] = "O" if game["turn"] == "X" else "X"

        if game["mode"] == "bot" and game["turn"] == "O":
            bot_move = get_bot_move(game["board"])
            if bot_move is not None:
                game["board"][bot_move] = "O"

                if check_ttt_win(game["board"], "O"):
                    text = f"🤖 <b>GAME OVER</b>\n─────────────────\n<blockquote><code>Myra</code> won this match — <i>better luck next time!</i></blockquote>"
                    game["status"] = "done"
                    await query.edit_message_text(text, reply_markup=get_ttt_kb(game_id, game["board"], True), parse_mode="HTML")
                    return
                if " " not in game["board"]:
                    text = "⚖️ <b>IT'S A DRAW!</b> ⚖️\n─────────────────\n<blockquote>🍃 <i>A tie match! No points.</i></blockquote>\n─────────────────"
                    game["status"] = "done"
                    await query.edit_message_text(text, reply_markup=get_ttt_kb(game_id, game["board"], True), parse_mode="HTML")
                    return

                game["turn"] = "X"

        current_turn_name = game["x_name"] if game["turn"] == "X" else game["o_name"]
        current_emoji = "✖️" if game["turn"] == "X" else "🅾️"

        text = f"🎮 <b>TIC TAC TOE</b>\n─────────────────\n<blockquote>✖️ <code>{tg_escape(game['x_name'])}</code> <b>VS</b> 🅾️ <code>{tg_escape(game['o_name'])}</code>\n\n▶️ {current_emoji} <i>It's <b>{tg_escape(current_turn_name)}'s</b> turn!</i></blockquote>"
        await query.edit_message_text(text, reply_markup=get_ttt_kb(game_id, game["board"]), parse_mode="HTML")

async def roast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.message.reply_to_message.from_user.first_name if update.message.reply_to_message else (" ".join(context.args) if context.args else update.message.from_user.first_name)
    target_clean = tg_escape(target)
    status_msg = await safe_reply(update, context, f"<blockquote>🔥 <i>lemme cook up a roast for <b>{target_clean}</b>...</i></blockquote>", parse_mode='HTML')
    if not status_msg: return

    system_base = get_user_history(update.message.from_user.id)[0]["content"]
    prompt = [
        {"role": "system", "content": system_base + f"\n\nTASK: Write a hilarious, witty, lighthearted roast targeting '{target}'. Keep it clever, polite, and funny. Use <blockquote>, <b>, and <i> formatting."},
        {"role": "user", "content": f"Roast {target}"}
    ]

    try:
        roast_text = await generate_response_with_failover(prompt)
        res_msg = f"🔥 <b>ROAST</b>\n─────────────────\n<b>Target:</b> {target_clean}\n\n<blockquote>{roast_text}</blockquote>"
        await status_msg.edit_text(res_msg, parse_mode='HTML')
    except Exception:
        await status_msg.edit_text(f"<blockquote>🔥 <i><b>{target_clean}</b> is so polite that even my roast engine could not find anything to say!</i></blockquote>", parse_mode='HTML')

async def ship_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user1, user2 = None, None
    if update.message.reply_to_message:
        user1 = update.message.from_user.first_name
        user2 = update.message.reply_to_message.from_user.first_name
    elif len(context.args) >= 2:
        user1 = context.args[0]
        user2 = " ".join(context.args[1:])
    elif len(context.args) == 1:
        user1 = update.message.from_user.first_name
        user2 = context.args[0]
    else:
        await safe_reply(update, context, "<blockquote><i>tag someone, reply to them, or type two names! Example: <code>/ship @user1 @user2</code></i></blockquote>", parse_mode='HTML')
        return

    u1_clean, u2_clean = tg_escape(user1.replace("@", "")), tg_escape(user2.replace("@", ""))
    ship_name = (u1_clean[:max(2, len(u1_clean)//2)] + u2_clean[len(u2_clean)//2:]).title()
    compat_score = random.randint(15, 100)

    status_msg = await safe_reply(update, context, f"<blockquote>💘 <i>checking the vibe between <b>{u1_clean}</b> & <b>{u2_clean}</b>...</i></blockquote>", parse_mode='HTML')
    if not status_msg: return

    bars = int(compat_score / 10)
    progress_bar = "💖" * bars + "🤍" * (10 - bars)

    system_base = get_user_history(update.message.from_user.id)[0]["content"]
    prompt = [
        {"role": "system", "content": system_base + f"\n\nTASK: Write a short, pleasant 2-sentence romantic analysis for '{u1_clean}' and '{u2_clean}' who scored {compat_score}% compatibility. Use <blockquote>, <b>, and <i> tags."},
        {"role": "user", "content": f"Analyze couple {u1_clean} and {u2_clean}"}
    ]

    try:
        analysis = await generate_response_with_failover(prompt)
        res_msg = (
            f"💘 <b>SHIP</b>\n─────────────────\n"
            f"<blockquote>\n"
            f"<b>Couple:</b> {u1_clean} + {u2_clean}\n"
            f"<b>Ship Name:</b> <code>{ship_name}</code>\n"
            f"<b>Score:</b> <code>{compat_score}%</code>\n"
            f"{progress_bar}\n"
            f"</blockquote>\n"
            f"<blockquote><i>{analysis}</i></blockquote>"
        )
        await status_msg.edit_text(res_msg, parse_mode='HTML')
    except Exception:
        fallback_msg = (
            f"💘 <b>SHIP</b>\n─────────────────\n"
            f"<blockquote>\n"
            f"<b>Couple:</b> {u1_clean} + {u2_clean}\n"
            f"<b>Ship Name:</b> <code>{ship_name}</code>\n"
            f"<b>Score:</b> <code>{compat_score}%</code>\n"
            f"{progress_bar}\n"
            f"</blockquote>"
        )
        await status_msg.edit_text(fallback_msg, parse_mode='HTML')

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args[:-1]) if context.args and context.args[-1].isdigit() else " ".join(context.args)
    page = max(1, int(context.args[-1])) if context.args and context.args[-1].isdigit() else 1
    query = query.strip() if query else None

    status_msg = await safe_reply(update, context, "<blockquote>📰 <i>fetching the latest tea...</i></blockquote>", parse_mode='HTML')
    if not status_msg: return

    articles = await fetch_news(query, page)
    if not articles:
        await status_msg.edit_text("<blockquote><i>i couldn't find any news articles for that rn!</i></blockquote>", parse_mode='HTML')
        return

    topic = tg_escape(f"{query.upper()}") if query else "TOP HEADLINES"
    news_data_for_prompt = "".join([f"Article {i}:\nTitle: {art.get('title')}\nSummary: {art.get('description')}\nURL: {art.get('url')}\n\n" for i, art in enumerate(articles, 1)])

    system_base = get_user_history(update.message.from_user.id)[0]["content"]
    ai_prompt = [
        {"role": "system", "content": system_base + f"\n\nTASK: Read these news articles and summarize. Format with Telegram HTML tags (<b>, <i>, <blockquote>, <a href='URL'>Read More</a>). Group under headline: '{topic}' (Page {page})."},
        {"role": "user", "content": f"Raw news data:\n\n{news_data_for_prompt}"}
    ]

    next_page_cmd = f"/news {query + ' ' if query else ''}{page + 1}"
    footer = f"\n─────────────────\n<i>For more, type <b><code>{next_page_cmd}</code></b></i>"

    await status_msg.edit_text("<blockquote>🧠 <i>summarizing the headlines for u...</i></blockquote>", parse_mode='HTML')
    try:
        formatted_news = await generate_response_with_failover(ai_prompt)
        await status_msg.edit_text((formatted_news + footer)[:4000], parse_mode='HTML', disable_web_page_preview=True)
    except Exception:
        result_text = f"📰 <b>LATEST NEWS | {topic} (Page {page})</b> 📰\n─────────────────\n"
        for i, art in enumerate(articles, 1):
            title = tg_escape(art.get("title", "No Title"))
            desc = tg_escape(art.get("description", ""))[:137] + "..." if len(art.get("description", "")) > 140 else tg_escape(art.get("description", ""))
            url = art.get("url", "")
            result_text += f"🗞️ <b>{i}. {title}</b>\n<blockquote>📝 <i>{desc}</i></blockquote>\n"
            if url and url != "https://removed.com": result_text += f"🔗 <b><a href='{url}'>Read Full Article</a></b>\n\n"
        await status_msg.edit_text((result_text + footer)[:4000], parse_mode='HTML', disable_web_page_preview=True)

async def search_anilist_media(search_term):
    url = 'https://graphql.anilist.co'
    graphql_query = '''query ($search: String) {
      Page (page: 1, perPage: 6) {
        media (search: $search, type: ANIME, sort: SEARCH_MATCH) {
          id
          title { romaji english native }
          format
          seasonYear
          episodes
        }
      }
    }'''
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': random.choice(USER_AGENTS)}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={'query': graphql_query, 'variables': {'search': search_term}}, timeout=8.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', {}).get('Page', {}).get('media', [])
    except Exception as e:
        logging.error(f"AniList query error: {e}")
    return []

async def anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context, "<blockquote><i>please specify an anime, technique, or character! Example: <code>/anime Rasengan</code> or <code>/anime JJK</code></i> 🍡</blockquote>", parse_mode='HTML')
        return

    query = " ".join(context.args)
    status_msg = await safe_reply(update, context, f"<blockquote>⛩️ <i>checking anime database for <b>{tg_escape(query)}</b>...</i></blockquote>", parse_mode='HTML')
    if not status_msg: return

    results = await search_anilist_media(query)

    if not results:
        await status_msg.edit_text(f"<blockquote>🌐 <i>no direct match, web searching official anime title for: <b>{tg_escape(query)}</b>...</i></blockquote>", parse_mode='HTML')

        web_res, _ = await fetch_multi_source_web_search(f"{query} anime name official title")

        extracted_title = None
        if web_res:
            snippet_text = "\n".join([f"- {r.get('title')}: {r.get('body')}" for r in web_res[:4]])
            extract_prompt = [
                {"role": "system", "content": "You extract ONLY the exact official anime title name associated with the user query from search results. Output ONLY the official anime title name and absolutely nothing else."},
                {"role": "user", "content": f"Query: '{query}'. Search Snippets:\n{snippet_text}"}
            ]
            try:
                target_model = "llama-3.1-8b-instant"
                if target_model not in MODELS_CASCADE:
                    target_model = MODELS_CASCADE[0]

                response = await clients[0].chat.completions.create(
                    model=target_model,
                    messages=extract_prompt,
                    max_tokens=60,
                    temperature=0.1,
                    timeout=30.0
                )
                extracted_title = response.choices[0].message.content.strip().strip('"\'')
            except Exception:
                if web_res:
                    extracted_title = web_res[0].get("title", "").split("-")[0].split("|")[0].strip()

        if extracted_title:
            await status_msg.edit_text(f"<blockquote>⛩️ <i>found official title <b>{tg_escape(extracted_title)}</b>! Loading seasons...</i></blockquote>", parse_mode='HTML')
            results = await search_anilist_media(extracted_title)

    if not results:
        await status_msg.edit_text("<blockquote><i>i couldn't find any anime matching that query even after web search!</i></blockquote>", parse_mode='HTML')
        return

    kb = []
    for res in results:
        title = res.get('title', {}).get('english') or res.get('title', {}).get('romaji') or "Unknown"
        fmt = res.get('format', 'TV')
        year = res.get('seasonYear') or 'N/A'
        btn_text = f"🎬 {title} ({fmt} - {year})"
        kb.append([InlineKeyboardButton(btn_text, callback_data=f"ani_{res['id']}")])

    msg = f"⛩️ <b>ANIME SEASONS & MOVIES</b> ⛩️\n─────────────────\n<blockquote><i>Select the exact season, movie, or series for <b>{tg_escape(query)}</b>:</i></blockquote>\n─────────────────"
    await status_msg.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def anime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if not data.startswith("ani_"): return
    ani_id = data.split("_")[1]
    await query.answer()

    url = 'https://graphql.anilist.co'
    graphql_query = '''query ($id: Int) {
      Media (id: $id, type: ANIME) {
        title { romaji english }
        averageScore
        episodes
        status
        description
        siteUrl
        coverImage { large }
      }
    }'''

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={'query': graphql_query, 'variables': {'id': int(ani_id)}}, timeout=6.0) as resp:
                data = await resp.json()
                anime = data.get('data', {}).get('Media')
    except Exception as e:
        logging.error(f"Anilist details error: {e}")
        anime = None

    if not anime:
        await query.edit_message_text("<blockquote><i>failed to fetch details for this season!</i></blockquote>", parse_mode='HTML')
        return

    t = anime.get("title", {})
    title = tg_escape(t.get("english") or t.get("romaji") or "Unknown")
    score = anime.get('averageScore')
    score_str = f"{score / 10:.1f}" if score else "N/A"
    eps = anime.get("episodes") or "N/A"
    status = str(anime.get("status", "Unknown")).replace("_", " ").title()

    synopsis = tg_escape(html.unescape(re.sub(r'<[^>]+>', '', anime.get("description") or "")))
    synopsis = synopsis[:300] + "..." if len(synopsis) > 300 else synopsis
    img_url = anime.get("coverImage", {}).get("large", "")

    msg = (f"⛩️ <b>ANILIST: {title}</b> ⛩️\n─────────────────\n"
           f"<blockquote>\n"
           f"⭐ <b><i>Score:</i></b> <b><code>{score_str}/10</code></b>\n"
           f"🎬 <b><i>Episodes:</i></b> <b><code>{eps}</code></b>\n"
           f"📌 <b><i>Status:</i></b> <b><code>{status}</code></b>\n"
           f"</blockquote>\n"
           f"📖 <b><i>Synopsis:</i></b>\n<blockquote><i>{synopsis}</i></blockquote>\n─────────────────\n")

    if img_url: msg += f"🖼️ <b><a href='{img_url}'>Cover Image</a></b> | "
    msg += f"🔗 <b><a href='{anime.get('siteUrl', '')}'>AniList Link</a></b>"

    await query.edit_message_text(msg, parse_mode='HTML', disable_web_page_preview=False)

async def rizz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args and not update.message.reply_to_message:
        await safe_reply(update, context, "<blockquote><i>tag someone or reply to their text to evaluate their rizz! Example: <code>/rizz @username</code></i></blockquote>", parse_mode='HTML')
        return
    target = tg_escape(" ".join(context.args)) if context.args else tg_escape(update.message.reply_to_message.from_user.first_name)
    msg = (f"📊 <b>RIZZ</b> 📊\n─────────────────\n"
           f"<blockquote>\n"
           f"👤 <b><i>Target:</i></b> <b>{target}</b>\n"
           f"📈 <b><i>Rizz Score:</i></b> <b><code>{random.randint(1, 100)}%</code></b>\n"
           f"</blockquote>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

def _ig_fmt_num(n) -> str:
    """Format a count like 4 -> '4', 1234 -> '1.2K', 1234567 -> '1.2M'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 1_000_000:
        s = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if n >= 1_000:
        s = f"{n / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}K"
    return str(n)

def _render_ig_profile_card(username: str, data: dict, pic_bytes: bytes | None = None) -> bytes:
    """Render a single Instagram-profile-style card (pfp embedded, stats, bio).
    The profile picture is drawn INTO this image so it need not be sent separately."""
    from PIL import Image, ImageDraw
    import io as _io

    W, H = 900, 400
    c1 = (88, 40, 180)
    c2 = (220, 50, 120)
    grad = Image.new("RGB", (2, 256))
    for i in range(256):
        t = i / 255
        col = (int(c1[0] + (c2[0] - c1[0]) * t),
               int(c1[1] + (c2[1] - c1[1]) * t),
               int(c1[2] + (c2[2] - c1[2]) * t))
        grad.putpixel((0, i), col)
        grad.putpixel((1, i), col)
    grad = grad.resize((W, H))
    img = grad.convert("RGBA")

    rmask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(rmask).rounded_rectangle([0, 0, W, H], radius=36, fill=255)
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    card.paste(img, (0, 0), rmask)
    img = card
    draw = ImageDraw.Draw(img)

    gx0, gy0 = W - 92, 28
    draw.rounded_rectangle([gx0, gy0, gx0 + 60, gy0 + 60], radius=18, outline=(255, 255, 255, 235), width=5)
    draw.ellipse([gx0 + 16, gy0 + 16, gx0 + 44, gy0 + 44], outline=(255, 255, 255, 235), width=5)
    draw.ellipse([gx0 + 44, gy0 + 12, gx0 + 52, gy0 + 20], fill=(255, 255, 255, 235))

    ar = 82
    ax, ay = 44 + ar, 128
    drew_avatar = False
    if pic_bytes:
        try:
            av = Image.open(_io.BytesIO(pic_bytes)).convert("RGBA").resize((ar * 2, ar * 2))
            avm = Image.new("L", (ar * 2, ar * 2), 0)
            ImageDraw.Draw(avm).ellipse([0, 0, ar * 2, ar * 2], fill=255)
            img.paste(av, (ax - ar, ay - ar), avm)
            drew_avatar = True
        except Exception:
            pass
    if not drew_avatar:
        initials = "".join(w[0] for w in (username or "?")[:2]).upper() or "?"
        draw.ellipse([ax - ar, ay - ar, ax + ar, ay + ar], fill=(255, 255, 255, 235))
        f_init = _get_font(52, bold=True)
        tw = draw.textlength(initials, font=f_init)
        draw.text((ax - tw / 2, ay - 34), initials, font=f_init, fill=(170, 45, 110, 255))
    draw.ellipse([ax - ar - 4, ay - ar - 4, ax + ar + 4, ay + ar + 4],
                 outline=(255, 255, 255, 245), width=4)

    tx = ax + ar + 40
    full_name = str(data.get('full_name') or '').strip()
    f_name = _get_font(38, bold=True)
    draw.text((tx, 58), (full_name or username)[:30], font=f_name, fill=(255, 255, 255, 255))
    f_handle = _get_font(24)
    draw.text((tx, 108), f"@{username}"[:34], font=f_handle, fill=(235, 235, 245, 210))

    bx = tx + draw.textlength((full_name or username)[:30], font=f_name) + 12
    if data.get('is_verified'):
        draw.ellipse([bx, 62, bx + 30, 92], fill=(56, 176, 255, 255))
        draw.line([(bx + 8, 77), (bx + 13, 83), (bx + 23, 70)], fill=(255, 255, 255, 255), width=3, joint="curve")
        bx += 38
    if data.get('is_private'):
        draw.rounded_rectangle([bx, 62, bx + 78, 92], radius=15, fill=(255, 255, 255, 45))
        f_pv = _get_font(17, bold=True)
        draw.text((bx + 14, 66), "Private", font=f_pv, fill=(255, 255, 255, 235))

    f_lbl = _get_font(20)
    stats = [
        f"{_ig_fmt_num(data.get('follower_count'))} Followers",
        f"{_ig_fmt_num(data.get('following_count'))} Following",
        f"{_ig_fmt_num(data.get('media_count'))} Posts",
    ]
    px, py = tx, 158
    for s in stats:
        tw = draw.textlength(s, font=f_lbl)
        draw.rounded_rectangle([px, py, px + tw + 34, py + 44], radius=22, fill=(18, 8, 30, 75))
        draw.text((px + 17, py + 10), s, font=f_lbl, fill=(255, 255, 255, 255))
        px += tw + 34 + 16

    f_bio = _get_font(21)
    bio = str(data.get('biography') or '').strip()
    by = 226
    if bio:
        for ln in _wrap_text_px(draw, bio, f_bio, W - tx - 40)[:3]:
            draw.text((tx, by), ln, font=f_bio, fill=(245, 245, 250, 240))
            by += 30
    else:
        draw.text((tx, by), "No bio yet.", font=f_bio, fill=(235, 235, 245, 170))

    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

async def ig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context,
            "<blockquote><i>Send me an Insta handle, e.g.</i> <code>/ig @username</code></blockquote>",
            parse_mode='HTML')
        return
    username = context.args[0].replace("@", "")
    status_msg = await safe_reply(update, context,
        f"<blockquote><i>Fetching Instagram details for</i> <b>@{tg_escape(username)}</b>...</blockquote>",
        parse_mode='HTML')

    data = await fetch_ig_info(username)
    if not data:
        if status_msg:
            try:
                await status_msg.edit_text(
                    "<blockquote><i>Couldn't connect, or that account doesn't exist!</i></blockquote>",
                    parse_mode='HTML')
            except Exception:
                pass
        return

    pic_url = data.get('profile_pic_url_hd') or data.get('profile_pic_url')
    pic_bytes = None
    if pic_url:
        def _dl():
            req = urllib.request.Request(pic_url, headers={'User-Agent': random.choice(USER_AGENTS)})
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read()
        try:
            pic_bytes = await asyncio.to_thread(_dl)
        except Exception as e:
            logging.warning(f"/ig pic download failed (non-fatal): {e}")

    try:
        card = await asyncio.to_thread(_render_ig_profile_card, username, data, pic_bytes)
        name = str(data.get('full_name') or '').strip()
        caption = (f"<b>INSTAGRAM</b>  <i>@{tg_escape(username)}</i>\n"
                   + (f"<blockquote><i>{tg_escape(name)}</i></blockquote>\n" if name else "")
                   + f"<i>{_ig_fmt_num(data.get('follower_count'))} followers · "
                     f"{_ig_fmt_num(data.get('media_count'))} posts</i>")
        await update.message.reply_photo(photo=_ioutil.BytesIO(card),
                                         caption=caption[:1024], parse_mode='HTML')
        if status_msg:
            try: await status_msg.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/ig render failed: {e}")
        txt = f"<b>INSTAGRAM · @{tg_escape(username)}</b>\n<blockquote>"
        for key, lab in [('full_name', 'Name'), ('follower_count', 'Followers'),
                         ('following_count', 'Following'), ('media_count', 'Posts'),
                         ('is_private', 'Private'), ('is_verified', 'Verified')]:
            val = data.get(key)
            if val is not None and val != "":
                if isinstance(val, bool): val = "Yes" if val else "No"
                elif isinstance(val, int): val = f"{val:,}"
                txt += f"<b>{lab}:</b> <code>{tg_escape(str(val))}</code>\n"
        if data.get('biography'):
            txt += f"<b>Bio:</b> <i>{tg_escape(data.get('biography'))}</i>\n"
        txt += "</blockquote>"
        if status_msg:
            try:
                await status_msg.edit_text(txt[:4000], parse_mode='HTML', disable_web_page_preview=True)
            except Exception:
                pass
        else:
            await safe_reply(update, context, txt[:4000], parse_mode='HTML')

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)

    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it — or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return

    trivia = await fetch_live_trivia()

    if not trivia:
        await safe_reply(update, context, "<blockquote>🧠 <i>You have successfully answered every single trivia question in my database! Wait for an update!</i></blockquote>", parse_mode='HTML')
        return

    active_games[chat_id] = {"type": "trivia", "answer": trivia["a"]}

    msg = (
        f"🧠 <b>TRIVIA</b>\n"
        f"─────────────────\n"
        f"🏷️ <b><i>Category:</i></b> <i>{trivia['cat']}</i>\n"
        f"<blockquote><b>{trivia['q']}</b></blockquote>\n\n"
        f"<b>Options</b>\n<blockquote>{trivia['options']}</blockquote>\n"
        f"─────────────────\n"
        f"<i>First correct answer wins 1 pt.</i>"
    )
    await safe_reply(update, context, msg, parse_mode='HTML')

async def scramble_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)

    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it — or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return

    asked_scramble = set(history_cache.get("scramble", []))
    available_words = [w for w in SCRAMBLE_WORDS if w not in asked_scramble]

    if not available_words:
        await safe_reply(update, context, "<blockquote>🌪️ <i>You have unscrambled every single word in my dictionary! You are a genius!</i></blockquote>", parse_mode='HTML')
        return

    word = random.choice(available_words)
    history_cache.setdefault("scramble", []).append(word)
    await save_history_async()

    scrambled = "".join(random.sample(word, len(word)))
    active_games[chat_id] = {"type": "scramble", "answer": word}

    msg = (
        f"🌪️ <b>SCRAMBLE</b> 🌪️\n"
        f"─────────────────\n"
        f"<i>Unscramble the word:</i>\n"
        f"<blockquote>🔠 <b><code>{scrambled.upper()}</code></b></blockquote>\n"
        f"─────────────────\n"
        f"<i>First correct answer earns 2 pts.</i>"
    )
    await safe_reply(update, context, msg, parse_mode='HTML')

ROULETTE_REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

def roulette_pocket(num: int) -> str:
    """Returns (colored emoji, color name) for a roulette number."""
    if num == 0: return "🟢", "GREEN"
    return ("🟥", "RED") if num in ROULETTE_REDS else ("⬛", "BLACK")

async def roulette_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id_str, user_id_str = str(update.message.chat_id), str(update.message.from_user.id)
    user_name = tg_escape(update.message.from_user.first_name)
    if chat_id_str not in scores or user_id_str not in scores[chat_id_str] or scores[chat_id_str][user_id_str]["score"] <= 0:
        await safe_reply(update, context, "<blockquote><i>You have 0 points! Earn some via /game or /scramble first.</i></blockquote>", parse_mode='HTML')
        return

    user_eff = scores[chat_id_str][user_id_str].get("effects", {})

    last_spin = user_eff.get("roulette_cooldown", 0)
    if time.time() < last_spin:
        rem_secs = int(last_spin - time.time())
        await safe_reply(update, context, f"<blockquote>⏳ <i>The wheel is still spinning! Wait <b>{rem_secs}s</b> for your next round.</i></blockquote>", parse_mode='HTML')
        return

    current_score = scores[chat_id_str][user_id_str]["score"]
    has_star = user_eff.get("star_until", 0) > time.time()

    bet = 5
    if context.args:
        bet_arg = context.args[0].lower()
        if bet_arg == "all": bet = current_score
        elif bet_arg == "half": bet = max(1, current_score // 2)
        elif bet_arg.isdigit(): bet = int(bet_arg)

    if bet <= 0 or bet > current_score:
        await safe_reply(update, context, f"<blockquote><i>Invalid bet! Your balance is <b>{current_score:,} pts</b>.</i></blockquote>", parse_mode='HTML')
        return

    number = random.randint(0, 36)
    pocket_emoji, color_name = roulette_pocket(number)

    header = (f"🎡 <b>ROULETTE ROYALE</b>\n"
              f"─────────────────\n"
              f"<blockquote>👤 <b>{user_name}</b> wagers <code>{bet:,} pts</code>"
              f"{'  ·  ⭐ <i>Star luck active!</i>' if has_star else ''}</blockquote>\n"
              f"─────────────────")

    status_msg = await safe_reply(update, context, header + "\n\n🎡 <i>The croupier spins the wheel...</i>", parse_mode='HTML')

    spin_frames = ["🎡 ○ ─────────", "🎡 ──○───────", "🎡 ────○─────",
                   "🎡 ──────○───", "🎡 ────────○─", "🎡 ─────────○",
                   "🎡 ────────○─", "🎡 ──────○───"]
    for i, frame in enumerate(spin_frames):
        await asyncio.sleep(0.45)
        try:
            await status_msg.edit_text(header + f"\n\n<code>{frame}</code>", parse_mode='HTML')
        except Exception:
            pass
    await asyncio.sleep(0.6)

    roll = random.randint(1, 100)
    if has_star:
        if roll <= 25:   profit, tier, tier_emoji = -bet, "CRITICAL MISS", "💥"
        elif roll <= 45: profit, tier, tier_emoji = 0, "SAFE — BET RETURNED", "⚖️"
        elif roll <= 75: profit, tier, tier_emoji = int(bet * 0.2), "SMALL WIN · 1.2x", "🌸"
        elif roll <= 92: profit, tier, tier_emoji = int(bet * 0.5), "GREAT WIN · 1.5x", "✨"
        elif roll <= 98: profit, tier, tier_emoji = bet, "DOUBLE WIN · 2x", "🌟"
        else:            profit, tier, tier_emoji = bet * 2, "MEGA JACKPOT · 3x", "🏆"
    else:
        if roll <= 50:   profit, tier, tier_emoji = -bet, "CRITICAL MISS", "💥"
        elif roll <= 65: profit, tier, tier_emoji = 0, "SAFE — BET RETURNED", "⚖️"
        elif roll <= 85: profit, tier, tier_emoji = int(bet * 0.2), "SMALL WIN · 1.2x", "🌸"
        elif roll <= 96: profit, tier, tier_emoji = int(bet * 0.5), "GREAT WIN · 1.5x", "✨"
        else:            profit, tier, tier_emoji = bet, "DOUBLE WIN · 2x", "🌟"

    if "effects" not in scores[chat_id_str][user_id_str]:
        scores[chat_id_str][user_id_str]["effects"] = {}
    scores[chat_id_str][user_id_str]["effects"]["roulette_cooldown"] = time.time() + 120
    await update_score(chat_id_str, user_id_str, user_name, profit)

    new_balance = scores[chat_id_str][user_id_str]['score']
    profit_str = f"+{profit:,}" if profit > 0 else ("±0" if profit == 0 else f"{profit:,}")
    flavor = ("The ball rattles... and drops into the void. Ouch." if profit < 0 else
              "A dead-center landing on the safe pocket — nobody breathes." if profit == 0 else
              "The crowd goes WILD as the ball settles!" if profit >= bet else
              "A soft landing — chips slide your way.")

    msg = (f"{header}\n\n"
           f"🎯 <i>The ball lands on...</i>\n"
           f"<blockquote><b>{pocket_emoji} {number} — {color_name}</b></blockquote>\n"
           f"<blockquote>{tier_emoji} <b>{tier}</b>\n"
           f"<i>{flavor}</i>\n"
           f"📊 Result: <code>{profit_str} pts</code>  ·  💰 Balance: <code>{new_balance:,} pts</code></blockquote>")
    await status_msg.edit_text(msg, parse_mode='HTML')

async def flip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id_str = str(update.message.chat_id)
    user_id_str = str(update.message.from_user.id)
    user_name = update.message.from_user.first_name

    if not context.args or context.args[0].lower() not in ['heads', 'tails']:
        await safe_reply(update, context, "<blockquote>🪙 <i>Please choose heads or tails! Example: <code>/flip heads</code></i></blockquote>", parse_mode='HTML')
        return

    choice = context.args[0].lower()
    current_score = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)

    if current_score <= 0:
        await safe_reply(update, context, "<blockquote><i>You have 0 points! You can't flip an empty wallet!</i></blockquote>", parse_mode='HTML')
        return

    if random.random() < 0.01:
        msg = (
            f"🪙 <b>COIN FLIP</b> 🪙\n"
            f"─────────────────\n"
            f"<blockquote>😱 <i>UNBELIEVABLE! The coin landed perfectly on its edge!</i>\n"
            f"<i>Your points remain exactly the same.</i></blockquote>\n"
            f"─────────────────"
        )
        await safe_reply(update, context, msg, parse_mode='HTML')
        return

    outcome = random.choice(['heads', 'tails'])
    if choice == outcome:
        await update_score(chat_id_str, user_id_str, user_name, current_score)
        new_score = scores[chat_id_str][user_id_str]["score"]
        msg = (
            f"🪙 <b>COIN FLIP</b> 🪙\n"
            f"─────────────────\n"
            f"<blockquote>🎉 <i>It's <b>{outcome.upper()}</b>! You guessed right!</i>\n"
            f"📈 <i>Your points have been DOUBLED!</i></blockquote>\n"
            f"<b><i>New Balance:</i></b> <b><code>{new_score:,} pts</code></b>\n"
            f"─────────────────"
        )
    else:
        await update_score(chat_id_str, user_id_str, user_name, -current_score)
        msg = (
            f"🪙 <b>COIN FLIP</b> 🪙\n"
            f"─────────────────\n"
            f"<blockquote>🥀 <i>Oh no! It was <b>{outcome.upper()}</b>. You lost everything!</i>\n"
            f"📉 <i>Your points vanished to zero!</i></blockquote>\n"
            f"<b><i>New Balance:</i></b> <b><code>0 pts</code></b>\n"
            f"─────────────────"
        )

    await safe_reply(update, context, msg, parse_mode='HTML')

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id_str = str(update.message.chat_id)
    active_chats.add(update.message.chat_id)
    if chat_id_str not in scores or not scores[chat_id_str]:
        await safe_reply(update, context, "<blockquote><i>Leaderboard database is completely empty! Play some games first!</i></blockquote>", parse_mode='HTML')
        return

    sorted_users = sorted(scores[chat_id_str].values(), key=lambda x: x["score"], reverse=True)
    lb_text = "🏆 <b>LEADERBOARD</b>\n─────────────────\n<blockquote>\n"
    for idx, user_data in enumerate(sorted_users[:10], 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"<b>{idx}.</b>"
        lb_text += f"{medal} <b><i>{tg_escape(user_data['name'])}</i></b> — <code>{user_data['score']:,} pts</code>\n"
    lb_text += "</blockquote>\n─────────────────"
    await safe_reply(update, context, lb_text, parse_mode='HTML')

STOP_WORDS = {"the", "a", "an", "is", "it", "of", "in", "on", "at", "to", "and", "or", "was", "were"}

def normalize_answer(text: str) -> str:
    t = str(text).lower().strip()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]

def fuzzy_match_answer(user_guess: str, correct_answer: str) -> bool:
    """Tiered matching: exact -> containment -> word coverage -> abbreviation -> edit distance."""
    if not user_guess or not correct_answer:
        return False
    norm_guess = normalize_answer(user_guess)
    norm_ans = normalize_answer(correct_answer)
    if not norm_guess or not norm_ans:
        return False
    if norm_guess == norm_ans:
        return True

    if len(norm_guess) >= 3 and (norm_ans in norm_guess or norm_guess in norm_ans):
        return True

    ans_words = set(norm_ans.split()) - STOP_WORDS
    guess_words = set(norm_guess.split()) - STOP_WORDS
    if len(norm_ans.split()) >= 2 and ans_words and ans_words.issubset(guess_words):
        return True

    ans_initials = "".join(w[0] for w in norm_ans.split() if w)
    ans_initials_full = ans_initials
    if len(ans_initials) >= 2 and norm_guess == ans_initials:
        return True
    if len(ans_initials_full) >= 2 and norm_guess == ans_initials_full:
        return True
    ans_alnum_initials = "".join(w[0] + (w[1:] if w[1:].isdigit() else "") for w in norm_ans.split() if w)

    if any(ch.isdigit() for ch in norm_ans) and len(ans_alnum_initials) >= 2 and norm_guess == ans_alnum_initials:
        return True

    if len(ans_initials) >= 2 and norm_guess.startswith(ans_initials) and len(norm_guess) <= len(ans_initials) + 1:
        return True
    ans_len = len(norm_ans)
    max_dist = 1 if ans_len <= 4 else 2 if ans_len <= 8 else 3 if ans_len <= 15 else 4
    if levenshtein(norm_guess, norm_ans) <= max_dist:
        return True
    if len(norm_ans.split()) >= 2 and ans_words:
        for aw in ans_words:
            word_threshold = 1 if len(aw) <= 5 else 2
            if not any(levenshtein(aw, gw) <= word_threshold for gw in guess_words):
                return False
        return True
    return False

def add_to_chat_buffer(chat_id: int, user_name: str, text: str):
    if chat_id not in chat_buffers:
        chat_buffers[chat_id] = []
    chat_buffers[chat_id].append({"name": user_name, "text": text, "time": time.time()})
    if len(chat_buffers[chat_id]) > CHAT_BUFFER_MAX:
        chat_buffers[chat_id] = chat_buffers[chat_id][-CHAT_BUFFER_MAX:]

def get_chat_context_block(chat_id: int) -> str:
    buf = chat_buffers.get(chat_id, [])
    if not buf:
        return "No prior chat context available."
    return "\n".join(f"{e['name']}: {e['text']}" for e in buf[-15:])

SPEEDY_SENTENCES = [
    "The quick brown fox jumps over the lazy dog",
    "Programming is the art of telling a computer what to do",
    "Life is like riding a bicycle to keep your balance you must keep moving",
    "The only way to do great work is to love what you do",
    "In the middle of every difficulty lies opportunity",
    "It does not matter how slowly you go as long as you do not stop",
    "The best time to plant a tree was twenty years ago the second best time is now",
    "Knowledge is power but enthusiasm pulls the switch",
    "A journey of a thousand miles begins with a single step",
    "The future belongs to those who believe in the beauty of their dreams",
    "Success is not final failure is not fatal it is the courage to continue that counts",
    "The only impossible journey is the one you never begin",
    "Everything you have ever wanted is on the other side of fear"
]

async def speedy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    chat_last_activity[chat_id] = time.time()
    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it - or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return
    sentence = random.choice(SPEEDY_SENTENCES)
    active_games[chat_id] = {"type": "speedy", "answer": sentence.lower(), "original": sentence, "start_time": time.time()}
    msg = (f"⚡ <b>SPEED RACE</b> ⚡\n─────────────────\n"
           f"<i>Type this sentence as fast as you can!</i> 🏁\n\n"
           f"<blockquote>📝 <b><code>{tg_escape(sentence)}</code></b></blockquote>\n\n"
           f"⏱️ <i>Timer starts NOW! First correct answer wins 3 points!</i>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def guess_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    chat_last_activity[chat_id] = time.time()
    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it - or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return
    target = random.randint(1, 100)
    active_games[chat_id] = {"type": "guess", "answer": str(target), "target": target, "attempts": 0, "max_attempts": 10}
    msg = (f"🔢 <b>NUMBER GUESS</b> 🔢\n─────────────────\n"
           f"<i>I'm thinking of a number between <b>1</b> and <b>100</b>!</i> 🤔\n\n"
           f"<blockquote>🎯 You have <b>10</b> attempts. I'll give you hot/cold hints!</blockquote>\n\n"
           f"<i>Just type a number in chat to guess!</i>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def mathquiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    chat_last_activity[chat_id] = time.time()
    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it - or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return
    operations = [("+", lambda a, b: a + b), ("+", lambda a, b: a + b), ("-", lambda a, b: a - b), ("x", lambda a, b: a * b)]
    op_sym, op_fn = random.choice(operations)
    if op_sym == "x":
        a, b = random.randint(2, 12), random.randint(2, 12)
    elif op_sym == "-":
        a, b = random.randint(10, 60), random.randint(1, 9)
    else:
        a, b = random.randint(5, 200), random.randint(5, 200)
    answer = op_fn(a, b)
    active_games[chat_id] = {"type": "mathquiz", "answer": str(answer)}
    msg = (f"🧮 <b>MATH QUIZ</b> 🧮\n─────────────────\n"
           f"<i>Solve this as fast as you can!</i> ⚡\n\n"
           f"<blockquote>📐 <b><code>{a} {op_sym} {b} = ?</code></b></blockquote>\n\n"
           f"<i>First correct answer gets 2 points!</i>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def handle_game_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> bool:
    """Returns True if the message was consumed by an active game."""
    if chat_id not in active_games:
        return False
    game = active_games[chat_id]
    game_type = game.get("type", "")
    user = update.message.from_user
    user_name = user.first_name
    chat_id_str, user_id_str = str(chat_id), str(user.id)
    correct_ans = str(game.get("answer", ""))

    if game_type == "guess":
        guess_text = text.strip()
        if not guess_text.isdigit():
            return False
        guess_num = int(guess_text)
        target = game.get("target", 50)
        game["attempts"] = game.get("attempts", 0) + 1
        if guess_num == target:
            attempts = game["attempts"]
            pts = max(1, 5 - attempts)
            del active_games[chat_id]
            await update_score(chat_id_str, user_id_str, user_name, pts)
            msg = (f"🎉 <b>CORRECT!</b> 🎉\n─────────────────\n"
                   f"<blockquote>🎯 <b><i>{tg_escape(user_name)}</i></b> guessed <b><code>{target}</code></b> in <b>{attempts}</b> attempts!\n"
                   f"📊 <b><i>Points:</i></b> <b><code>+{pts} pts</code></b></blockquote>\n─────────────────")
            await safe_reply(update, context, msg, parse_mode='HTML')
            return True
        if game["attempts"] >= game.get("max_attempts", 10):
            del active_games[chat_id]
            await safe_reply(update, context, f"<blockquote>💀 <b>GAME OVER!</b> The number was <b><code>{target}</code></b>!</blockquote>", parse_mode='HTML')
            return True
        diff = abs(guess_num - target)
        hint = "🔥🔥🔥 BURNING HOT!" if diff <= 3 else "🔥 Very hot!" if diff <= 7 else "♨️ Warm..." if diff <= 15 else "🧊 Cool..." if diff <= 25 else "❄️❄️ ICE COLD!"
        direction = "higher ⬆️" if guess_num < target else "lower ⬇️"
        remaining = game.get("max_attempts", 10) - game["attempts"]
        await safe_reply(update, context, f"<blockquote>{hint} Go {direction}\n📊 <i>Attempts left: <b>{remaining}</b></i></blockquote>", parse_mode='HTML')
        return True

    if game_type == "speedy":
        if normalize_answer(text) == normalize_answer(game.get("answer", "")):
            elapsed = time.time() - game.get("start_time", time.time())
            word_count = len(game.get("original", "").split())
            wpm = int((word_count / elapsed) * 60) if elapsed > 0 else 0
            del active_games[chat_id]
            await update_score(chat_id_str, user_id_str, user_name, 3)
            msg = (f"⚡ <b>SPEEDY WINNER!</b> ⚡\n─────────────────\n"
                   f"<blockquote>🏆 <b><i>{tg_escape(user_name)}</i></b> typed it in <b>{elapsed:.1f}s</b>!\n"
                   f"📊 <b><i>Speed:</i></b> <b><code>{wpm} WPM</code></b> 🚀\n"
                   f"💰 <b><i>Points:</i></b> <b><code>+3 pts</code></b></blockquote>\n─────────────────")
            await safe_reply(update, context, msg, parse_mode='HTML')
            return True
        return False

    if fuzzy_match_answer(text, correct_ans):
        pts_earned = 2 if game_type in ("scramble", "mathquiz", "flag") else 1
        streak_bonus = 0
        if game_type == "trivia":
            streak = trivia_streaks.get(chat_id)
            if streak and streak.get("user_id") == user.id:
                streak["count"] += 1
                if streak["count"] >= 3:
                    streak_bonus = streak["count"] - 2
            else:
                trivia_streaks[chat_id] = {"user_id": user.id, "count": 1}
            pts_earned += streak_bonus
        del active_games[chat_id]
        await update_score(chat_id_str, user_id_str, user_name, pts_earned)
        streak_text = ""
        if streak_bonus > 0:
            streak_text = f"\n🔥 <b><i>Streak Bonus:</i></b> <b><code>+{streak_bonus} pts</code></b> (x{trivia_streaks[chat_id]['count']} streak!)"
        win_msg = (f"✅ <b>CORRECT!</b> ✅\n─────────────────\n"
                   f"<blockquote>\n🎉 <b><i>{tg_escape(user_name)}</i></b> answered correctly!\n"
                   f"✨ <b><i>Answer:</i></b> <b><code>{tg_escape(correct_ans.title())}</code></b>\n"
                   f"📊 <b><i>Points Earned:</i></b> <b><code>+{pts_earned} pts</code></b>{streak_text}\n"
                   f"</blockquote>\n─────────────────\n")
        await safe_reply(update, context, win_msg, parse_mode='HTML')
        return True
    return False

FLAG_DATA = [
    ("🇯🇵", "japan"), ("🇫🇷", "france"), ("🇧🇷", "brazil"), ("🇮🇳", "india"),
    ("🇩🇪", "germany"), ("🇮🇹", "italy"), ("🇰🇷", "south korea"), ("🇺🇸", "united states"),
    ("🇬🇧", "united kingdom"), ("🇨🇦", "canada"), ("🇦🇺", "australia"), ("🇲🇽", "mexico"),
    ("🇪🇸", "spain"), ("🇵🇹", "portugal"), ("🇳🇱", "netherlands"), ("🇸🇪", "sweden"),
    ("🇳🇴", "norway"), ("🇫🇮", "finland"), ("🇩🇰", "denmark"), ("🇵🇱", "poland"),
    ("🇹🇷", "turkey"), ("🇪🇬", "egypt"), ("🇿🇦", "south africa"), ("🇦🇷", "argentina"),
    ("🇨🇱", "chile"), ("🇨🇴", "colombia"), ("🇵🇪", "peru"), ("🇹🇭", "thailand"),
    ("🇻🇳", "vietnam"), ("🇮🇩", "indonesia"), ("🇵🇭", "philippines"), ("🇲🇾", "malaysia"),
    ("🇸🇬", "singapore"), ("🇳🇿", "new zealand"), ("🇮🇪", "ireland"), ("🇨🇭", "switzerland"),
    ("🇦🇹", "austria"), ("🇧🇪", "belgium"), ("🇨🇿", "czech republic"), ("🇭🇺", "hungary"),
    ("🇬🇷", "greece"), ("🇮🇱", "israel"), ("🇸🇦", "saudi arabia"), ("🇦🇪", "united arab emirates"),
    ("🇶🇦", "qatar"), ("🇰🇪", "kenya"), ("🇳🇬", "nigeria"), ("🇪🇹", "ethiopia"),
    ("🇲🇦", "morocco"), ("🇹🇳", "tunisia"), ("🇺🇦", "ukraine"), ("🇷🇴", "romania")
]

async def flag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    chat_last_activity[chat_id] = time.time()
    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it - or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return
    flag_emoji, country = random.choice(FLAG_DATA)
    active_games[chat_id] = {"type": "flag", "answer": country}

    flag_url = None
    try:
        iso = "".join(chr(ord(c) - 0x1F1E6 + 97) for c in flag_emoji if ord(c) >= 0x1F1E6)
        if len(iso) == 2:
            flag_url = f"https://flagcdn.com/w640/{iso}.png"
    except Exception:
        pass

    caption = (f"🌍 <b>FLAG CHALLENGE</b> 🌍\n─────────────────\n"
               f"<i>Which country does this flag belong to?</i> 🏳️\n\n"
               f"<i>First correct answer gets 2 points!</i>\n─────────────────")
    if flag_url:
        try:
            await update.message.reply_photo(photo=flag_url, caption=caption, parse_mode='HTML')
            return
        except Exception as e:
            logging.warning(f"Flag image failed, using emoji: {e}")
    msg = caption.replace("Which country", f"Which country does {flag_emoji} {flag_emoji} {flag_emoji} belong to?")
    await safe_reply(update, context, msg, parse_mode='HTML')

HANGMAN_WORDS = [
    "python", "javascript", "telegram", "computer", "keyboard", "programming",
    "algorithm", "database", "internet", "software", "hardware", "network",
    "pizza", "burger", "chocolate", "icecream", "sandwich", "pancake",
    "guitar", "piano", "violin", "drums", "trumpet", "flute",
    "elephant", "giraffe", "penguin", "dolphin", "butterfly", "octopus",
    "mountain", "ocean", "rainbow", "thunder", "volcano", "glacier",
    "adventure", "mystery", "treasure", "journey", "freedom", "harmony"
]

HANGMAN_STAGES = [
    "<pre>  ┌───┐\n  │\n  │\n  │\n──┴────</pre>",
    "<pre>  ┌───┐\n  │   😊\n  │\n  │\n──┴────</pre>",
    "<pre>  ┌───┐\n  │   😐\n  │   │\n  │\n──┴────</pre>",
    "<pre>  ┌───┐\n  │   😟\n  │  ╱│\n  │\n──┴────</pre>",
    "<pre>  ┌───┐\n  │   😨\n  │  ╱│╲\n  │\n──┴────</pre>",
    "<pre>  ┌───┐\n  │   😰\n  │  ╱│╲\n  │  ╱\n──┴────</pre>",
    "<pre>  ┌───┐\n  │  \n  │  ╱│╲\n  │  ╱ ╲\n──┴────</pre>"
]

HANGMAN_LIVES = ["❤️❤️❤️❤️❤️❤️", "❤️❤️❤️❤️❤️🖤", "❤️❤️❤️❤️🖤🖤", "❤️❤️❤️🖤🖤🖤",
                 "❤️❤️🖤🖤🖤🖤", "❤️🖤🖤🖤🖤🖤", "🖤🖤🖤🖤🖤🖤"]

def hangman_display(game) -> str:
    """Renders the word with clean spacing."""
    return " ".join(c.upper() if c in game["guessed"] else "▁" for c in game["word"])

def hangman_status(game) -> str:
    """Full status block shared by all hangman states."""
    used = " ".join(sorted(l.upper() for l in game["guessed"])) or "—"
    return (f"{HANGMAN_STAGES[game['wrong']]}\n"
            f"<blockquote><code>{hangman_display(game)}</code></blockquote>\n"
            f"❤️ {HANGMAN_LIVES[game['wrong']]}\n"
            f"🔤 <b>Used:</b> <code>{used}</code>")

async def hangman_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    chat_last_activity[chat_id] = time.time()
    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it — or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return
    word = random.choice(HANGMAN_WORDS).lower()
    hangman_games[chat_id] = {"word": word, "guessed": set(), "wrong": 0, "max_wrong": 6}
    msg = (f"🎯 <b>HANGMAN</b>\n"
           f"─────────────────\n"
           f"{hangman_status(hangman_games[chat_id])}\n"
           f"─────────────────\n"
           f"<blockquote><i>Type a single letter to guess, or the whole word to solve it — worth <b>3 pts</b>!</i></blockquote>")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def handle_hangman_guess(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> bool:
    """Process hangman letter/word guesses. Returns True if consumed."""
    if chat_id not in hangman_games:
        return False
    game = hangman_games[chat_id]
    text = text.strip().lower()
    user = update.message.from_user
    user_name = user.first_name
    chat_id_str, user_id_str = str(chat_id), str(user.id)

    if len(text) == 1 and text.isalpha():
        if text in game["guessed"]:
            await safe_reply(update, context, f"<blockquote><i>You already guessed <b>{text.upper()}</b>!</i> 🔄</blockquote>", parse_mode='HTML')
            return True
        game["guessed"].add(text)
        if text in game["word"]:
            if all(c in game["guessed"] for c in game["word"]):
                await update_score(chat_id_str, user_id_str, user_name, 3)
                del hangman_games[chat_id]
                msg = (f"🏆 <b>HANGMAN — SOLVED!</b>\n"
                       f"─────────────────\n"
                       f"{hangman_status(game)}\n"
                       f"─────────────────\n"
                       f"<blockquote><i><b>{tg_escape(user_name)}</b> saved the day — the word was "
                       f"<b><code>{game['word'].upper()}</code></b>! <b>+3 pts</b></i></blockquote>")
                await safe_reply(update, context, msg, parse_mode='HTML')
            else:
                msg = (f"✅ <b>Nice one — <code>{text.upper()}</code> is in the word!</b>\n"
                       f"─────────────────\n{hangman_status(game)}")
                await safe_reply(update, context, msg, parse_mode='HTML')
        else:
            game["wrong"] += 1
            if game["wrong"] >= game["max_wrong"]:
                del hangman_games[chat_id]
                msg = (f"💀 <b>HANGMAN — GAME OVER</b>\n"
                       f"─────────────────\n"
                       f"{hangman_status(game)}\n"
                       f"─────────────────\n"
                       f"<blockquote>The word was <b><code>{game['word'].upper()}</code></b>.\n"
                       f"<i>Better luck next time!</i></blockquote>")
                await safe_reply(update, context, msg, parse_mode='HTML')
            else:
                msg = (f"❌ <b>Nope — no <code>{text.upper()}</code> in there!</b>\n"
                       f"─────────────────\n{hangman_status(game)}")
                await safe_reply(update, context, msg, parse_mode='HTML')
        return True

    if text == game["word"]:
        await update_score(chat_id_str, user_id_str, user_name, 3)
        game["guessed"].update(game["word"])
        del hangman_games[chat_id]
        msg = (f"🏆 <b>HANGMAN — SOLVED!</b>\n"
               f"─────────────────\n"
               f"{hangman_status(game)}\n"
               f"─────────────────\n"
               f"<blockquote><i><b>{tg_escape(user_name)}</b> guessed the whole word in one shot — "
               f"<b><code>{game['word'].upper()}</code></b>! <b>+3 pts</b></i></blockquote>")
        await safe_reply(update, context, msg, parse_mode='HTML')
        return True

    return False

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PvP dice battle. /dice @username [bet]"""
    chat_id = update.message.chat_id
    user = update.message.from_user
    chat_id_str, user_id_str = str(chat_id), str(user.id)
    chat_last_activity[chat_id] = time.time()
    if not context.args:
        await safe_reply(update, context, "<blockquote>🎲 <i>Usage: <code>/dice @username [bet_amount]</code></i></blockquote>", parse_mode='HTML')
        return
    bet = int(context.args[1]) if len(context.args) >= 2 and context.args[1].isdigit() else 0
    challenger_score = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)
    if bet > 0 and bet > challenger_score:
        await safe_reply(update, context, f"<blockquote><i>You only have <b>{challenger_score:,}</b> pts!</i></blockquote>", parse_mode='HTML')
        return
    roll1, roll2 = random.randint(1, 6), random.randint(1, 6)
    dice_faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    if roll1 > roll2:
        result_text = f"🎉 <b>{tg_escape(user.first_name)}</b> wins!"
        if bet > 0:
            await update_score(chat_id_str, user_id_str, user.first_name, bet)
    elif roll2 > roll1:
        result_text = "😈 <b>Opponent</b> wins!"
        if bet > 0:
            await update_score(chat_id_str, user_id_str, user.first_name, -bet)
    else:
        result_text = "🤝 <b>It's a tie!</b>"
    msg = (f"🎲 <b>DICE BATTLE</b> 🎲\n─────────────────\n"
           f"<blockquote>\n🎲 <b>{tg_escape(user.first_name)}:</b> {dice_faces[roll1-1]} ({roll1})\n"
           f"🎲 <b>Opponent:</b> {dice_faces[roll2-1]} ({roll2})\n</blockquote>\n"
           f"<blockquote>{result_text}</blockquote>\n")
    if bet > 0:
        new_bal = scores.get(chat_id_str, {}).get(user_id_str, {}).get("score", 0)
        msg += f"💰 <b><i>Balance:</i></b> <b><code>{new_bal:,} pts</code></b>\n"
    msg += "─────────────────"
    await safe_reply(update, context, msg, parse_mode='HTML')

JOKES = [
    "Why don't scientists trust atoms? Because they make up everything! 😂",
    "I told my wife she was drawing her eyebrows too high. She looked surprised. 🤨",
    "Why did the scarecrow win an award? Because he was outstanding in his field! 🌾",
    "What do you call a fish without eyes? A fsh! 🐟",
    "Why don't eggs tell jokes? They'd crack each other up! 🥚",
    "What do you call a bear with no teeth? A gummy bear! 🐻",
    "Why did the math book look so sad? Because it had too many problems! 📐",
    "What do you call a sleeping dinosaur? A dino-snore! 🦕",
    "Why did the cookie go to the doctor? Because it felt crumbly! 🍪",
    "What do you call a fake noodle? An impasta! 🍝",
    "Why did the bicycle fall over? Because it was two-tired! 🚲",
    "What did the ocean say to the beach? Nothing, it just waved! 🌊",
    "Why did the tomato turn red? Because it saw the salad dressing! 🍅",
    "What do you call a boomerang that doesn't come back? A stick! 🪃",
    "Why don't skeletons fight each other? They don't have the guts!"
]

FACTS = [
    "🍯 Honey never spoils. Archaeologists found 3000-year-old honey in Egyptian tombs that's still edible!",
    "🐙 An octopus has three hearts and blue blood!",
    "🍌 Bananas are berries, but strawberries aren't!",
    "🦈 Sharks existed before trees! Sharks are ~450 million years old, trees ~350 million.",
    "🧠 Your brain generates about 12-25 watts of electricity — enough to power an LED!",
    "🐌 A snail can sleep for up to 3 years!",
    "🌕 Footprints on the Moon will last 100 million years — there's no wind to erode them!",
    "🔥 Hot water can freeze faster than cold water. It's called the Mpemba effect!",
    "🐝 Bees can recognize human faces!",
    "💎 On Saturn and Jupiter, it rains diamonds!",
    "🐘 Elephants are the only animals that can't jump!",
    "🌈 A rainbow is actually a full circle — you only see half of it!",
    "⚡ Lightning strikes Earth about 100 times per second!",
    "🐧 Penguins have knees! They're just hidden under their feathers!",
    "🧬 You share about 60% of your DNA with bananas!",
    "🌊 The ocean produces over 50% of the world's oxygen!"
]

WYR_QUESTIONS = [
    "Would you rather be able to fly 🦅 or be invisible 👻?",
    "Would you rather always be 10 minutes late ⏰ or always 20 minutes early ⏳?",
    "Would you rather have unlimited money 💰 or unlimited love ❤️?",
    "Would you rather live without music 🎵 or without movies 🎬?",
    "Would you rather talk to animals 🐾 or speak all human languages 🗣️?",
    "Would you rather fight 100 duck-sized horses 🦆 or 1 horse-sized duck 🐴?",
    "Would you rather never use social media again 📵 or never watch movies/TV 📺?",
    "Would you rather have a rewind button ⏪ or a pause button ⏸️ for your life?",
    "Would you rather be the funniest person in the room 😂 or the smartest 🧠?",
    "Would you rather live in the past 🏰 or the future 🚀?",
    "Would you rather eat only pizza 🍕 or only burgers 🍔 forever?",
    "Would you rather read minds 🧠 or predict the future 🔮?",
    "Would you rather have a pet dragon 🐉 or a pet unicorn 🦄?",
    "Would you rather always sing instead of speak 🎤 or dance everywhere 💃?",
    "Would you rather live underwater 🌊 or in outer space 🌌?",
    "Would you rather be famous 🌟 or rich 💎?",
    "Would you rather have super strength 💪 or super speed ⚡?",
    "Would you rather never feel cold ❄️ or never feel hot 🔥?"
]

WORDLE_WORDS = {
    4: [
        "rain", "moon", "star", "wolf", "fire", "wind", "snow", "gold",
        "rose", "leaf", "ship", "wave", "rock", "bird", "fish", "cake",
        "door", "tree", "lake", "hill", "book", "ring", "king", "lion",
        "bear", "deer", "frog", "crab", "crow", "dove", "gate", "hero",
        "iris", "jade", "kiss", "lamp", "mint", "nest", "opal", "pond",
        "quiz", "ruby", "sand", "tide", "unit", "vine", "wish", "yarn",
        "zero", "aqua", "bolt", "cube", "dusk", "echo", "fern", "glow"
    ],
    5: [
        "apple", "beach", "brain", "bread", "brush", "chair", "charm", "cloud",
        "dance", "dream", "eagle", "earth", "flame", "frost", "grape", "heart",
        "honey", "house", "juice", "knife", "lemon", "light", "magic", "mango",
        "music", "night", "ocean", "panda", "pearl", "piano", "pizza", "plant",
        "queen", "river", "robot", "smile", "snake", "solar", "spice", "storm",
        "sugar", "tiger", "toast", "tower", "train", "trick", "ultra", "vivid",
        "water", "whale", "world", "youth", "zebra", "angel", "bloom", "candy",
        "crisp", "daisy", "ember", "fairy", "globe", "happy", "ivory", "jelly"
    ],
    6: [
        "banana", "castle", "dragon", "flower", "garden", "island", "jungle",
        "knight", "ladder", "market", "nature", "orange", "palace", "rabbit",
        "silver", "temple", "umbrella", "valley", "window", "yellow", "anchor",
        "bridge", "camera", "dinner", "engine", "forest", "galaxy", "hammer",
        "insect", "jacket", "karate", "laptop", "magnet", "needle", "oxygen",
        "pencil", "quartz", "rocket", "sunset", "tennis", "unicorn", "violet",
        "walnut", "yogurt", "zipper", "basket", "candle", "desert", "falcon",
        "gravel", "harbor", "kitten", "lizard", "meadow", "napkin", "orchid"
    ]
}

WORDLE_MAX_TRIES = {4: 5, 5: 6, 6: 7}
WORDLE_POINTS = {4: 3, 5: 4, 6: 6}

def wordle_feedback(guess: str, target: str) -> str:
    """Returns emoji row: 🟩 correct spot, 🟨 in word wrong spot, 🟥 not in word."""
    n = len(target)
    result = ["🟥"] * n
    target_chars = list(target)
    for i in range(n):
        if guess[i] == target[i]:
            result[i] = "🟩"
            target_chars[i] = None
    for i in range(n):
        if result[i] == "🟥" and guess[i] in target_chars:
            result[i] = "🟨"
            target_chars[target_chars.index(guess[i])] = None
    return "".join(result)

async def wordle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    active_chats.add(chat_id)
    chat_last_activity[chat_id] = time.time()
    state = chat_game_state(chat_id)
    if state:
        msg = (f"⚠️ <b>GAME IN PROGRESS</b>\n"
               f"─────────────────\n"
               f"<blockquote>{state} is already running in this chat.\n"
               f"<i>Finish it — or force-end it below.</i></blockquote>")
        await safe_reply(update, context, msg, reply_markup=end_game_kb(chat_id), parse_mode='HTML')
        return
    wordle_pending[chat_id] = {"user_id": update.message.from_user.id}
    kb = [[
        InlineKeyboardButton("4️⃣ Easy", callback_data="wordlelen_4"),
        InlineKeyboardButton("5️⃣ Classic", callback_data="wordlelen_5"),
        InlineKeyboardButton("6️⃣ Hard", callback_data="wordlelen_6")
    ]]
    msg = (f"🟩 <b>WORDLE</b>\n"
           f"─────────────────\n"
           f"<blockquote><i>I'm thinking of a secret word. Crack it before you run out of tries!</i>\n\n"
           f"🟩 correct letter, correct spot\n"
           f"🟨 correct letter, wrong spot\n"
           f"🟥 letter not in the word</blockquote>\n"
           f"<b>Choose your word length:</b>")
    await safe_reply(update, context, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def wordle_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data
    if not data.startswith("wordlelen_"): return
    length = int(data.split("_")[1])
    pending = wordle_pending.get(chat_id)
    if pending is None:
        await query.answer("This menu has expired! Start a new /wordle.", show_alert=True)
        return
    if query.from_user.id != pending.get("user_id"):
        await query.answer("Only the player who started can pick the mode!", show_alert=True)
        return
    del wordle_pending[chat_id]
    word = random.choice(WORDLE_WORDS[length])
    wordle_games[chat_id] = {"word": word, "guesses": [], "max": WORDLE_MAX_TRIES[length], "len": length}
    mode_names = {4: "Easy", 5: "Classic", 6: "Hard"}
    msg = (f"🟩 <b>WORDLE · {mode_names[length].upper()} MODE</b>\n"
           f"─────────────────\n"
           f"<blockquote><i>A <b>{length}-letter</b> word is locked in!</i>\n"
           f"🎯 Tries: <b>{WORDLE_MAX_TRIES[length]}</b>  ·  💰 Reward: <b>{WORDLE_POINTS[length]} pts</b></blockquote>\n"
           f"<i>Type any {length}-letter word in chat to guess.</i>")
    await query.edit_message_text(msg, parse_mode='HTML')

async def handle_wordle_guess(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> bool:
    """Process wordle guesses. Returns True if consumed."""
    if chat_id not in wordle_games:
        return False
    text = text.strip().lower()
    game = wordle_games[chat_id]
    word_len = game.get("len", len(game["word"]))
    if len(text) != word_len or not text.isalpha():
        return False
    user = update.message.from_user
    user_name = user.first_name
    chat_id_str, user_id_str = str(chat_id), str(user.id)

    feedback = wordle_feedback(text, game["word"])
    game["guesses"].append((text, feedback))
    board = "\n".join(f"{fb}  <code>{g.upper()}</code>" for g, fb in game["guesses"])
    remaining = game["max"] - len(game["guesses"])
    pts = WORDLE_POINTS.get(word_len, 4)

    if text == game["word"]:
        await update_score(chat_id_str, user_id_str, user_name, pts)
        tries = len(game["guesses"])
        del wordle_games[chat_id]
        msg = (f"🏆 <b>WORDLE — SOLVED!</b>\n"
               f"─────────────────\n"
               f"{board}\n"
               f"─────────────────\n"
               f"<blockquote><i><b>{tg_escape(user_name)}</b> cracked <b><code>{game['word'].upper()}</code></b> "
               f"in <b>{tries}/{game['max']}</b> tries — <b>+{pts} pts!</b></i></blockquote>")
        await safe_reply(update, context, msg, parse_mode='HTML')
        return True

    if remaining <= 0:
        del wordle_games[chat_id]
        msg = (f"💀 <b>WORDLE — GAME OVER</b>\n"
               f"─────────────────\n"
               f"{board}\n"
               f"─────────────────\n"
               f"<blockquote>The word was <b><code>{game['word'].upper()}</code></b>.\n"
               f"<i>Better luck next time!</i></blockquote>")
        await safe_reply(update, context, msg, parse_mode='HTML')
        return True

    msg = (f"🟩 <b>WORDLE</b> · <i>{remaining} tries left</i>\n"
           f"─────────────────\n{board}\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')
    return True

def _get_font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = (["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"] if bold
                  else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"])
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _wrap_text_px(draw, text: str, font, max_width: int):
    lines, current = [], ""
    for word in str(text).split():
        test = f"{current} {word}".strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]

def _render_quote_image(text: str, author: str, avatar_img=None) -> bytes:
    """Render a quote sticker with a smooth Instagram-style gradient, big quote
    mark, centered text and an author chip at the bottom."""
    from PIL import Image, ImageDraw
    import io as _io
    W, H = 512, 512

    c1 = (88, 40, 180)
    c2 = (220, 50, 120)
    grad = Image.new("RGB", (2, 256))
    for i in range(256):
        t = i / 255
        col = (int(c1[0] + (c2[0] - c1[0]) * t),
               int(c1[1] + (c2[1] - c1[1]) * t),
               int(c1[2] + (c2[2] - c1[2]) * t))
        grad.putpixel((0, i), col)
        grad.putpixel((1, i), col)
    grad = grad.resize((W, H))
    img = grad.convert("RGBA")

    rmask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(rmask).rounded_rectangle([0, 0, W, H], radius=44, fill=255)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(img, (0, 0), rmask)
    img = out
    draw = ImageDraw.Draw(img)

    f_qm = _get_font(190, bold=True)
    draw.text((28, -34), "\u201C", font=f_qm, fill=(255, 255, 255, 80))

    f_quote = _get_font(33, bold=True)
    lines = _wrap_text_px(draw, text, f_quote, W - 100)[:8]
    total_h = len(lines) * 44
    ty = max(120, (H - total_h) // 2 - 10)
    for ln in lines:
        draw.text((50, ty), ln, font=f_quote, fill=(255, 255, 255, 255))
        ty += 44

    ay, ax, ar = H - 88, 78, 30
    drew_avatar = False
    if avatar_img is not None:
        try:
            av = avatar_img.convert("RGBA").resize((ar * 2, ar * 2))
            avm = Image.new("L", (ar * 2, ar * 2), 0)
            ImageDraw.Draw(avm).ellipse([0, 0, ar * 2, ar * 2], fill=255)
            img.paste(av, (ax - ar, ay - ar), avm)
            draw.ellipse([ax - ar - 2, ay - ar - 2, ax + ar + 2, ay + ar + 2],
                         outline=(255, 255, 255, 255), width=3)
            drew_avatar = True
        except Exception:
            pass
    if not drew_avatar:
        initials = "".join(w[0] for w in (author or "?").split()[:2]).upper() or "?"
        draw.ellipse([ax - ar, ay - ar, ax + ar, ay + ar], fill=(255, 255, 255, 235))
        f_init = _get_font(26, bold=True)
        tw = draw.textlength(initials, font=f_init)
        draw.text((ax - tw / 2, ay - 16), initials, font=f_init, fill=(150, 50, 120, 255))

    f_name = _get_font(28, bold=True)
    draw.text((ax + ar + 16, ay - 17), (author or "Myra")[:26], font=f_name, fill=(255, 255, 255, 255))

    f_sig = _get_font(16)
    sig = "via Myra"
    sw = draw.textlength(sig, font=f_sig)
    draw.text((W - sw - 22, H - 30), sig, font=f_sig, fill=(255, 255, 255, 150))

    buf = _io.BytesIO()
    img.save(buf, format="WEBP", quality=95)
    return buf.getvalue()

async def _fetch_avatar(bot, user_id: int):
    from PIL import Image
    import io as _io
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            fid = photos.photos[0][-1].file_id
            f = await bot.get_file(fid)
            raw = await f.download_as_bytearray()
            return Image.open(_io.BytesIO(bytes(raw)))
    except Exception:
        pass
    return None

async def q_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = update.message.reply_to_message
    custom_text = " ".join(context.args) if context.args else ""

    if not reply and not custom_text:
        await safe_reply(update, context,
            "<blockquote><i>Reply to a message with <b>/q</b>, or use <b>/q your text</b> to make it a sticker.</i> 🎨</blockquote>",
            parse_mode='HTML')
        return

    if reply:
        text = reply.text or reply.caption or ""
        author = reply.from_user.first_name if reply.from_user else "Unknown"
        author_id = reply.from_user.id if reply.from_user else None
        if not text:
            await safe_reply(update, context, "<blockquote><i>That message has no text to quote!</i></blockquote>", parse_mode='HTML')
            return
    else:
        text = custom_text
        author = update.message.from_user.first_name
        author_id = update.message.from_user.id

    status = await safe_reply(update, context, "<blockquote>🎨 <i>Painting your quote...</i></blockquote>", parse_mode='HTML')
    try:
        avatar = await _fetch_avatar(context.bot, author_id) if author_id else None
        webp = await asyncio.to_thread(_render_quote_image, text[:300], author, avatar)
        import io as _io

        try:
            LAST_QUOTE_WEBP[update.effective_chat.id] = webp
        except NameError:
            pass
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Save to my sticker pack",
                                                         callback_data=f"ownq_{update.effective_chat.id}")]])
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=_io.BytesIO(webp),
                                       reply_markup=kb)
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/q sticker error: {e}")
        err = f"<blockquote><i>Sticker engine failed:</i> <code>{tg_escape(str(e)[:120])}</code></blockquote>"
        if status:
            try: await status.edit_text(err, parse_mode='HTML')
            except Exception: pass
        else:
            await safe_reply(update, context, err, parse_mode='HTML')

QRAND_QUOTES = [
    ("Push through the pain — giving up hurts more.", "Myra"),
    ("A smooth sea never made a skilled sailor.", "Myra"),
    ("Small steps every day become giant leaps.", "Myra"),
    ("You were born to stand out, not fit in.", "Myra"),
    ("Dream big. Work hard. Stay humble.", "Myra"),
    ("The best view comes after the hardest climb.", "Myra"),
    ("Stars can't shine without darkness.", "Myra"),
    ("Your vibe attracts your tribe.", "Myra"),
    ("Be the energy you want to attract.", "Myra"),
    ("Fall seven times, stand up eight.", "Myra")
]

async def qrand_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, author = random.choice(QRAND_QUOTES)
    status = await safe_reply(update, context, "<blockquote>🎨 <i>Summoning a random quote...</i></blockquote>", parse_mode='HTML')
    try:
        webp = await asyncio.to_thread(_render_quote_image, text, author, None)
        import io as _io
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=_io.BytesIO(webp))
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/qrand sticker error: {e}")
        if status:
            try: await status.edit_text("<blockquote><i>Sticker engine failed! Try again.</i></blockquote>", parse_mode='HTML')
            except Exception: pass

TRUTHS = [
    "What's the most embarrassing thing in your search history?",
    "Who in this group would you call first if you needed help moving a body... of laundry?",
    "What's the biggest lie you've ever told your parents?",
    "What's your most controversial food opinion?",
    "Have you ever pretended to be sick to skip school/work? Spill!",
    "What's the longest you've gone without showering?",
    "Who was your first crush?",
    "What's something you've done that you'd never admit to your family?",
    "What's the dumbest way you've injured yourself?",
    "If you had to delete one app from your phone forever, which would hurt the most?",
    "What's the most childish thing you still do?",
    "Have you ever stalked someone's profile and accidentally liked an old post?",
    "What's your guilty pleasure song?",
    "What's the worst date you've ever been on?",
    "If your life was a movie, what would the embarrassing title be?"
]

DARES = [
    "Send a voice message singing your favorite song for 15 seconds!",
    "Change your profile name to something embarrassing for 10 minutes!",
    "Text your crush 'I had a dream about you' right now!",
    "Send the 5th photo in your gallery to this chat!",
    "Talk in only emojis for the next 5 messages!",
    "Let the group choose your profile picture for 1 hour!",
    "Send a message to your mom saying 'I have a confession' and share her reply!",
    "Do 20 pushups right now and report back!",
    "Speak in rhymes until your next turn!",
    "Send the last meme you saved!",
    "Call a random contact and say 'the package is delivered' then hang up!",
    "Type with your eyes closed for your next 3 messages!",
    "Confess your most unpopular opinion to the group!",
    "Let the person who dared you ask you ANY question — answer honestly!",
    "Send a dramatic voice note pretending to be a movie trailer narrator about your day!"
]

EIGHT_BALL = [
    "🎱 It is certain.", "🎱 Without a doubt.", "🎱 Yes, definitely!",
    "🎱 Most likely.", "🎱 Signs point to yes.", "🎱 Ask again later...",
    "🎱 Cannot predict now.", "🎱 Concentrate and ask again.",
    "🎱 Don't count on it.", "🎱 My reply is no.", "🎱 Outlook not so good.",
    "🎱 Very doubtful.", "🎱 Absolutely not.", "🎱 The stars say yes!",
    "🎱 100% YES!", "🎱 Hmm... risky. 🤔"
]

async def truth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"🎭 <b>TRUTH</b>\n─────────────────\n"
           f"<blockquote>💬 <i>{tg_escape(random.choice(TRUTHS))}</i></blockquote>\n"
           f"<i>Answer honestly or take a dare!</i>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def dare_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"😈 <b>DARE</b>\n─────────────────\n"
           f"<blockquote>⚡ <i>{tg_escape(random.choice(DARES))}</i></blockquote>\n"
           f"<i>Complete it or take 2 truths!</i>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def eightball_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args) if context.args else "the void"
    msg = (f"🔮 <b>8-BALL</b>\n─────────────────\n"
           f"<blockquote><i>{tg_escape(question)}</i></blockquote>\n"
           f"<blockquote><b>{random.choice(EIGHT_BALL)}</b></blockquote>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def rps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choices = {"rock": "🪨", "paper": "📄", "scissors": "✂️", "r": "🪨", "p": "📄", "s": "✂️"}
    if not context.args or context.args[0].lower() not in choices:
        await safe_reply(update, context, "<blockquote>✊ <i>Usage: <code>/rps rock</code>, <code>/rps paper</code>, or <code>/rps scissors</code></i></blockquote>", parse_mode='HTML')
        return
    user_choice = choices[context.args[0].lower()]
    bot_choice = random.choice(list(set(choices.values())))
    beats = {"🪨": "✂️", "📄": "🪨", "✂️": "📄"}
    chat_id_str, user_id_str = str(update.message.chat_id), str(update.message.from_user.id)
    if user_choice == bot_choice:
        result, pts = "🤝 <b>Tie!</b>", 0
    elif beats[user_choice] == bot_choice:
        result, pts = "🎉 <b>You win! +1 pt!</b>", 1
    else:
        result, pts = "😈 <b>I win!</b>", 0
    if pts:
        await update_score(chat_id_str, user_id_str, update.message.from_user.first_name, pts)
    msg = (f"✊ <b>RPS</b>\n─────────────────\n"
           f"<blockquote>👤 You: {user_choice}  vs  🤖 Me: {bot_choice}</blockquote>\n"
           f"<blockquote>{result}</blockquote>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def roll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dice_spec = context.args[0].lower() if context.args else "1d6"
    match = re.match(r'^(\d{1,2})d(\d{1,3})$', dice_spec)
    if match:
        num_dice, sides = min(int(match.group(1)), 10), min(int(match.group(2)), 100)
    else:
        num_dice, sides = 1, 6
    rolls = [random.randint(1, sides) for _ in range(num_dice)]
    total = sum(rolls)
    dice_faces = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
    visual = " ".join(dice_faces.get(r, f"[{r}]") for r in rolls)
    msg = (f"🎲 <b>DICE ROLL</b>\n─────────────────\n"
           f"<blockquote><b>{num_dice}d{sides}:</b> {visual}\n"
           f"<b>Total:</b> <code>{total}</code></blockquote>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def joke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"😂 <b>JOKE</b>\n─────────────────\n"
           f"<blockquote>{tg_escape(random.choice(JOKES))}</blockquote>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def fact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"💡 <b>DID YOU KNOW?</b>\n─────────────────\n"
           f"<blockquote>{tg_escape(random.choice(FACTS))}</blockquote>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def wyr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (f"🤔 <b>WOULD YOU RATHER</b>\n─────────────────\n"
           f"<blockquote>{tg_escape(random.choice(WYR_QUESTIONS))}</blockquote>\n"
           f"<i>Reply with your choice and why!</i>\n─────────────────")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def endgame_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual override: /endgame force-ends the current chat game."""
    chat_id = update.message.chat_id
    if not chat_game_state(chat_id):
        await safe_reply(update, context, "<blockquote><i>No game is running in this chat right now.</i></blockquote>", parse_mode='HTML')
        return
    result = await end_active_game(chat_id)
    msg = (f"✅ <b>GAME ENDED</b>\n"
           f"─────────────────\n"
           f"<blockquote><i>{result}.</i>\n"
           f"Start a new game whenever you're ready!</blockquote>")
    await safe_reply(update, context, msg, parse_mode='HTML')

async def smart_trivia_scheduler(context: ContextTypes.DEFAULT_TYPE):
    """Fires every 60s. Sends trivia ONLY to chats that:
       (a) had a message within the last ACTIVITY_WINDOW seconds, AND
       (b) haven't received auto-trivia in the last 4-8 hours (randomized per chat).
       Never fires while another game is active in that chat."""
    now = time.time()
    for chat_id in list(active_chats):
        if now - chat_last_activity.get(chat_id, 0) > ACTIVITY_WINDOW:
            continue
        sched = trivia_schedule.get(chat_id)
        if sched is None:
            trivia_schedule[chat_id] = {"next_fire": now + random.randint(1800, 3600)}
            continue
        if now < sched["next_fire"]:
            continue
        if chat_id in active_games or chat_id in hangman_games or chat_id in wordle_games or chat_id in wordle_pending:
            sched["next_fire"] = now + 1800
            continue
        trivia = await fetch_live_trivia()
        if trivia:
            active_games[chat_id] = {"type": "trivia", "answer": trivia["a"]}
            auto_msg = (
                f"🧠 <b>TRIVIA TIME</b>\n"
                f"─────────────────\n"
                f"🏷️ <b><i>Category:</i></b> <i>{trivia['cat']}</i>\n"
                f"<blockquote><b>{trivia['q']}</b></blockquote>\n\n"
                f"<b>Options</b>\n<blockquote>{trivia['options']}</blockquote>\n"
                f"─────────────────\n"
                f"<i>Reply correctly for 1 point! Streak bonuses apply!</i>"
            )
            try: await context.bot.send_message(chat_id=chat_id, text=auto_msg, parse_mode='HTML')
            except Exception as e: logging.error(f"Smart trivia broadcast failed to {chat_id}: {e}")
        sched["next_fire"] = now + random.randint(TRIVIA_MIN_INTERVAL, TRIVIA_MAX_INTERVAL)

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.sticker: return
    chat_id = update.message.chat_id
    chat_type = update.message.chat.type
    user = update.message.from_user
    chat_last_activity[chat_id] = time.time()

    is_private = chat_type == 'private'
    is_reply_to_bot = bool(update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id)

    if is_private or is_reply_to_bot:
        if not clients:
            await context.bot.send_message(chat_id=chat_id, text="✨")
            return
        active_chats.add(chat_id)
        user_emoji = update.message.sticker.emoji or "✨"
        history = get_user_history(user.id)

        target_client = random.choice(clients)
        await send_ai_sticker(chat_id, context, target_client, f"User sent a sticker with this emoji: {user_emoji}", history)

MOD_WARN_LIMIT = 3
MOD_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

def parse_duration(args):
    """Parses e.g. '10m', '2h', '1d'. Returns (seconds, pretty) or (None, None)."""
    if not args: return None, None
    m = re.match(r'^(\d+)([smhdw])$', args[0].lower())
    if not m: return None, None
    secs = int(m.group(1)) * MOD_UNITS[m.group(2)]
    names = {"s": "second", "m": "minute", "h": "hour", "d": "day", "w": "week"}
    return secs, f"{m.group(1)} {names[m.group(2)]}{'s' if int(m.group(1)) != 1 else ''}"

async def _require_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message.chat.type == "private":
        await safe_reply(update, context, "<blockquote><i>This command only works in groups.</i> 🛡️</blockquote>", parse_mode='HTML')
        return False
    try:
        member = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
        if member.status not in ("administrator", "creator"):
            await safe_reply(update, context, "<blockquote><i>Only <b>group admins</b> can use this command.</i> 🛡️</blockquote>", parse_mode='HTML')
            return False
    except Exception:
        await safe_reply(update, context, "<blockquote><i>Couldn't verify your admin status.</i> 🛡️</blockquote>", parse_mode='HTML')
        return False
    return True

async def _resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Returns telegram User/Chat for reply-target, numeric ID, or @username string."""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user
    if context.args:
        arg = context.args[0]
        if arg.lstrip("-").isdigit():
            try:
                return await context.bot.get_chat(int(arg))
            except Exception:
                return None
        if arg.startswith("@"):
            return arg
    return None

async def _target_id(target, update: Update):
    """Extract numeric id from User/Chat or try username lookup via known scores."""
    if target is None: return None, "unknown"
    if isinstance(target, str):
        uname = target.lstrip("@").lower()
        chat_id_str = str(update.message.chat_id)
        for uid, udata in scores.get(chat_id_str, {}).items():
            if udata.get("name", "").lower() == uname:
                return int(uid), udata.get("name", uname)
        return None, target
    return target.id, (getattr(target, "first_name", None) or getattr(target, "title", None) or str(target.id))

def _mod_header(action: str) -> str:
    return f"🛡️ <b>{action}</b>\n─────────────────\n"

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    reason = " ".join(context.args[1:]) if (context.args and not update.message.reply_to_message) else (" ".join(context.args) if context.args else "")
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user or pass their ID: <code>/ban</code> (reply) or <code>/ban 123456 reason</code></i> 🛡️</blockquote>", parse_mode='HTML')
        return
    try:
        await context.bot.ban_chat_member(update.message.chat_id, tid)
        msg = _mod_header("USER BANNED") + f"<blockquote>⛔ <b>{tg_escape(tname)}</b> was <b>banned</b> by <b>{tg_escape(update.message.from_user.first_name)}</b>."
        if reason: msg += f"\n📝 <i>Reason: {tg_escape(reason)}</i>"
        msg += "</blockquote>"
        await safe_reply(update, context, msg, parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Ban failed:</i> <code>{tg_escape(str(e)[:100])}</code>\n<i>Make sure I'm an admin with ban rights.</i></blockquote>", parse_mode='HTML')

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user or pass their ID: <code>/unban 123456</code></i> 🛡️</blockquote>", parse_mode='HTML')
        return
    try:
        await context.bot.unban_chat_member(update.message.chat_id, tid, only_if_banned=True)
        await safe_reply(update, context, _mod_header("USER UNBANNED") + f"<blockquote>✅ <b>{tg_escape(tname)}</b> can rejoin the group now.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Unban failed:</i> <code>{tg_escape(str(e)[:100])}</code></blockquote>", parse_mode='HTML')

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user or pass their ID: <code>/kick</code> (reply)</i> 🛡️</blockquote>", parse_mode='HTML')
        return
    try:
        await context.bot.ban_chat_member(update.message.chat_id, tid)
        await context.bot.unban_chat_member(update.message.chat_id, tid)
        await safe_reply(update, context, _mod_header("USER KICKED") + f"<blockquote>👢 <b>{tg_escape(tname)}</b> was kicked. They can rejoin via invite.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Kick failed:</i> <code>{tg_escape(str(e)[:100])}</code></blockquote>", parse_mode='HTML')

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user or pass their ID: <code>/mute</code> (reply)</i> 🛡️</blockquote>", parse_mode='HTML')
        return
    try:
        await context.bot.restrict_chat_member(update.message.chat_id, tid, permissions=constants.ChatPermissions.no_permissions())
        await safe_reply(update, context, _mod_header("USER MUTED") + f"<blockquote>🔇 <b>{tg_escape(tname)}</b> can no longer send messages.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Mute failed:</i> <code>{tg_escape(str(e)[:100])}</code>\n<i>I need admin rights with restrict permission.</i></blockquote>", parse_mode='HTML')

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user or pass their ID: <code>/unmute</code> (reply)</i> 🛡️</blockquote>", parse_mode='HTML')
        return
    try:
        await context.bot.restrict_chat_member(update.message.chat_id, tid, permissions=constants.ChatPermissions.all_permissions())
        await safe_reply(update, context, _mod_header("USER UNMUTED") + f"<blockquote>🔊 <b>{tg_escape(tname)}</b> can talk again.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Unmute failed:</i> <code>{tg_escape(str(e)[:100])}</code></blockquote>", parse_mode='HTML')

async def tmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    dur_args = context.args if update.message.reply_to_message else context.args[1:]
    secs, pretty = parse_duration(dur_args)
    if tid is None or secs is None:
        await safe_reply(update, context, "<blockquote><i>Usage: reply + <code>/tmute 10m</code> or <code>/tmute @user 2h</code> — units: s m h d w</i> 🛡️</blockquote>", parse_mode='HTML')
        return
    try:
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=secs)
        await context.bot.restrict_chat_member(update.message.chat_id, tid, permissions=constants.ChatPermissions.no_permissions(), until_date=until)
        await safe_reply(update, context, _mod_header("TEMPORARY MUTE") + f"<blockquote>🔇 <b>{tg_escape(tname)}</b> is muted for <b>{pretty}</b>.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Temp-mute failed:</i> <code>{tg_escape(str(e)[:100])}</code></blockquote>", parse_mode='HTML')

async def tban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    dur_args = context.args if update.message.reply_to_message else context.args[1:]
    secs, pretty = parse_duration(dur_args)
    if tid is None or secs is None:
        await safe_reply(update, context, "<blockquote><i>Usage: reply + <code>/tban 1d</code> or <code>/tban @user 12h</code></i> 🛡️</blockquote>", parse_mode='HTML')
        return
    try:
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=secs)
        await context.bot.ban_chat_member(update.message.chat_id, tid, until_date=until)
        await safe_reply(update, context, _mod_header("TEMPORARY BAN") + f"<blockquote>⛔ <b>{tg_escape(tname)}</b> is banned for <b>{pretty}</b>.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Temp-ban failed:</i> <code>{tg_escape(str(e)[:100])}</code></blockquote>", parse_mode='HTML')

async def _get_warns(chat_id: int, user_id: int) -> int:
    return scores.get(str(chat_id), {}).get(str(user_id), {}).get("effects", {}).get("warns", 0)

async def _set_warns(chat_id: int, user_id: int, count: int):
    chat_id_str, user_id_str = str(chat_id), str(user_id)
    async with db_lock:
        if chat_id_str not in scores: scores[chat_id_str] = {}
        if user_id_str not in scores[chat_id_str]: scores[chat_id_str][user_id_str] = {"name": "User", "score": 0, "inventory": [], "effects": {}}
        scores[chat_id_str][user_id_str].setdefault("effects", {})["warns"] = count
        def _write():
            try:
                with tempfile.NamedTemporaryFile('w', delete=False) as tf:
                    json.dump(scores, tf, indent=4)
                    tempname = tf.name
                shutil.move(tempname, SCORES_FILE)
            except Exception as e:
                logging.error(f"Warn save error: {e}")
        await asyncio.to_thread(_write)

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    reason = " ".join(context.args[1:]) if (context.args and not update.message.reply_to_message) else (" ".join(context.args) if context.args else "")
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user or pass their ID: <code>/warn</code> (reply) <i>[reason]</i></i> 🛡️</blockquote>", parse_mode='HTML')
        return
    warns = await _get_warns(update.message.chat_id, tid) + 1
    await _set_warns(update.message.chat_id, tid, warns)
    if warns >= MOD_WARN_LIMIT:
        try:
            await context.bot.ban_chat_member(update.message.chat_id, tid)
            await _set_warns(update.message.chat_id, tid, 0)
            await safe_reply(update, context, _mod_header("AUTO-BAN") + f"<blockquote>⛔ <b>{tg_escape(tname)}</b> hit <b>{MOD_WARN_LIMIT} warns</b> and was automatically banned.</blockquote>", parse_mode='HTML')
            return
        except Exception:
            pass
    bar = "🟥" * warns + "⬜" * (MOD_WARN_LIMIT - warns)
    msg = _mod_header(f"WARNING {warns}/{MOD_WARN_LIMIT}") + f"<blockquote>⚠️ <b>{tg_escape(tname)}</b> {bar}"
    if reason: msg += f"\n📝 <i>Reason: {tg_escape(reason)}</i>"
    msg += f"\n<i>At {MOD_WARN_LIMIT} warns the user is auto-banned.</i></blockquote>"
    await safe_reply(update, context, msg, parse_mode='HTML')

async def warns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user: <code>/warns</code></i> 🛡️</blockquote>", parse_mode='HTML')
        return
    warns = await _get_warns(update.message.chat_id, tid)
    bar = "🟥" * warns + "⬜" * (MOD_WARN_LIMIT - warns)
    await safe_reply(update, context, _mod_header("WARN STATUS") + f"<blockquote>👤 <b>{tg_escape(tname)}</b> — {bar} <code>{warns}/{MOD_WARN_LIMIT}</code></blockquote>", parse_mode='HTML')

async def resetwarns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    target = await _resolve_target(update, context)
    tid, tname = await _target_id(target, update)
    if tid is None:
        await safe_reply(update, context, "<blockquote><i>Reply to a user: <code>/resetwarns</code></i> 🛡️</blockquote>", parse_mode='HTML')
        return
    await _set_warns(update.message.chat_id, tid, 0)
    await safe_reply(update, context, _mod_header("WARNS CLEARED") + f"<blockquote>🧹 <b>{tg_escape(tname)}</b>'s warnings were reset to zero.</blockquote>", parse_mode='HTML')

async def purge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    count = 100
    if context.args and context.args[0].isdigit():
        count = min(500, max(1, int(context.args[0])))
    start_id = update.message.reply_to_message.message_id if update.message.reply_to_message else update.message.message_id
    end_id = update.message.message_id
    deleted, failed = 0, 0
    status = await safe_reply(update, context, "<blockquote>🧹 <i>Purging messages...</i></blockquote>", parse_mode='HTML')
    for mid in range(start_id, end_id + 1):
        if deleted >= count: break
        try:
            await context.bot.delete_message(update.message.chat_id, mid)
            deleted += 1
            if deleted % 20 == 0: await asyncio.sleep(0.5)
        except Exception:
            failed += 1
    if status:
        try:
            await status.edit_text(_mod_header("PURGE COMPLETE") + f"<blockquote>🧹 Deleted <b>{deleted}</b> messages{f' · <i>{failed} skipped</i>' if failed else ''}.</blockquote>", parse_mode='HTML')
        except Exception:
            pass

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    if not update.message.reply_to_message:
        await safe_reply(update, context, "<blockquote><i>Reply to the message you want to pin with <code>/pin</code>.</i> 📌</blockquote>", parse_mode='HTML')
        return
    try:
        await context.bot.pin_chat_message(update.message.chat_id, update.message.reply_to_message.message_id, disable_notification=True)
        await safe_reply(update, context, _mod_header("MESSAGE PINNED") + "<blockquote>📌 Done — it's pinned to the top.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Pin failed:</i> <code>{tg_escape(str(e)[:100])}</code>\n<i>I need pin permissions.</i></blockquote>", parse_mode='HTML')

async def unpin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_group_admin(update, context): return
    try:
        if update.message.reply_to_message:
            await context.bot.unpin_chat_message(update.message.chat_id, update.message.reply_to_message.message_id)
        else:
            await context.bot.unpin_chat_message(update.message.chat_id)
        await safe_reply(update, context, _mod_header("MESSAGE UNPINNED") + "<blockquote>📌 Done — unpinned.</blockquote>", parse_mode='HTML')
    except Exception as e:
        await safe_reply(update, context, f"<blockquote><i>Unpin failed:</i> <code>{tg_escape(str(e)[:100])}</code></blockquote>", parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_type, text, chat_id, user = update.message.chat.type, update.message.text, update.message.chat_id, update.message.from_user
    if chat_type in ['group', 'supergroup']: active_chats.add(chat_id)

    chat_last_activity[chat_id] = time.time()
    text_clean = text.strip()

    if chat_type in ['group', 'supergroup']:
        bot_username = context.bot.username
        if not text_clean.startswith("/") and f"@{bot_username}" not in text:
            add_to_chat_buffer(chat_id, user.first_name, text_clean[:200])

    if chat_id in hangman_games:
        if await handle_hangman_guess(update, context, chat_id, text_clean):
            return

    if chat_id in wordle_games:
        if await handle_wordle_guess(update, context, chat_id, text_clean):
            return

    if chat_id in active_games:
        if await handle_game_answer(update, context, chat_id, text_clean):
            return

    if chat_type in ['group', 'supergroup']:
        bot_username = context.bot.username
        mentioned = f"@{bot_username}" in text
        is_reply = (update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id)
        if not (mentioned or is_reply or "myra" in text.lower()): return
        text = text.replace(f"@{bot_username}", "").strip()

    sender_prefix = f"[SENDER: {user.first_name}]"
    base_history = get_user_history(user.id)

    img_prompt = _maybe_image_request(text_clean if chat_type == 'private' else text.replace(f"@{context.bot.username}", "").strip())
    if img_prompt and not img_prompt.lower().startswith(("http://", "https://")):
        status_img = await safe_reply(update, context,
            f"<blockquote>🎨 <i>Dreaming up</i> <b>{tg_escape(img_prompt[:70])}</b>...</blockquote>", parse_mode='HTML')
        gen = await generate_ai_image(img_prompt, 1024, 1024)
        if gen:
            try:
                await update.message.reply_photo(photo=_ioutil.BytesIO(gen),
                    caption=f"🎨 <b>IMAGINE</b>\n<blockquote><i>{tg_escape(img_prompt[:300])}</i></blockquote>",
                    parse_mode='HTML')
                if status_img:
                    try: await status_img.delete()
                    except Exception: pass
                return
            except Exception as e:
                logging.error(f"auto-image send failed: {e}")
        if status_img:
            try: await status_img.edit_text("<blockquote><i>⚠️ Couldn't generate that image — try /imagine.</i></blockquote>", parse_mode='HTML')
            except Exception: pass
        return

    explicit_sticker_request = any(kw in text.lower() for kw in ["sticker", "stkr", "send sticker", "sticker de", "sticker send", "send me a sticker"])

    if explicit_sticker_request:
        if not clients:
            await safe_reply(update, context, "✨")
            return
        target_client = random.choice(clients)
        await send_ai_sticker(chat_id, context, target_client, f"User explicitly asked for a sticker saying: '{text}'", base_history)
        return

    if not clients:
        await safe_reply(update, context, "<blockquote><i>my brain isn't connected rn... try again later?</i></blockquote>", parse_mode='HTML')
        return

    try:
        status_msg = await safe_reply(update, context, "<blockquote><i>Thinking...</i></blockquote>", parse_mode='HTML')

        target_client = random.choice(clients)
        intention_analysis = await analyze_intention(base_history, text, target_client)

        async def ui_callback(new_text):
            if status_msg:
                try: await status_msg.edit_text(new_text, parse_mode='HTML')
                except Exception: pass

        user_eff = scores.get(str(chat_id), {}).get(str(user.id), {}).get("effects", {})
        is_vip = user_eff.get("vip_until", 0) > time.time()

        if is_vip:
            intention_system = f"--- INTENT ANALYSIS ---\n{intention_analysis}\n\nCRITICAL DIRECTIVE: User {user.first_name} is a VIP Admin! Fulfill their requests directly with absolute loyalty."
        else:
            intention_system = f"--- INTENT ANALYSIS ---\n{intention_analysis}\n\nUse this intent analysis to guide your empathy, exact search behavior, and overall response strategy."

        group_context_block = ""
        if chat_type in ['group', 'supergroup']:
            chat_context = get_chat_context_block(chat_id)
            group_context_block = (
                f"\n\n--- GROUP CHAT CONTEXT (recent messages from all members) ---\n"
                f"{chat_context}\n"
                f"--- END GROUP CONTEXT ---\n"
                f"Use this to understand what the group is currently discussing. "
                f"If the user's message refers to something from the recent conversation, answer using that context."
            )

        request_payload = base_history + [
            {"role": "system", "content": intention_system + group_context_block},
            {"role": "user", "content": f"{sender_prefix}: {text}"}
        ]

        bot_reply = await generate_response_with_failover(request_payload, status_callback=ui_callback)

        base_history.append({"role": "user", "content": f"{sender_prefix}: {text}"})
        base_history.append({"role": "assistant", "content": bot_reply})
        if len(base_history) > 6: base_history = [base_history[0]] + base_history[-5:]
        user_sessions[user.id] = base_history

        clean_reply = sanitize_telegram_html(bot_reply)

        if status_msg:
            try: await status_msg.edit_text(clean_reply[:4000], parse_mode='HTML')
            except Exception: await status_msg.edit_text(re.sub(r'<[^>]+>', '', clean_reply)[:4000])
        else:
            await safe_reply(update, context, clean_reply[:4000], parse_mode='HTML')

    except Exception as e:
        logging.error(f"Message handling error: {e}")
        error_msg = "<blockquote><i>Something broke on my end - try again in a moment.</i></blockquote>"
        if 'status_msg' in locals() and status_msg:
            try: await status_msg.edit_text(error_msg, parse_mode='HTML')
            except Exception: pass
        else:
            await safe_reply(update, context, error_msg, parse_mode='HTML')

import io as _ioutil

AIHORDE_BASE = "https://aihorde.org/api/v2"
AIHORDE_ANON_KEY = "0000000000"
AIHORDE_AGENT = "MyraBot:1.0:free-telegram-assistant"
POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/"

async def generate_ai_image(prompt: str, width: int = 1024, height: int = 1024,
                            model: str | None = None, seed: int | None = None) -> bytes | None:
    """Generate an image from a text prompt. Primary: AI Horde (keyless SD).
    Falls back to Pollinations. Returns raw image bytes or None."""
    if not prompt or not prompt.strip():
        return None
    data = await _aihorde_generate(prompt, width, height, seed)
    if data:
        return data
    logging.info("AI Horde unavailable for this prompt - trying Pollinations fallback")
    return await _pollinations_generate(prompt, width, height, model, seed)

def _sd_size(value: int) -> int:
    """Clamp to an SD-friendly size (multiple of 64, within 256-1024)."""
    v = max(256, min(1024, int(value)))
    return (v // 64) * 64

async def _aihorde_generate(prompt: str, width: int, height: int, seed: int | None,
                            timeout: int = 90) -> bytes | None:
    """Submit an anonymous AI Horde job, poll for completion, download the image."""
    params = {
        "width": _sd_size(width),
        "height": _sd_size(height),
        "steps": 28,
        "cfg_scale": 7.0,
        "sampler_name": "k_euler_a",
        "n": 1,
        "post_processing": ["GFPGAN"],
    }
    if seed is not None:
        params["seed"] = str(int(seed))
    payload = {
        "prompt": prompt[:1800],
        "params": params,
        "nsfw": False,
        "censor_nsfw": True,
        "r2": True,
    }
    base_headers = {
        'apikey': AIHORDE_ANON_KEY,
        'Client-Agent': AIHORDE_AGENT,
        'Content-Type': 'application/json',
    }

    def _submit_and_wait():

        req = urllib.request.Request(
            f"{AIHORDE_BASE}/generate/async",
            data=json.dumps(payload).encode('utf-8'),
            headers=base_headers, method='POST')
        with urllib.request.urlopen(req, timeout=25) as r:
            job = json.loads(r.read().decode())
        jid = job.get('id')
        if not jid:
            return None

        deadline = time.time() + timeout
        poll_headers = {'apikey': AIHORDE_ANON_KEY, 'Client-Agent': AIHORDE_AGENT}
        while time.time() < deadline:
            time.sleep(3)
            sreq = urllib.request.Request(
                f"{AIHORDE_BASE}/generate/status/{jid}", headers=poll_headers)
            with urllib.request.urlopen(sreq, timeout=20) as r:
                status = json.loads(r.read().decode())
            if status.get('done'):
                gens = status.get('generations') or []
                if gens and gens[0].get('img'):
                    ireq = urllib.request.Request(
                        gens[0]['img'], headers={'User-Agent': random.choice(USER_AGENTS)})
                    with urllib.request.urlopen(ireq, timeout=30) as ir:
                        return ir.read()
                return None
        return None

    try:
        data = await asyncio.to_thread(_submit_and_wait)
        if data and len(data) > 1000 and data[:3] in (b'\xff\xd8\xff', b'\x89PN', b'RIFF'):
            return data
        logging.warning(f"AI Horde returned tiny/invalid payload ({len(data or b'')} bytes)")
        return None
    except Exception as e:
        logging.warning(f"AI Horde image gen failed: {e}")
        return None

async def _pollinations_generate(prompt: str, width: int, height: int,
                                 model: str | None = None, seed: int | None = None) -> bytes | None:
    """Legacy free fallback via Pollinations (used only if AI Horde is unavailable)."""
    if seed is None:
        seed = random.randint(1, 2_147_483_647)
    model = model or "flux"
    safe = urllib.parse.quote(prompt.strip()[:900])
    url = (f"{POLLINATIONS_BASE}{safe}?width={int(width)}&height={int(height)}"
           f"&seed={int(seed)}&nologo=true&model={urllib.parse.quote(model)}")
    req = urllib.request.Request(url, headers={'User-Agent': random.choice(USER_AGENTS)})

    def _fetch():
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    try:
        data = await asyncio.to_thread(_fetch)
        if data and len(data) > 800 and (data[:3] in (b'\xff\xd8\xff', b'\x89PN') or len(data) > 2000):
            return data
        logging.warning(f"Pollinations returned tiny/invalid payload ({len(data or b'')} bytes)")
        return None
    except Exception as e:
        logging.error(f"Pollinations image generation failed: {e}")
        return None

async def imagine_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context,
            "<blockquote><i>🎨 Usage: <code>/imagine a cyberpunk cat hacker</code></i>\n"
            "<i>Free AI art — no key, no limits. Also try <code>/wallpaper</code>.</i></blockquote>",
            parse_mode='HTML')
        return
    prompt = " ".join(context.args).strip()
    status = await safe_reply(update, context,
        f"<blockquote>🎨 <i>Dreaming up:</i> <b>{tg_escape(prompt[:80])}</b>...</blockquote>", parse_mode='HTML')
    img = await generate_ai_image(prompt, 1024, 1024)
    if not img:
        if status:
            try: await status.edit_text("<blockquote><i>⚠️ The dream-machine stalled. Try again in a sec!</i></blockquote>", parse_mode='HTML')
            except Exception: pass
        return
    try:
        await update.message.reply_photo(
            photo=_ioutil.BytesIO(img),
            caption=f"🎨 <b>IMAGINE</b>\n─────────────────\n<blockquote><i>{tg_escape(prompt[:300])}</i></blockquote>\n─────────────────\n<i>via AI Horde · free &amp; keyless</i>",
            parse_mode='HTML')
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"imagine send failed: {e}")
        if status:
            try: await status.edit_text("<blockquote><i>Made it but couldn't send it. Try a shorter prompt.</i></blockquote>", parse_mode='HTML')
            except Exception: pass

async def wallpaper_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    theme = " ".join(context.args).strip() if context.args else "breathtaking scenic landscape, 8k, ultra detailed"
    prompt = f"{theme}, wallpaper, cinematic lighting, ultra high detail, vibrant"
    status = await safe_reply(update, context, "<blockquote>🖼️ <i>Rendering wallpaper...</i></blockquote>", parse_mode='HTML')
    img = await generate_ai_image(prompt, 1280, 720)
    if not img:
        if status:
            try: await status.edit_text("<blockquote><i>⚠️ Wallpaper engine stalled. Try again!</i></blockquote>", parse_mode='HTML')
            except Exception: pass
        return
    try:
        await update.message.reply_photo(photo=_ioutil.BytesIO(img),
            caption=f"🖼️ <b>WALLPAPER</b>\n<blockquote><i>{tg_escape(theme[:200])}</i></blockquote>", parse_mode='HTML')
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception:
        pass

def _maybe_image_request(text: str) -> str | None:
    """Detect an explicit image-generation request in normal chat. Returns prompt or None."""
    t = text.strip()
    patterns = [
        r"^(?:hey\s+)?(?:myra\s+)?(?:please\s+)?(?:imagine|picture|image)\s+(?:of\s+)?(.+)$",
        r"^(?:hey\s+)?(?:myra\s+)?(?:please\s+)?(?:draw|render|generate|paint|create)\s+(?:an?\s+|me\s+)?(?:image|picture|art|photo)?\s*(?:of\s+)?(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, t, flags=re.IGNORECASE)
        if m and m.group(1) and len(m.group(1).split()) >= 2:
            return m.group(1).strip()
    return None

from telegram import InputSticker

def _pack_name(uid: int, bot_username: str) -> str:
    return f"myraown{int(uid)}_by_{bot_username}".lower()[:64]

async def _create_or_add_sticker(bot, owner_uid: int, bot_username: str,
                                 file_bytes: bytes, fmt: str, emojis: list):
    """Add file_bytes to the user's personal pack, creating it if needed."""
    pack = _pack_name(owner_uid, bot_username)
    buf = _ioutil.BytesIO(file_bytes)
    buf.name = "sticker.webp" if fmt == "static" else ("sticker.tgs" if fmt == "animated" else "sticker.webm")
    inp = InputSticker(sticker=buf, emoji_list=(emojis or ["✨"])[:20], format=fmt)
    try:
        await bot.add_sticker_to_set(user_id=int(owner_uid), name=pack, sticker=inp)
        return pack, False
    except Exception as e:
        low = str(e).lower()
        if any(k in low for k in ("invalid", "not found", "stickerset_invalid")):
            title = "Myra Own Pack"
            await bot.create_new_sticker_set(user_id=int(owner_uid), name=pack, title=title,
                                             stickers=[inp], sticker_type="regular")
            return pack, True
        raise

async def _bytes_from_sticker(bot, st) -> tuple:
    """Download an incoming Sticker object -> (bytes, format)."""
    f = await bot.get_file(st.file_id)
    raw = bytes(await f.download_as_bytearray())
    if st.is_animated:
        return raw, "animated"
    if st.is_video:
        return raw, "video"
    return raw, "static"

async def own_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply to any sticker (including a /q quote) with /own -> save to your pack."""
    reply = update.message.reply_to_message
    if not reply or not reply.sticker:
        await safe_reply(update, context,
            "<blockquote><i>Reply to any sticker (or a <b>/q</b> quote sticker) with <code>/own</code> to save it into your personal Myra pack.</i> 🎒</blockquote>",
            parse_mode='HTML')
        return
    st = reply.sticker
    user = update.message.from_user
    bot_username = (await context.bot.get_me()).username
    status = await safe_reply(update, context, "<blockquote>🎒 <i>Saving to your pack...</i></blockquote>", parse_mode='HTML')
    try:
        raw, fmt = await _bytes_from_sticker(context.bot, st)
        emojis = list(st.emoji) if st.emoji else ["✨"]
        pack, created = await _create_or_add_sticker(context.bot, user.id, bot_username, raw, fmt, emojis)
        link = f"https://t.me/addstickers/{pack}"
        head = "🆕 Pack created!" if created else "✅ Added to your pack!"
        await safe_reply(update, context,
            f"<blockquote>{head}</blockquote>\n🔗 <a href=\"{link}\">{tg_escape(pack)}</a>",
            parse_mode='HTML', disable_web_page_preview=True)
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/own failed: {e}")
        err = f"<blockquote><i>Couldn't save:</i> <code>{tg_escape(str(e)[:120])}</code></blockquote>"
        if status:
            try: await status.edit_text(err, parse_mode='HTML')
            except Exception: pass
        else:
            await safe_reply(update, context, err, parse_mode='HTML')

async def mypack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the user's personal sticker pack link."""
    bot_username = (await context.bot.get_me()).username
    pack = _pack_name(update.message.from_user.id, bot_username)
    await safe_reply(update, context,
        f"🎒 <b>YOUR MYRA PACK</b>\n─────────────────\n"
        f"<blockquote><i>Save stickers with <code>/own</code> (reply to a sticker), then browse:</i></blockquote>\n"
        f"🔗 <a href=\"https://t.me/addstickers/{pack}\">{tg_escape(pack)}</a>",
        parse_mode='HTML', disable_web_page_preview=True)

LAST_QUOTE_WEBP = {}

async def own_q_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        chat_id = int(query.data.split("_", 2)[1])
    except Exception:
        await query.answer("Expired.", show_alert=True)
        return
    webp = LAST_QUOTE_WEBP.get(chat_id)
    user = query.from_user
    if not webp:
        await query.answer("Quote expired — reply to the sticker with /own instead.", show_alert=True)
        return
    bot_username = (await context.bot.get_me()).username
    try:
        pack, created = await _create_or_add_sticker(context.bot, user.id, bot_username,
                                                     webp, "static", ["✨"])
        await query.answer("🆕 Pack created & quote saved!" if created else "✅ Quote saved to your pack!",
                           show_alert=True)
        try:
            await context.bot.send_message(
                query.message.chat_id,
                f"🎒 <a href=\"https://t.me/addstickers/{pack}\">{tg_escape(pack)}</a>",
                parse_mode='HTML', disable_web_page_preview=True)
        except Exception:
            pass
    except Exception as e:
        logging.error(f"/q save button failed: {e}")
        await query.answer(f"Failed: {str(e)[:80]}", show_alert=True)

def _render_profile_card(name: str, handle: str, uid, bio: str, avatar_img=None,
                         extra_lines=None) -> bytes:
    from PIL import Image, ImageDraw
    W, H = 800, 420
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, W - 8, H - 8], radius=40, fill=(28, 28, 46, 250))
    draw.rounded_rectangle([12, 12, W - 12, H - 12], radius=36, outline=(139, 92, 246, 160), width=2)

    band = Image.new("RGBA", (W - 16, 96), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for i in range(band.height):
        t = i / band.height
        bd.line([(0, i), (band.width, i)],
                fill=(int(139 + (70 - 139) * t), int(92 + (40 - 92) * t),
                      int(246 + (180 - 246) * t), 255), width=1)
    mask = Image.new("L", band.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, band.width, band.height], radius=36, fill=255)
    img.paste(band, (8, 8), mask)

    ax, ay, ar = 120, 130, 72
    drew_avatar = False
    if avatar_img is not None:
        try:
            av = avatar_img.convert("RGBA").resize((ar * 2, ar * 2))
            avm = Image.new("L", (ar * 2, ar * 2), 0)
            ImageDraw.Draw(avm).ellipse([0, 0, ar * 2, ar * 2], fill=255)
            img.paste(av, (ax - ar, ay - ar), avm)
            draw.ellipse([ax - ar - 3, ay - ar - 3, ax + ar + 3, ay + ar + 3],
                         outline=(255, 255, 255, 235), width=4)
            drew_avatar = True
        except Exception:
            pass
    if not drew_avatar:
        initials = "".join(w[0] for w in (name or "?").split()[:2]).upper() or "?"
        draw.ellipse([ax - ar, ay - ar, ax + ar, ay + ar], fill=(139, 92, 246, 255))
        f_init = _get_font(44, bold=True)
        tw = draw.textbbox((0, 0), initials, font=f_init)[2]
        draw.text((ax - tw / 2, ay - 26), initials, font=f_init, fill=(255, 255, 255, 255))

    tx = ax + ar + 34
    f_name = _get_font(34, bold=True)
    draw.text((tx, 88), (name or "Unknown")[:26], font=f_name, fill=(255, 255, 255, 255))
    f_sub = _get_font(22)
    if handle:
        draw.text((tx, 132), handle[:30], font=f_sub, fill=(200, 178, 255, 255))
    f_id = _get_font(20)
    if uid is not None:
        draw.text((tx, 164), f"ID: {uid}", font=f_id, fill=(150, 150, 170, 255))

    draw.line([(40, 250), (W - 40, 250)], fill=(255, 255, 255, 40), width=2)

    f_bio = _get_font(21)
    ty = 266
    if bio:
        for ln in _wrap_text_px(draw, bio, f_bio, W - 90)[:3]:
            draw.text((44, ty), ln, font=f_bio, fill=(226, 226, 240, 255))
            ty += 28
    else:
        draw.text((44, ty), "No bio available.", font=f_bio, fill=(150, 150, 170, 255))
        ty += 28

    if extra_lines:
        f_ex = _get_font(19)
        for ln in extra_lines[:2]:
            draw.text((44, ty), str(ln)[:70], font=f_ex, fill=(170, 170, 195, 255))
            ty += 24

    f_sig = _get_font(16)
    draw.text((W - 210, H - 40), "· via Myra", font=f_sig, fill=(150, 150, 170, 180))
    buf = _ioutil.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

async def pf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """beem-style: send a rendered profile-card IMAGE of a Telegram account."""
    status = await safe_reply(update, context,
        "<blockquote>🖼️ <i>Building profile card...</i></blockquote>", parse_mode='HTML')
    target_user = None
    target_id = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_id = target_user.id
    elif context.args and context.args[0].lstrip("-").isdigit():
        target_id = int(context.args[0])
    elif context.args:
        try:
            chat_obj = await context.bot.get_chat(context.args[0].replace("@", ""))
            target_id = chat_obj.id
            target_user = chat_obj
        except Exception:
            target_user = update.message.from_user
            target_id = target_user.id
    else:
        target_user = update.message.from_user
        target_id = target_user.id

    try:
        if target_user is None:
            try:
                target_user = await context.bot.get_chat(target_id)
            except Exception:
                target_user = None
        name = (getattr(target_user, "first_name", None)
                or getattr(target_user, "full_name", None) or "Unknown")
        uname = getattr(target_user, "username", None)
        handle = f"@{uname}" if uname else "no username"
        bio = "No bio available."
        try:
            c = await context.bot.get_chat(target_id)
            bio = c.bio or "No bio available."
        except Exception:
            pass
        avatar = await _fetch_avatar(context.bot, target_id)
        card = await asyncio.to_thread(_render_profile_card, name, handle, target_id, bio, avatar, None)
        caption = (f"🪪 <b>PROFILE CARD</b>\n─────────────────\n"
                   f"<blockquote><i>{tg_escape(name)} · {tg_escape(handle)}</i></blockquote>")
        await update.message.reply_photo(photo=_ioutil.BytesIO(card), caption=caption, parse_mode='HTML')
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/pf failed: {e}")
        if status:
            try: await status.edit_text("<blockquote><i>Couldn't build the card.</i></blockquote>", parse_mode='HTML')
            except Exception: pass

def _fget_json(url, headers=None, timeout=12, method="GET", data=None):
    h = {'User-Agent': random.choice(USER_AGENTS)}
    if headers: h.update(headers)
    body = data.encode() if isinstance(data, str) else data
    last_err = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=body, headers=h, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last_err = e
            if attempt == 0:
                time.sleep(0.6)
                continue
            raise last_err

WMO = {0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Fog",48:"Rime fog",
       51:"Light drizzle",53:"Drizzle",55:"Heavy drizzle",61:"Light rain",63:"Rain",
       65:"Heavy rain",66:"Freezing rain",67:"Freezing rain",71:"Light snow",73:"Snow",
       75:"Heavy snow",77:"Snow grains",80:"Rain showers",81:"Rain showers",82:"Violent showers",
       85:"Snow showers",86:"Snow showers",95:"Thunderstorm",96:"Thunderstorm + hail",99:"Thunderstorm + hail"}

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context, "<blockquote><i>Usage: <code>/weather Delhi</code></i> 🌦️</blockquote>", parse_mode='HTML')
        return
    city = " ".join(context.args)
    status = await safe_reply(update, context, f"<blockquote>🌦️ <i>Weather for</i> <b>{tg_escape(city)}</b>...</blockquote>", parse_mode='HTML')
    def _work():
        geo = _fget_json(f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=en")
        res = geo.get("results") or []
        if not res: return None
        g = res[0]
        w = _fget_json(f"https://api.open-meteo.com/v1/forecast?latitude={g['latitude']}&longitude={g['longitude']}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min&timezone=auto&forecast_days=1")
        return g, w
    try:
        out = await asyncio.to_thread(_work)
        if not out:
            await status.edit_text("<blockquote><i>Couldn't find that city!</i></blockquote>", parse_mode='HTML')
            return
        g, w = out
        cur = w.get("current", {})
        day = (w.get("daily") or {})
        desc = WMO.get(cur.get("weather_code", -1), "Unknown")
        hi = (day.get("temperature_2m_max") or [None])[0]
        lo = (day.get("temperature_2m_min") or [None])[0]
        msg = (f"🌦️ <b>WEATHER · {tg_escape(g.get('name', city))}</b>\n─────────────────\n"
               f"<blockquote>🌡️ <b>{cur.get('temperature_2m')}°C</b> (feels {cur.get('apparent_temperature')}°C)\n"
               f"☁️ <i>{desc}</i>\n💧 Humidity: {cur.get('relative_humidity_2m')}%\n"
               f"💨 Wind: {cur.get('wind_speed_10m')} km/h"
               + (f"\n🔺 Hi {hi}° / 🔻 Lo {lo}°" if hi is not None else "")
               + "</blockquote>\n─────────────────")
        await status.edit_text(msg, parse_mode='HTML')
    except Exception as e:
        logging.error(f"/weather failed: {e}")
        await status.edit_text("<blockquote><i>Weather service hiccup — try again.</i></blockquote>", parse_mode='HTML')

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await safe_reply(update, context,
            "<blockquote><i>Usage: <code>/translate es hello world</code></i> 🌐<br/><i>First arg = target language code (es, fr, hi, ja...).</i></blockquote>",
            parse_mode='HTML')
        return
    lang = context.args[0].lower()
    text = " ".join(context.args[1:])
    status = await safe_reply(update, context, "<blockquote>🌐 <i>Translating...</i></blockquote>", parse_mode='HTML')
    def _work():
        url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto"
               f"&tl={urllib.parse.quote(lang)}&dt=t&q={urllib.parse.quote(text[:1500])}")
        d = _fget_json(url)
        return "".join(seg[0] for seg in d[0] if seg and seg[0])
    try:
        out = await asyncio.to_thread(_work)
        msg = (f"🌐 <b>TRANSLATE</b> <i>(→ {tg_escape(lang)})</i>\n─────────────────\n"
               f"<blockquote>🔸 <i>{tg_escape(text[:400])}</i>\n\n🔸 <b>{tg_escape(out[:600])}</b></blockquote>")
        await status.edit_text(msg, parse_mode='HTML')
    except Exception as e:
        logging.error(f"/translate failed: {e}")
        await status.edit_text("<blockquote><i>Translation failed — try different text.</i></blockquote>", parse_mode='HTML')

async def define_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context, "<blockquote><i>Usage: <code>/define resilience</code></i> 📖</blockquote>", parse_mode='HTML')
        return
    word = " ".join(context.args)
    status = await safe_reply(update, context, "<blockquote>📖 <i>Looking up...</i></blockquote>", parse_mode='HTML')
    def _work():
        return _fget_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word.lower())}")
    try:
        data = await asyncio.to_thread(_work)
        entry = data[0]
        phon = entry.get("phonetic") or (entry.get("phonetics") or [{}])[0].get("text", "")
        lines = []
        for m in (entry.get("meanings") or [])[:2]:
            pos = m.get("pos", "")
            for d in (m.get("definitions") or [])[:2]:
                lines.append(f"▸ <b>{tg_escape(pos)}</b> <i>{tg_escape(d.get('definition',''))}</i>")
                if d.get("example"):
                    lines.append(f"  <i>“{tg_escape(d['example'][:150])}”</i>")
        body = "\n".join(lines[:6]) if lines else "<i>No definitions found.</i>"
        msg = (f"📖 <b>{tg_escape(word.upper())}</b> {tg_escape(phon)}\n─────────────────\n"
               f"<blockquote>{body}</blockquote>")
        await status.edit_text(msg, parse_mode='HTML')
    except Exception as e:
        logging.error(f"/define failed: {e}")
        await status.edit_text("<blockquote><i>No definition found for that word.</i></blockquote>", parse_mode='HTML')

async def github_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context, "<blockquote><i>Usage: <code>/github torvalds</code></i> 🐙</blockquote>", parse_mode='HTML')
        return
    uname = context.args[0].replace("@", "")
    status = await safe_reply(update, context, "<blockquote>🐙 <i>Fetching GitHub profile...</i></blockquote>", parse_mode='HTML')
    def _work():
        return _fget_json(f"https://api.github.com/users/{urllib.parse.quote(uname)}",
                          headers={"Accept": "application/vnd.github+json"})
    try:
        d = await asyncio.to_thread(_work)
        pinned = f"{d.get('public_repos',0)} repos · {d.get('followers',0)} followers · {d.get('following',0)} following"
        msg = (f"🐙 <b>GITHUB · {tg_escape(d.get('name') or d.get('login'))}</b>\n─────────────────\n"
               f"<blockquote>🆔 <code>{tg_escape(str(d.get('login')))}</code>\n"
               f"👥 {tg_escape(pinned)}\n"
               f"⭐ {d.get('public_gists',0)} gists\n"
               f"🏢 {tg_escape(d.get('company') or '—')}\n"
               f"📍 {tg_escape(d.get('location') or '—')}\n"
               f"🧩 {tg_escape((d.get('bio') or '—')[:150])}</blockquote>\n"
               f"🔗 <a href=\"{d.get('html_url')}\">View profile</a>")
        await status.edit_text(msg, parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"/github failed: {e}")
        await status.edit_text("<blockquote><i>GitHub user not found.</i></blockquote>", parse_mode='HTML')

async def meme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await safe_reply(update, context, "<blockquote>😂 <i>Fresh meme incoming...</i></blockquote>", parse_mode='HTML')
    def _work():
        return _fget_json("https://meme-api.com/gimme")
    try:
        d = await asyncio.to_thread(_work)
        await update.message.reply_photo(photo=d.get("url"),
            caption=f"😂 <b>{tg_escape((d.get('title') or 'Meme')[:200])}</b>\n<i>r/{tg_escape(d.get('subreddit','memes'))}</i>",
            parse_mode='HTML')
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/meme failed: {e}")
        if status:
            try: await status.edit_text("<blockquote><i>No memes right now — try again!</i></blockquote>", parse_mode='HTML')
            except Exception: pass

def _make_qr(text: str) -> bytes:
    import qrcode as _qr
    qr = _qr.QRCode(error_correction=_qr.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(text[:2000])
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = _ioutil.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context, "<blockquote><i>Usage: <code>/qr https://t.me/yourchannel</code></i> 📱</blockquote>", parse_mode='HTML')
        return
    text = " ".join(context.args)
    status = await safe_reply(update, context, "<blockquote>📱 <i>Generating QR...</i></blockquote>", parse_mode='HTML')
    try:
        buf = _ioutil.BytesIO(await asyncio.to_thread(_make_qr, text))
        await update.message.reply_photo(photo=buf,
            caption=f"📱 <b>QR CODE</b>\n<blockquote><i>{tg_escape(text[:200])}</i></blockquote>", parse_mode='HTML')
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/qr failed: {e}")
        if status:
            try: await status.edit_text("<blockquote><i>QR generation failed.</i></blockquote>", parse_mode='HTML')
            except Exception: pass

def _safe_eval(expr: str):
    import ast, operator as _op
    ops = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul, ast.Div: _op.truediv,
           ast.Pow: _op.pow, ast.Mod: _op.mod, ast.FloorDiv: _op.floordiv, ast.USub: _op.neg, ast.UAdd: _op.pos}
    def ev(node):
        if isinstance(node, ast.Expression): return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)): return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops: return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops: return ops[type(node.op)](ev(node.operand))
        raise ValueError("Unsupported expression")
    return ev(ast.parse(expr, mode="eval"))

async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await safe_reply(update, context, "<blockquote><i>Usage: <code>/calc 12*(4+3)</code></i> 🧮</blockquote>", parse_mode='HTML')
        return
    expr = "".join(context.args)
    try:
        res = await asyncio.to_thread(_safe_eval, expr)
        if isinstance(res, float) and res.is_integer(): res = int(res)
        msg = (f"🧮 <b>CALCULATOR</b>\n─────────────────\n"
               f"<blockquote><code>{tg_escape(expr)}</code>\n<b>= {res}</b></blockquote>")
        await safe_reply(update, context, msg, parse_mode='HTML')
    except Exception:
        await safe_reply(update, context, "<blockquote><i>Invalid math expression!</i></blockquote>", parse_mode='HTML')

async def simage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply to a photo/image with /simage -> turn it into a static sticker."""
    reply = update.message.reply_to_message
    if not reply or not (reply.photo or (reply.document and (reply.document.mime_type or "").startswith("image/"))):
        await safe_reply(update, context, "<blockquote><i>Reply to a photo/image with <code>/simage</code> to turn it into a sticker.</i> ✂️</blockquote>", parse_mode='HTML')
        return
    status = await safe_reply(update, context, "<blockquote>✂️ <i>Cutting out your sticker...</i></blockquote>", parse_mode='HTML')
    try:
        from PIL import Image as _PILImage
        tg_file = reply.photo[-1] if reply.photo else reply.document
        f = await context.bot.get_file(tg_file.file_id)
        raw = bytes(await f.download_as_bytearray())
        im = _PILImage.open(_ioutil.BytesIO(raw)).convert("RGBA")
        im.thumbnail((512, 512))
        canvas = _PILImage.new("RGBA", (512, 512), (0, 0, 0, 0))
        canvas.paste(im, ((512 - im.width)//2, (512 - im.height)//2), im)
        out = _ioutil.BytesIO()
        canvas.save(out, format="WEBP")
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=_ioutil.BytesIO(out.getvalue()))
        if status:
            try: await status.delete()
            except Exception: pass
    except Exception as e:
        logging.error(f"/simage failed: {e}")
        if status:
            try: await status.edit_text("<blockquote><i>Couldn't convert that image.</i></blockquote>", parse_mode='HTML')
            except Exception: pass

def main():

    if sys.platform.startswith('win'): asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = Application.builder().token(TELEGRAM_TOKEN).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CommandHandler("game", game_command))
    app.add_handler(CommandHandler("scramble", scramble_command))
    app.add_handler(CommandHandler("roulette", roulette_command))
    app.add_handler(CommandHandler("flip", flip_command))
    app.add_handler(CommandHandler("ttt", ttt_command))
    app.add_handler(CommandHandler("mine", mine_command))
    app.add_handler(CommandHandler("mines", mine_command))
    app.add_handler(CommandHandler("speedy", speedy_command))
    app.add_handler(CommandHandler("guess", guess_command))
    app.add_handler(CommandHandler("mathquiz", mathquiz_command))
    app.add_handler(CommandHandler("flag", flag_command))
    app.add_handler(CommandHandler("hangman", hangman_command))
    app.add_handler(CommandHandler("wordle", wordle_command))
    app.add_handler(CommandHandler("dice", dice_command))

    app.add_handler(CommandHandler("points", points_command))
    app.add_handler(CommandHandler("donate", donate_command))
    app.add_handler(CommandHandler("add", add_points_command))
    app.add_handler(CommandHandler("shop", shop_command))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    app.add_handler(CommandHandler("rizz", rizz_command))
    app.add_handler(CommandHandler("roast", roast_command))
    app.add_handler(CommandHandler("ship", ship_command))
    app.add_handler(CommandHandler("joke", joke_command))
    app.add_handler(CommandHandler("fact", fact_command))
    app.add_handler(CommandHandler("wouldyourather", wyr_command))
    app.add_handler(CommandHandler("wyr", wyr_command))
    app.add_handler(CommandHandler("truth", truth_command))
    app.add_handler(CommandHandler("dare", dare_command))
    app.add_handler(CommandHandler("8ball", eightball_command))
    app.add_handler(CommandHandler("rps", rps_command))
    app.add_handler(CommandHandler("roll", roll_command))
    app.add_handler(CommandHandler("anime", anime_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("ig", ig_command))
    app.add_handler(CommandHandler("id", userinfo_command))
    app.add_handler(CommandHandler("userinfo", userinfo_command))

    app.add_handler(CommandHandler("endgame", endgame_command))
    app.add_handler(CommandHandler("q", q_command))
    app.add_handler(CommandHandler("qrand", qrand_command))

    app.add_handler(CommandHandler(["imagine", "img", "draw", "ai"], imagine_command))
    app.add_handler(CommandHandler("wallpaper", wallpaper_command))
    app.add_handler(CommandHandler("own", own_command))
    app.add_handler(CommandHandler(["mypack", "pack"], mypack_command))
    app.add_handler(CommandHandler(["pf", "profile", "card"], pf_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler(["tr", "translate"], translate_command))
    app.add_handler(CommandHandler("define", define_command))
    app.add_handler(CommandHandler("github", github_command))
    app.add_handler(CommandHandler("meme", meme_command))
    app.add_handler(CommandHandler("qr", qr_command))
    app.add_handler(CommandHandler("calc", calc_command))
    app.add_handler(CommandHandler(["simage", "photo2sticker"], simage_command))
    app.add_handler(CallbackQueryHandler(own_q_callback, pattern=r"^ownq_"))

    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("tmute", tmute_command))
    app.add_handler(CommandHandler("tban", tban_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("warns", warns_command))
    app.add_handler(CommandHandler("resetwarns", resetwarns_command))
    app.add_handler(CommandHandler("purge", purge_command))
    app.add_handler(CommandHandler("pin", pin_command))
    app.add_handler(CommandHandler("unpin", unpin_command))

    app.add_handler(CallbackQueryHandler(ttt_callback, pattern="^ttt_"))
    app.add_handler(CallbackQueryHandler(mine_callback, pattern="^mine_"))
    app.add_handler(CallbackQueryHandler(shop_callback, pattern="^shop_"))
    app.add_handler(CallbackQueryHandler(anime_callback, pattern="^ani_"))
    app.add_handler(CallbackQueryHandler(wordle_mode_callback, pattern="^wordlelen_"))
    app.add_handler(CallbackQueryHandler(endgame_callback, pattern="^endgame_"))

    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(smart_trivia_scheduler, interval=60, first=30)

    logging.info("Myra Bot is live!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

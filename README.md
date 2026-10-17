# Myra Telegram Bot

A feature-rich Telegram bot: group games, an economy/points system, moderation
tools, an AI chat persona, free AI image generation, Instagram lookups,
sticker tools and more.

## Setup

1. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Open `api_keys.txt` and paste one or more Groq API keys (one per line).
   Get free keys at https://console.groq.com

3. Open `bot.py` and fill in the placeholders near the top:

   - `TELEGRAM_TOKEN`  - your bot token from @BotFather
   - `NEWS_API_KEY`    - a key from https://newsapi.org
   - `OWNER_ID` / `OWNER_USERNAME` / `OWNER_NAME` - your Telegram details

4. Run it:

   ```
   python bot.py
   ```

## Notes

- Without valid keys the bot still starts, but AI chat and image generation
  will not work until real keys are added.
- Set commands in @BotFather with `/setcommands` (see the command list in the
  repo, or type `/help` in the bot).

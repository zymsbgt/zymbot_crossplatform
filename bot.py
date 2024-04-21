from bot.telegram_bot import TelegramBot
from bot.discord_bot import DiscordBot
import os
from dotenv import load_dotenv
import threading

# Load variables from .env file
load_dotenv()

def main():
    telegram_bot = TelegramBot(os.getenv("TELEGRAM_TOKEN"))
    discord_bot = DiscordBot(os.getenv("DISCORD_TOKEN"))

    # Start both bots
    # telegram_bot.run()
    discord_bot.start()

if __name__ == "__main__":
    main()

from discord_bot import DiscordBot
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

def main():
    discord_bot = DiscordBot(os.getenv("DISCORD_TOKEN"))
    discord_bot.start()

if __name__ == "__main__":
    main()

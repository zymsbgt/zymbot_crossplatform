import logging
import os

from bot.common_utils import request_chatgpt
from telegram import Update
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters)

class TelegramBot:
    def __init__(self, token):
        self.token = token
        
    def run(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello! I'm a chatbot. Start typing away to chat with me!")

        async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            response = request_chatgpt(update.message.text)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=response)
        
        async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await DownloadVideo("telegram", update.message.text, False)

        application = ApplicationBuilder().token(self.token).build()

        # Add registered commands here
        start_handler = CommandHandler('start', start)
        echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), echo) # Chatbot
        download_handler = CommandHandler('download', download)
        application.add_handler(start_handler)
        application.add_handler(echo_handler) # Chatbot
        application.add_handler(download_handler)

        application.run_polling()

    # Other Telegram-specific methods

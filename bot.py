import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import Database
from ai_client import AIClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
AI_API_ENDPOINT = os.getenv('AI_API_ENDPOINT')
AI_API_KEY = os.getenv('AI_API_KEY')
AI_MODEL = os.getenv('AI_MODEL')
MESSAGE_LIMIT = int(os.getenv('MESSAGE_LIMIT', '100'))
DATABASE_PATH = os.getenv('DATABASE_PATH', 'bot_data.db')

# Initialize database and AI client
db = Database(DATABASE_PATH)
ai_client = AIClient(AI_API_ENDPOINT, AI_API_KEY, AI_MODEL)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "Привет! Я бот для создания саммари групповых разговоров.\n\n"
        "Команда:\n"
        "/summary - Получить саммари новых несуммаризированных сообщений\n\n"
        "Я автоматически сохраняю сообщения группы и отслеживаю, какие из них уже были суммаризированы."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store incoming messages in the database"""
    message = update.message
    
    # Skip if no text content
    if not message.text:
        return
    
    # Skip bot commands
    if message.text.startswith('/'):
        return
    
    chat_id = message.chat_id
    message_id = message.message_id
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    text = message.text
    
    # Get thread ID if message is in a thread
    thread_id = None
    if message.is_topic_message:
        thread_id = message.message_thread_id
    
    # Store message in database
    db.add_message(chat_id, message_id, thread_id, user_id, username, text)
    logger.info(f"Stored message from {username} in chat {chat_id}, thread {thread_id}")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /summary command"""
    message = update.message
    chat_id = message.chat_id
    
    # Get thread ID if command is in a thread
    thread_id = None
    if message.is_topic_message:
        thread_id = message.message_thread_id
    
    # Send "thinking" message
    status_message = await message.reply_text("Генерирую саммари...")
    
    try:
        # Retrieve unsummarized messages
        messages = db.get_unsummarized_messages(chat_id, thread_id, MESSAGE_LIMIT)
        
        if not messages:
            await status_message.edit_text("Нет новых сообщений для суммаризации.")
            return
        
        # Extract message IDs and format for AI
        message_ids = [msg[0] for msg in messages]
        formatted_messages = [(msg[1], msg[2], msg[3]) for msg in messages]  # username, text, timestamp
        
        # Generate summary using AI
        summary_text = await ai_client.generate_summary(formatted_messages)
        
        # Mark messages as summarized
        db.mark_messages_as_summarized(message_ids)
        
        # Format response
        thread_info = f" (Тред ID: {thread_id})" if thread_id else ""
        response = f"📝 Саммари {len(messages)} новых сообщений{thread_info}:\n\n{summary_text}"
        
        await status_message.edit_text(response, parse_mode='MarkdownV2')
        logger.info(f"Generated summary for chat {chat_id}, thread {thread_id}, {len(messages)} messages")
    
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        await status_message.edit_text(f"Ошибка при генерации саммари: {str(e)}")


def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in environment variables")
    
    if not AI_API_KEY:
        raise ValueError("AI_API_KEY not set in environment variables")
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start the bot
    logger.info("Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

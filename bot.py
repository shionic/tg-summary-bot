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
THREADED_SEPARATED = os.getenv('THREADED_SEPARATED', 'true').lower() == 'true'

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
    
    # Build display name from first name and last name
    display_name_parts = []
    if message.from_user.first_name:
        display_name_parts.append(message.from_user.first_name)
    if message.from_user.last_name:
        display_name_parts.append(message.from_user.last_name)
    
    # Fallback to username if no display name available
    display_name = " ".join(display_name_parts) if display_name_parts else (message.from_user.username or "Unknown User")
    
    # Get custom title/tag from message and chat member
    custom_title = None
    
    # First, try to get sender_tag from message (Bot API 9.5+)
    if hasattr(message, 'sender_tag') and message.sender_tag:
        custom_title = message.sender_tag
    
    # If no sender_tag, try to get custom_title from chat member (for admins)
    if not custom_title:
        try:
            chat_member = await context.bot.get_chat_member(chat_id, user_id)
            if hasattr(chat_member, 'custom_title') and chat_member.custom_title:
                custom_title = chat_member.custom_title
            # Also try to get tag from ChatMemberMember or ChatMemberRestricted (Bot API 9.5+)
            elif hasattr(chat_member, 'tag') and chat_member.tag:
                custom_title = chat_member.tag
        except Exception as e:
            logger.debug(f"Could not get custom title/tag for user {user_id}: {e}")
    
    text = message.text
    
    # Get thread ID and name if message is in a thread
    thread_id = None
    thread_name = None
    if message.is_topic_message:
        thread_id = message.message_thread_id
        # Try to get thread name from forum topic
        try:
            # The thread name is available in the message_thread_id context
            # We'll store it when we encounter it
            if hasattr(message, 'reply_to_message') and message.reply_to_message:
                if hasattr(message.reply_to_message, 'forum_topic_created'):
                    thread_name = message.reply_to_message.forum_topic_created.name
            # Fallback: try to get from chat
            if not thread_name:
                thread_name = f"Тред {thread_id}"
        except Exception as e:
            logger.debug(f"Could not get thread name: {e}")
            thread_name = f"Тред {thread_id}"
    
    # Store message in database
    db.add_message(chat_id, message_id, thread_id, thread_name, user_id, display_name, custom_title, text)
    logger.info(f"Stored message from {display_name} (title: {custom_title}) in chat {chat_id}, thread {thread_id}")


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
        # Retrieve unsummarized messages based on THREADED_SEPARATED setting
        if THREADED_SEPARATED:
            # Get messages only from current thread/chat
            messages = db.get_unsummarized_messages(chat_id, thread_id, MESSAGE_LIMIT)
            
            if not messages:
                await status_message.edit_text("Нет новых сообщений для суммаризации.")
                return
            
            # Extract message IDs and format for AI
            message_ids = [msg[0] for msg in messages]
            formatted_messages = [(msg[1], msg[2], msg[3], msg[4]) for msg in messages]  # username, custom_title, text, timestamp
            
            # Generate summary using AI
            summary_text = await ai_client.generate_summary(formatted_messages)
            
            # Delete messages after summarization
            db.delete_messages(message_ids)
            
            # Format response - use thread name if available
            thread_name = messages[0][6] if messages and messages[0][6] else None
            thread_info = f" ({thread_name})" if thread_name else (f" (Тред ID: {thread_id})" if thread_id else "")
            response = f"📝 Саммари {len(messages)} новых сообщений{thread_info}:\n\n{summary_text}"
            
            await status_message.edit_text(response, parse_mode='HTML')
            logger.info(f"Generated summary for chat {chat_id}, thread {thread_id}, {len(messages)} messages")
        
        else:
            # Get all unsummarized messages from all threads
            all_messages = db.get_all_unsummarized_messages(chat_id, MESSAGE_LIMIT)
            
            if not all_messages:
                await status_message.edit_text("Нет новых сообщений для суммаризации.")
                return
            
            # Group messages by thread
            from collections import defaultdict
            threads = defaultdict(list)
            thread_names_map = {}
            
            for msg in all_messages:
                msg_id, username, custom_title, text, timestamp, msg_thread_id, thread_name = msg
                threads[msg_thread_id].append((msg_id, username, custom_title, text, timestamp))
                # Store thread name from database
                if msg_thread_id and thread_name:
                    thread_names_map[msg_thread_id] = thread_name
            
            # Prepare grouped messages for AI
            grouped_data = []
            all_message_ids = []
            
            for tid, msgs in threads.items():
                # Use stored thread name or fallback
                thread_name = thread_names_map.get(tid, "Основной чат" if tid is None else f"Тред {tid}")
                thread_messages = []
                
                for msg_id, username, custom_title, text, timestamp in msgs:
                    all_message_ids.append(msg_id)
                    thread_messages.append((username, custom_title, text, timestamp))
                
                grouped_data.append((thread_name, thread_messages))
            
            # Generate combined summary with thread context
            summary_text = await ai_client.generate_summary_grouped(grouped_data)
            
            # Delete messages after summarization
            db.delete_messages(all_message_ids)
            
            # Format response
            response = f"📝 Саммари {len(all_messages)} новых сообщений из {len(threads)} тред(ов):\n\n{summary_text}"
            
            await status_message.edit_text(response, parse_mode='HTML')
            logger.info(f"Generated combined summary for chat {chat_id}, {len(threads)} threads, {len(all_messages)} messages")
    
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

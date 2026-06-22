import os
import logging
import re
from datetime import time
from typing import List, Optional
from dotenv import load_dotenv
from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from database import Database
from ai_client import AIClient, AIInputTooLongError, AITokenUsage

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
AI_MAX_TOKENS = int(os.getenv('AI_MAX_TOKENS', '1500'))
AI_MAX_INPUT_CHARS = int(os.getenv('AI_MAX_INPUT_CHARS', '60000'))
AI_REQUEST_TIMEOUT = int(os.getenv('AI_REQUEST_TIMEOUT', '120'))
TELEGRAM_MESSAGE_LIMIT = min(int(os.getenv('TELEGRAM_MESSAGE_LIMIT', '3900')), 4096)
DATABASE_PATH = os.getenv('DATABASE_PATH', 'bot_data.db')
THREADED_SEPARATED = os.getenv('THREADED_SEPARATED', 'true').lower() == 'true'
AUTO_SUMMARY_ENABLED = os.getenv('AUTO_SUMMARY_ENABLED', 'false').lower() == 'true'
AUTO_SUMMARY_TIME = os.getenv('AUTO_SUMMARY_TIME', '09:00')
AUTO_SUMMARY_CHAT_ID = os.getenv('AUTO_SUMMARY_CHAT_ID')
ALLOWED_CHAT_ID = os.getenv('ALLOWED_CHAT_ID')
SIMPLE_AI_BOT_ENABLED = os.getenv('SIMPLE_AI_BOT_ENABLED', 'false').lower() == 'true'
SIMPLE_AI_BOT_USERNAME = os.getenv('SIMPLE_AI_BOT_USERNAME')
SIMPLE_AI_MAX_TOKENS = int(os.getenv('SIMPLE_AI_MAX_TOKENS', '250'))

# Initialize database and AI client
db = Database(DATABASE_PATH)
ai_client = AIClient(AI_API_ENDPOINT, AI_API_KEY, AI_MODEL, AI_MAX_TOKENS, AI_MAX_INPUT_CHARS, AI_REQUEST_TIMEOUT)

HTML_TAG_RE = re.compile(r'</?(b|i|u|code)>')


def format_token_usage(token_usage: Optional[AITokenUsage]) -> str:
    """Format AI token usage for a Telegram summary footer."""
    if not token_usage or not token_usage.has_summary_tokens:
        return ""

    parts = []
    if token_usage.input_tokens is not None:
        parts.append(f"input: {token_usage.input_tokens}")
    if token_usage.output_tokens is not None:
        parts.append(f"output: {token_usage.output_tokens}")
    if token_usage.total_tokens is not None:
        parts.append(f"total: {token_usage.total_tokens}")

    return f"\n\n<code>Tokens: {', '.join(parts)}</code>"


def split_html_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """Split Telegram HTML into chunks without leaving supported tags unclosed."""
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""
    open_tags = []
    index = 0

    while index < len(text):
        match = HTML_TAG_RE.match(text, index)
        if match:
            unit = match.group(0)
            index = match.end()
        else:
            unit = text[index]
            index += 1

        closing_tags = ''.join(f'</{tag}>' for tag in reversed(open_tags))
        if current and len(current) + len(unit) + len(closing_tags) > limit:
            chunks.append(current.rstrip() + closing_tags)
            current = ''.join(f'<{tag}>' for tag in open_tags)
            if unit == "\n":
                continue

        current += unit

        tag_match = HTML_TAG_RE.fullmatch(unit)
        if tag_match:
            tag = tag_match.group(1)
            if unit.startswith("</"):
                for pos in range(len(open_tags) - 1, -1, -1):
                    if open_tags[pos] == tag:
                        del open_tags[pos]
                        break
            else:
                open_tags.append(tag)

    if current:
        closing_tags = ''.join(f'</{tag}>' for tag in reversed(open_tags))
        chunks.append(current.rstrip() + closing_tags)

    return chunks


async def send_long_reply(message: Message, text: str, first_message: Optional[Message] = None):
    """Edit the status message with the first chunk and send follow-up chunks."""
    chunks = split_html_message(text)
    if first_message:
        await safe_edit_or_send(message, first_message, chunks[0], parse_mode='HTML')
    else:
        await safe_reply_text(message, chunks[0], parse_mode='HTML')

    for chunk in chunks[1:]:
        await safe_reply_text(message, chunk, parse_mode='HTML')


async def send_long_chat_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """Send a long bot message to a chat in Telegram-sized chunks."""
    for chunk in split_html_message(text):
        await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode='HTML')


def _same_thread_kwargs(message: Message) -> dict:
    if message.is_topic_message and message.message_thread_id:
        return {"message_thread_id": message.message_thread_id}
    return {}


def _normalize_bot_username(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    return username.strip().lstrip('@') or None


async def get_simple_ai_bot_username(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Return configured bot username or fetch it from Telegram once."""
    configured_username = _normalize_bot_username(SIMPLE_AI_BOT_USERNAME)
    if configured_username:
        return configured_username

    cached_username = context.bot_data.get("simple_ai_bot_username")
    if cached_username:
        return cached_username

    bot_info = await context.bot.get_me()
    fetched_username = _normalize_bot_username(bot_info.username)
    if fetched_username:
        context.bot_data["simple_ai_bot_username"] = fetched_username
    return fetched_username


def strip_bot_mention(text: str, bot_username: str) -> Optional[str]:
    """Remove @bot_username mentions and return the direct request text."""
    mention_re = re.compile(rf'(?<!\w)@{re.escape(bot_username)}(?!\w)', re.IGNORECASE)
    if not mention_re.search(text):
        return None

    return mention_re.sub('', text).strip()


async def safe_reply_text(message: Message, text: str, **kwargs) -> Message:
    """Reply when possible, otherwise send to the same chat/thread."""
    try:
        return await message.reply_text(text, **kwargs)
    except BadRequest as e:
        if "message to be replied not found" not in str(e).lower():
            raise

        logger.warning(
            f"Reply target message {message.message_id} not found in chat {message.chat_id}; sending regular message"
        )
        return await message.get_bot().send_message(
            chat_id=message.chat_id,
            text=text,
            **_same_thread_kwargs(message),
            **kwargs
        )


async def safe_edit_or_send(
    source_message: Message,
    target_message: Optional[Message],
    text: str,
    **kwargs
) -> Message:
    """Edit a bot status message, or send a new message if editing is no longer possible."""
    if target_message:
        try:
            return await target_message.edit_text(text, **kwargs)
        except BadRequest as e:
            logger.warning(f"Could not edit status message {target_message.message_id}: {e}; sending regular message")

    return await source_message.get_bot().send_message(
        chat_id=source_message.chat_id,
        text=text,
        **_same_thread_kwargs(source_message),
        **kwargs
    )


def is_chat_allowed(chat_id: int) -> bool:
    """Check if the chat is allowed to use the bot"""
    if not ALLOWED_CHAT_ID:
        return True  # No restriction, allow all chats
    try:
        return int(ALLOWED_CHAT_ID) == chat_id
    except ValueError:
        logger.exception(f"Invalid ALLOWED_CHAT_ID format: {ALLOWED_CHAT_ID}")
        return True  # Allow all if config is invalid


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await safe_reply_text(
        update.message,
        "Привет! Я бот для создания саммари групповых разговоров.\n\n"
        "Команда:\n"
        "/summary - Получить саммари новых несуммаризированных сообщений\n\n"
        "Я автоматически сохраняю сообщения группы и отслеживаю, какие из них уже были суммаризированы."
    )


async def maybe_handle_simple_ai_request(message: Message, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Generate one stateless AI response when the message mentions this bot."""
    if not SIMPLE_AI_BOT_ENABLED:
        return False

    bot_username = await get_simple_ai_bot_username(context)
    if not bot_username:
        logger.warning("Simple AI bot is enabled, but bot username could not be resolved")
        return False

    request_text = strip_bot_mention(message.text, bot_username)
    if request_text is None:
        return False

    if not request_text:
        await safe_reply_text(message, "Напишите вопрос после упоминания бота.")
        return True

    try:
        response_text = await ai_client.generate_simple_response(request_text, SIMPLE_AI_MAX_TOKENS)
        await safe_reply_text(message, response_text)
        logger.info(f"Generated simple AI response in chat {message.chat_id}")
    except AIInputTooLongError:
        await safe_reply_text(message, "Сообщение слишком длинное для AI-запроса.")
    except Exception as e:
        logger.exception("Error generating simple AI response")
        await safe_reply_text(message, f"Ошибка при генерации ответа: {str(e)}")

    return True


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
    
    # Check if chat is allowed
    if not is_chat_allowed(chat_id):
        logger.debug(f"Ignoring message from unauthorized chat {chat_id}")
        return

    if await maybe_handle_simple_ai_request(message, context):
        return
    
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
            logger.debug(f"Could not get custom title/tag for user {user_id}", exc_info=True)
    
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
            logger.debug("Could not get thread name", exc_info=True)
            thread_name = f"Тред {thread_id}"
    
    # Store message in database
    db.add_message(chat_id, message_id, thread_id, thread_name, user_id, display_name, custom_title, text)
    logger.info(f"Stored message from {display_name} (title: {custom_title}) in chat {chat_id}, thread {thread_id}")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /summary command"""
    message = update.message
    chat_id = message.chat_id
    
    # Check if chat is allowed
    if not is_chat_allowed(chat_id):
        await safe_reply_text(message, "Этот бот не авторизован для использования в этой группе.")
        logger.warning(f"Unauthorized summary attempt from chat {chat_id}")
        return
    
    # Get thread ID if command is in a thread
    thread_id = None
    if message.is_topic_message:
        thread_id = message.message_thread_id
    
    status_message = None
    try:
        # Send "thinking" message
        status_message = await safe_reply_text(message, "Генерирую саммари...")

        # Retrieve unsummarized messages based on THREADED_SEPARATED setting
        if THREADED_SEPARATED:
            # Get messages only from current thread/chat
            messages = db.get_unsummarized_messages(chat_id, thread_id, MESSAGE_LIMIT)
            
            if not messages:
                await safe_edit_or_send(message, status_message, "Нет новых сообщений для суммаризации.")
                return
            
            # Extract message IDs and format for AI
            formatted_messages = [(msg[1], msg[2], msg[3], msg[4]) for msg in messages]  # username, custom_title, text, timestamp
            formatted_messages, was_trimmed = ai_client.fit_messages_to_input_limit(formatted_messages)
            message_ids = [msg[0] for msg in messages[:len(formatted_messages)]]
            
            # Generate summary using AI
            summary_result = await ai_client.generate_summary(formatted_messages)
            
            # Delete messages after summarization
            db.delete_messages(message_ids)
            
            # Format response - use thread name if available
            thread_name = messages[0][6] if messages and messages[0][6] else None
            thread_info = f" ({thread_name})" if thread_name else (f" (Тред ID: {thread_id})" if thread_id else "")
            count_info = f"{len(formatted_messages)} новых сообщений"
            if was_trimmed:
                count_info += f" из {len(messages)} доступных"
            response = (
                f"📝 Саммари {count_info}{thread_info}:\n\n"
                f"{summary_result.text}{format_token_usage(summary_result.token_usage)}"
            )
            
            await send_long_reply(message, response, status_message)
            logger.info(
                f"Generated summary for chat {chat_id}, thread {thread_id}, "
                f"{len(formatted_messages)} of {len(messages)} messages"
            )
        
        else:
            # Get all unsummarized messages from all threads
            all_messages = db.get_all_unsummarized_messages(chat_id, MESSAGE_LIMIT)
            
            if not all_messages:
                await safe_edit_or_send(message, status_message, "Нет новых сообщений для суммаризации.")
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
            grouped_data, included_message_count, was_trimmed = ai_client.fit_grouped_data_to_input_limit(grouped_data)
            all_message_ids = all_message_ids[:included_message_count]
            summary_result = await ai_client.generate_summary_grouped(grouped_data)
            
            # Delete messages after summarization
            db.delete_messages(all_message_ids)
            
            # Format response
            count_info = f"{included_message_count} новых сообщений"
            if was_trimmed:
                count_info += f" из {len(all_messages)} доступных"
            response = (
                f"📝 Саммари {count_info} из {len(grouped_data)} тред(ов):\n\n"
                f"{summary_result.text}{format_token_usage(summary_result.token_usage)}"
            )
            
            await send_long_reply(message, response, status_message)
            logger.info(
                f"Generated combined summary for chat {chat_id}, {len(grouped_data)} threads, "
                f"{included_message_count} of {len(all_messages)} messages"
            )
    
    except AIInputTooLongError as e:
        logger.warning(f"AI input limit exceeded: {e}")
        await safe_edit_or_send(
            message,
            status_message,
            "Слишком много текста для AI-запроса. Уменьшите MESSAGE_LIMIT или увеличьте AI_MAX_INPUT_CHARS."
        )
    except Exception as e:
        logger.exception("Error generating summary")
        await safe_edit_or_send(message, status_message, f"Ошибка при генерации саммари: {str(e)}")


async def auto_summary_job(context: ContextTypes.DEFAULT_TYPE):
    """Automatic summary job that runs at scheduled time"""
    if not AUTO_SUMMARY_CHAT_ID:
        logger.warning("AUTO_SUMMARY_CHAT_ID not set, skipping automatic summary")
        return
    
    try:
        chat_id = int(AUTO_SUMMARY_CHAT_ID)
        logger.info(f"Running automatic summary for chat {chat_id}")
        
        # Get all unsummarized messages
        if THREADED_SEPARATED:
            # For separated mode, we need to summarize each thread separately
            # This is a simplified approach - summarize main chat only
            messages = db.get_unsummarized_messages(chat_id, None, MESSAGE_LIMIT)
            
            if not messages:
                logger.info("No new messages for automatic summary")
                return
            
            # Extract message IDs and format for AI
            formatted_messages = [(msg[1], msg[2], msg[3], msg[4]) for msg in messages]
            formatted_messages, was_trimmed = ai_client.fit_messages_to_input_limit(formatted_messages)
            message_ids = [msg[0] for msg in messages[:len(formatted_messages)]]
            
            # Generate summary using AI
            summary_result = await ai_client.generate_summary(formatted_messages)
            
            # Delete messages after summarization
            db.delete_messages(message_ids)
            
            # Send summary
            count_info = f"{len(formatted_messages)} новых сообщений"
            if was_trimmed:
                count_info += f" из {len(messages)} доступных"
            response = (
                f"🕐 Автоматическое саммари {count_info}:\n\n"
                f"{summary_result.text}{format_token_usage(summary_result.token_usage)}"
            )
            await send_long_chat_message(context, chat_id, response)
            logger.info(f"Sent automatic summary for chat {chat_id}, {len(formatted_messages)} of {len(messages)} messages")
        
        else:
            # Get all unsummarized messages from all threads
            all_messages = db.get_all_unsummarized_messages(chat_id, MESSAGE_LIMIT)
            
            if not all_messages:
                logger.info("No new messages for automatic summary")
                return
            
            # Group messages by thread
            from collections import defaultdict
            threads = defaultdict(list)
            thread_names_map = {}
            
            for msg in all_messages:
                msg_id, username, custom_title, text, timestamp, msg_thread_id, thread_name = msg
                threads[msg_thread_id].append((msg_id, username, custom_title, text, timestamp))
                if msg_thread_id and thread_name:
                    thread_names_map[msg_thread_id] = thread_name
            
            # Prepare grouped messages for AI
            grouped_data = []
            all_message_ids = []
            
            for tid, msgs in threads.items():
                thread_name = thread_names_map.get(tid, "Основной чат" if tid is None else f"Тред {tid}")
                thread_messages = []
                
                for msg_id, username, custom_title, text, timestamp in msgs:
                    all_message_ids.append(msg_id)
                    thread_messages.append((username, custom_title, text, timestamp))
                
                grouped_data.append((thread_name, thread_messages))
            
            # Generate combined summary with thread context
            grouped_data, included_message_count, was_trimmed = ai_client.fit_grouped_data_to_input_limit(grouped_data)
            all_message_ids = all_message_ids[:included_message_count]
            summary_result = await ai_client.generate_summary_grouped(grouped_data)
            
            # Delete messages after summarization
            db.delete_messages(all_message_ids)
            
            # Send summary
            count_info = f"{included_message_count} новых сообщений"
            if was_trimmed:
                count_info += f" из {len(all_messages)} доступных"
            response = (
                f"🕐 Автоматическое саммари {count_info} из {len(grouped_data)} тред(ов):\n\n"
                f"{summary_result.text}{format_token_usage(summary_result.token_usage)}"
            )
            await send_long_chat_message(context, chat_id, response)
            logger.info(
                f"Sent automatic combined summary for chat {chat_id}, {len(grouped_data)} threads, "
                f"{included_message_count} of {len(all_messages)} messages"
            )
    
    except AIInputTooLongError as e:
        logger.warning(f"Automatic summary AI input limit exceeded: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Слишком много текста для автоматического AI-запроса. Уменьшите MESSAGE_LIMIT или увеличьте AI_MAX_INPUT_CHARS."
        )
    except Exception as e:
        logger.exception("Error in automatic summary job")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log uncaught handler exceptions."""
    if context.error:
        logger.error(
            "Unhandled Telegram update error",
            exc_info=(type(context.error), context.error, context.error.__traceback__)
        )


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
    application.add_error_handler(error_handler)
    
    # Setup automatic summary job if enabled
    if AUTO_SUMMARY_ENABLED:
        try:
            # Parse time from HH:MM format
            hour, minute = map(int, AUTO_SUMMARY_TIME.split(':'))
            summary_time = time(hour=hour, minute=minute)
            
            # Add daily job
            job_queue = application.job_queue
            if job_queue is None:
                raise RuntimeError(
                    "JobQueue is unavailable. Install dependencies with "
                    "`pip install -r requirements.txt` so python-telegram-bot[job-queue] is installed."
                )

            job_queue.run_daily(auto_summary_job, time=summary_time, name='auto_summary')
            
            logger.info(f"Automatic summary scheduled daily at {AUTO_SUMMARY_TIME} for chat {AUTO_SUMMARY_CHAT_ID}")
        except Exception as e:
            logger.exception("Failed to setup automatic summary")
    else:
        logger.info("Automatic summary is disabled")
    
    # Start the bot
    logger.info("Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

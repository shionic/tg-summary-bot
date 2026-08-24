PROMPTS DIRECTORY
=================

This directory contains all AI prompts used by the Telegram Summary Bot.
You can edit these files to customize the bot's behavior without modifying the source code.

FILES:
------

1. summary_single_thread.txt
   - System prompt for summarizing a single thread or main chat
   - Used when THREADED_SEPARATED=true or summarizing main chat
   - Format: Plain text system message

2. summary_grouped_threads.txt
   - System prompt for summarizing multiple threads together
   - Used when THREADED_SEPARATED=false
   - Format: Plain text system message

3. simple_bot_response.txt
   - System prompt for simple AI bot responses to @mentions
   - Used when SIMPLE_AI_BOT_ENABLED=true
   - Format: Plain text system message

4. user_message_template.txt
   - Template for user message sent to AI for summaries
   - Use {conversation_text} as placeholder for the actual conversation
   - Format: Plain text with {conversation_text} placeholder

EDITING PROMPTS:
----------------

1. Open the appropriate .txt file
2. Edit the prompt text as needed
3. Save the file
4. Restart the bot for changes to take effect

NOTES:
------

- All prompts should be in plain text (UTF-8 encoding)
- Keep HTML tag restrictions: only <b>, <i>, <u>, <code> are supported
- Prompts are loaded once at bot startup
- Empty lines at the end of files are automatically stripped
- The {conversation_text} placeholder in user_message_template.txt is required

SUPPORTED HTML TAGS:
--------------------
<b>bold</b>, <i>italic</i>, <u>underline</u>, <code>monospace</code>

DO NOT USE:
-----------
<strong>, <em>, <ul>, <li>, <p>, <br>, or any other HTML tags

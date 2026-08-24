import os
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from http_client import HTTPClient


class AIInputTooLongError(Exception):
    """Raised when the formatted AI input exceeds the configured limit."""


@dataclass(frozen=True)
class AITokenUsage:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    @property
    def has_summary_tokens(self) -> bool:
        return self.input_tokens is not None or self.output_tokens is not None


@dataclass(frozen=True)
class AITextResponse:
    text: str
    token_usage: Optional[AITokenUsage] = None


class AIClient:
    """AI client for generating summaries using Chat Completions API"""
    
    def __init__(
        self,
        api_endpoint: str,
        api_key: str,
        model: str,
        max_tokens: Optional[int] = None,
        max_input_chars: Optional[int] = None,
        request_timeout: Optional[int] = None,
        prompts_dir: str = "prompts"
    ):
        self.api_endpoint = api_endpoint
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens or 1500
        self.max_input_chars = max_input_chars or 60000
        self.http_client = HTTPClient(request_timeout or 120)
        self.prompts_dir = prompts_dir
        
        # Load prompts from files
        self.prompt_summary_single = self._load_prompt("summary_single_thread.txt")
        self.prompt_summary_grouped = self._load_prompt("summary_grouped_threads.txt")
        self.prompt_simple_bot = self._load_prompt("simple_bot_response.txt")
        self.prompt_user_template = self._load_prompt("user_message_template.txt")

    def _load_prompt(self, filename: str) -> str:
        """Load a prompt from a text file"""
        filepath = os.path.join(self.prompts_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except FileNotFoundError:
            raise FileNotFoundError(f"Prompt file not found: {filepath}")
        except Exception as e:
            raise Exception(f"Error loading prompt from {filepath}: {str(e)}")

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    async def _post_chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.http_client.post_json(
            self.api_endpoint,
            self._headers(),
            payload
        )
    
    def _format_messages_for_prompt(self, messages: List[tuple]) -> str:
        """Format messages into a readable conversation text"""
        formatted_messages = []
        for username, custom_title, text, timestamp in messages:
            user_display = username if username else "Unknown User"
            if custom_title:
                user_display = f"{user_display} [{custom_title}]"
            formatted_messages.append(f"{user_display}: {text}")
        
        return "\n".join(formatted_messages)
    
    def _format_grouped_messages_for_prompt(self, grouped_data: List[tuple]) -> str:
        """Format grouped messages by thread into a readable conversation text"""
        formatted_sections = []
        
        for thread_name, messages in grouped_data:
            section = f"=== {thread_name} ===\n"
            for username, custom_title, text, timestamp in messages:
                user_display = username if username else "Unknown User"
                if custom_title:
                    user_display = f"{user_display} [{custom_title}]"
                section += f"{user_display}: {text}\n"
            formatted_sections.append(section)
        
        return "\n\n".join(formatted_sections)

    def fit_messages_to_input_limit(self, messages: List[tuple]) -> Tuple[List[tuple], bool]:
        """Return the largest message prefix that fits the configured input limit."""
        if len(self._format_messages_for_prompt(messages)) <= self.max_input_chars:
            return messages, False

        low = 0
        high = len(messages)
        while low < high:
            mid = (low + high + 1) // 2
            if len(self._format_messages_for_prompt(messages[:mid])) <= self.max_input_chars:
                low = mid
            else:
                high = mid - 1

        if low == 0:
            raise AIInputTooLongError(
                f"AI input is too long: first message exceeds limit of {self.max_input_chars} chars."
            )

        return messages[:low], True

    def fit_grouped_data_to_input_limit(self, grouped_data: List[tuple]) -> Tuple[List[tuple], int, bool]:
        """Return grouped message prefixes that fit the configured input limit."""
        if len(self._format_grouped_messages_for_prompt(grouped_data)) <= self.max_input_chars:
            return grouped_data, sum(len(messages) for _, messages in grouped_data), False

        flattened = []
        for thread_name, messages in grouped_data:
            for message in messages:
                flattened.append((thread_name, message))

        low = 0
        high = len(flattened)
        while low < high:
            mid = (low + high + 1) // 2
            candidate = self._rebuild_grouped_prefix(flattened[:mid])
            if len(self._format_grouped_messages_for_prompt(candidate)) <= self.max_input_chars:
                low = mid
            else:
                high = mid - 1

        if low == 0:
            raise AIInputTooLongError(
                f"AI input is too long: first grouped message exceeds limit of {self.max_input_chars} chars."
            )

        return self._rebuild_grouped_prefix(flattened[:low]), low, True

    def _rebuild_grouped_prefix(self, flattened_messages: List[tuple]) -> List[tuple]:
        grouped = []
        current_thread_name = None
        current_messages = []

        for thread_name, message in flattened_messages:
            if thread_name != current_thread_name:
                if current_messages:
                    grouped.append((current_thread_name, current_messages))
                current_thread_name = thread_name
                current_messages = []
            current_messages.append(message)

        if current_messages:
            grouped.append((current_thread_name, current_messages))

        return grouped
    
    def _build_chat_completion_payload(self, conversation_text: str, is_grouped: bool = False) -> Dict[str, Any]:
        """Build the Chat Completions API payload"""
        if len(conversation_text) > self.max_input_chars:
            raise AIInputTooLongError(
                f"AI input is too long: {len(conversation_text)} chars, limit is {self.max_input_chars}. "
                "Reduce MESSAGE_LIMIT or increase AI_MAX_INPUT_CHARS for a model with a larger context window."
            )
        
        if is_grouped:
            system_content = self.prompt_summary_grouped
        else:
            system_content = self.prompt_summary_single
        
        user_content = self.prompt_user_template.replace("{conversation_text}", conversation_text)
        
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_content
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            "temperature": 0.7,
            "max_tokens": self.max_tokens
        }

    def _build_simple_response_payload(self, request_text: str, max_tokens: int) -> Dict[str, Any]:
        """Build a one-shot Chat Completions payload for direct bot mentions."""
        if len(request_text) > self.max_input_chars:
            raise AIInputTooLongError(
                f"AI input is too long: {len(request_text)} chars, limit is {self.max_input_chars}."
            )

        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": self.prompt_simple_bot
                },
                {
                    "role": "user",
                    "content": request_text
                }
            ],
            "temperature": 0.5,
            "max_tokens": max_tokens
        }
    
    def _extract_summary_from_response(self, response_data: Dict[str, Any]) -> str:
        """Extract summary text from API response"""
        try:
            summary = response_data["choices"][0]["message"]["content"]
            return summary.strip()
        except KeyError as e:
            raise Exception(f"Unexpected API response format: {str(e)}")

    def _extract_token_usage_from_response(self, response_data: Dict[str, Any]) -> Optional[AITokenUsage]:
        """Extract token usage when the API response provides it."""
        usage = response_data.get("usage")
        if not isinstance(usage, dict):
            return None

        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
        total_tokens = usage.get("total_tokens")

        if input_tokens is None and output_tokens is None and total_tokens is None:
            return None

        return AITokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens
        )

    def _extract_text_response_from_response(self, response_data: Dict[str, Any]) -> AITextResponse:
        return AITextResponse(
            text=self._extract_summary_from_response(response_data),
            token_usage=self._extract_token_usage_from_response(response_data)
        )
    
    async def generate_summary(self, messages: List[tuple]) -> AITextResponse:
        """Generate a summary of messages using AI API"""
        # Format messages
        conversation_text = self._format_messages_for_prompt(messages)
        
        # Build payload
        payload = self._build_chat_completion_payload(conversation_text, is_grouped=False)
        
        # Make API request
        response_data = await self._post_chat_completion(payload)
        
        # Extract and return summary
        return self._extract_text_response_from_response(response_data)
    
    async def generate_summary_grouped(self, grouped_data: List[tuple]) -> AITextResponse:
        """Generate a summary of grouped messages (by thread) using AI API"""
        # Format grouped messages
        conversation_text = self._format_grouped_messages_for_prompt(grouped_data)
        
        # Build payload
        payload = self._build_chat_completion_payload(conversation_text, is_grouped=True)
        
        # Make API request
        response_data = await self._post_chat_completion(payload)
        
        # Extract and return summary
        return self._extract_text_response_from_response(response_data)

    async def generate_simple_response(self, request_text: str, max_tokens: int = 250) -> str:
        """Generate a short stateless response to one user message."""
        payload = self._build_simple_response_payload(request_text, max_tokens)
        response_data = await self._post_chat_completion(payload)
        return self._extract_summary_from_response(response_data)

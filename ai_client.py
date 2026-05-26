from typing import List, Dict, Any
from http_client import HTTPClient


class AIClient:
    """AI client for generating summaries using Chat Completions API"""
    
    def __init__(self, api_endpoint: str, api_key: str, model: str):
        self.api_endpoint = api_endpoint
        self.api_key = api_key
        self.model = model
        self.http_client = HTTPClient()
    
    def _format_messages_for_prompt(self, messages: List[tuple]) -> str:
        """Format messages into a readable conversation text"""
        formatted_messages = []
        for username, text, timestamp in messages:
            user_display = username if username else "Unknown User"
            formatted_messages.append(f"{user_display}: {text}")
        
        return "\n".join(formatted_messages)
    
    def _format_grouped_messages_for_prompt(self, grouped_data: List[tuple]) -> str:
        """Format grouped messages by thread into a readable conversation text"""
        formatted_sections = []
        
        for thread_name, messages in grouped_data:
            section = f"=== {thread_name} ===\n"
            for username, text, timestamp in messages:
                user_display = username if username else "Unknown User"
                section += f"{user_display}: {text}\n"
            formatted_sections.append(section)
        
        return "\n\n".join(formatted_sections)
    
    def _build_chat_completion_payload(self, conversation_text: str, is_grouped: bool = False) -> Dict[str, Any]:
        """Build the Chat Completions API payload"""
        
        if is_grouped:
            system_content = "Ты помощник, который суммаризирует групповые чаты с несколькими тредами. Предоставь краткое саммари для каждого треда отдельно, указывая название треда. Используй Telegram MarkdownV2 форматирование для структурирования ответа: *жирный текст* для важных моментов, _курсив_ для акцентов, списки для перечислений. Отвечай на русском языке. ВАЖНО: Экранируй специальные символы MarkdownV2: \\_ \\* \\[ \\] \\( \\) \\~ \\` \\> \\# \\+ \\- \\= \\| \\{ \\} \\. \\!"
        else:
            system_content = "Ты помощник, который суммаризирует групповые чаты. Предоставь краткое саммари основных тем и ключевых моментов обсуждения. Используй Telegram MarkdownV2 форматирование для структурирования ответа: *жирный текст* для важных моментов, _курсив_ для акцентов, списки для перечислений. Отвечай на русском языке. ВАЖНО: Экранируй специальные символы MarkdownV2: \\_ \\* \\[ \\] \\( \\) \\~ \\` \\> \\# \\+ \\- \\= \\| \\{ \\} \\. \\!"
        
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_content
                },
                {
                    "role": "user",
                    "content": f"Пожалуйста, суммаризируй следующий разговор:\n\n{conversation_text}"
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
    
    def _extract_summary_from_response(self, response_data: Dict[str, Any]) -> str:
        """Extract summary text from API response"""
        try:
            summary = response_data["choices"][0]["message"]["content"]
            return summary.strip()
        except KeyError as e:
            raise Exception(f"Unexpected API response format: {str(e)}")
    
    async def generate_summary(self, messages: List[tuple]) -> str:
        """Generate a summary of messages using AI API"""
        # Format messages
        conversation_text = self._format_messages_for_prompt(messages)
        
        # Build payload
        payload = self._build_chat_completion_payload(conversation_text, is_grouped=False)
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Make API request
        response_data = await self.http_client.post_json(
            self.api_endpoint,
            headers,
            payload
        )
        
        # Extract and return summary
        return self._extract_summary_from_response(response_data)
    
    async def generate_summary_grouped(self, grouped_data: List[tuple]) -> str:
        """Generate a summary of grouped messages (by thread) using AI API"""
        # Format grouped messages
        conversation_text = self._format_grouped_messages_for_prompt(grouped_data)
        
        # Build payload
        payload = self._build_chat_completion_payload(conversation_text, is_grouped=True)
        
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Make API request
        response_data = await self.http_client.post_json(
            self.api_endpoint,
            headers,
            payload
        )
        
        # Extract and return summary
        return self._extract_summary_from_response(response_data)

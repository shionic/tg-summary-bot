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
    
    def _build_chat_completion_payload(self, conversation_text: str) -> Dict[str, Any]:
        """Build the Chat Completions API payload"""
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Ты помощник, который суммаризирует групповые чаты. Предоставь краткое саммари основных тем и ключевых моментов обсуждения. Используй Markdown форматирование для структурирования ответа: **жирный текст** для важных моментов, *курсив* для акцентов, списки для перечислений. Отвечай на русском языке."
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
        payload = self._build_chat_completion_payload(conversation_text)
        
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

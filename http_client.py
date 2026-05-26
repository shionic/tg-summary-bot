import aiohttp
import json
from typing import Dict, Any


class HTTPClient:
    """HTTP client for making API requests"""
    
    def __init__(self, timeout: int = 30):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
    
    async def post_json(self, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make a POST request with JSON payload"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', '')
                        
                        # Handle streaming response (SSE)
                        if 'text/event-stream' in content_type:
                            return await self._parse_streaming_response(response)
                        # Handle regular JSON response
                        else:
                            return await response.json()
                    else:
                        error_text = await response.text()
                        raise Exception(f"API request failed with status {response.status}: {error_text}")
        
        except aiohttp.ClientError as e:
            raise Exception(f"Network error: {str(e)}")
        except Exception as e:
            raise Exception(f"Request error: {str(e)}")
    
    async def _parse_streaming_response(self, response) -> Dict[str, Any]:
        """Parse Server-Sent Events (SSE) streaming response"""
        full_content = ""
        
        async for line in response.content:
            line_text = line.decode('utf-8').strip()
            
            # Skip empty lines and comments
            if not line_text or line_text.startswith(':'):
                continue
            
            # Parse SSE data lines
            if line_text.startswith('data: '):
                data_content = line_text[6:]  # Remove 'data: ' prefix
                
                # Skip [DONE] marker
                if data_content == '[DONE]':
                    break
                
                try:
                    chunk = json.loads(data_content)
                    # Extract content delta from streaming chunk
                    if 'choices' in chunk and len(chunk['choices']) > 0:
                        delta = chunk['choices'][0].get('delta', {})
                        if 'content' in delta:
                            full_content += delta['content']
                except json.JSONDecodeError:
                    continue
        
        # Return in the same format as non-streaming response
        return {
            "choices": [
                {
                    "message": {
                        "content": full_content
                    }
                }
            ]
        }

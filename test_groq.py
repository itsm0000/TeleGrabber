import httpx, os
from dotenv import load_dotenv

load_dotenv('backend/.env')
groq_key = os.environ.get('GROQ_API_KEY')
groq_url = 'https://api.groq.com/openai/v1/chat/completions'
headers = { 'Authorization': f'Bearer {groq_key}', 'Content-Type': 'application/json' }
payload = {
    'model': 'llama-3.3-70b-versatile',
    'messages': [{'role': 'system', 'content': 'You are a categorizer. Output JSON.'}, {'role': 'user', 'content': 'classify this: [{"id": "1", "text": "hello"}]'}],
    'response_format': {'type': 'json_object'}
}
res = httpx.post(groq_url, headers=headers, json=payload, timeout=10.0)
print('Status:', res.status_code)
print('Response:', res.text)

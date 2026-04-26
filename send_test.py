import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN or not CHAT_ID:
    print("❌ .env 파일에 TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 입력해주세요.")
    exit(1)

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "✅ 알림 테스트 성공! 주식 알림 시스템이 정상 작동합니다.",
}

response = requests.post(url, json=payload)

if response.status_code == 200:
    print("✅ 메시지 전송 성공!")
else:
    print(f"❌ 전송 실패: {response.status_code}")
    print(response.text)

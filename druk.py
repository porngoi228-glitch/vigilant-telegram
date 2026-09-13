import asyncio
import logging
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message
from dotenv import load_dotenv

from Triggers import TRIGGERS

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise SystemExit(
        "BOT_TOKEN не задан: скопируй .env.example в .env и вставь токен от BotFather."
    )

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def pick_response(response):
    if isinstance(response, (list, tuple)):
        return random.choice(response)
    return response


def find_response(text: str):
    text_lower = text.lower()
    for trigger, response in TRIGGERS.items():
        if trigger.lower() in text_lower:
            return pick_response(response)
    return None


@dp.message(F.text)
async def handle_message(message: Message):
    response = find_response(message.text)
    if response is None:
        return
    await message.answer(response, message_thread_id=message.message_thread_id)


PORT = int(os.environ.get("PORT", "8080"))


class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args):
        pass


async def main():
    server = HTTPServer(("0.0.0.0", PORT), KeepAliveHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logging.info("Keep-alive HTTP server on port %s", PORT)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
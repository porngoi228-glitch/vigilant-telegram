import asyncio
import html
import logging
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyParameters
from dotenv import load_dotenv

from Triggers import TRIGGERS

from Checkers import (
    apply_move,
    choose_move,
    legal_moves,
    parse_path,
    piece_count,
    render,
    sq_name,
    start_board,
    user_move,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise SystemExit(
        "BOT_TOKEN не задан: скопируй .env.example в .env и вставь токен от BotFather."
    )

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


class GameStates(StatesGroup):
    knb_wait = State()
    knb_two_wait = State()
    guess_wait = State()
    checkers = State()
    knt_wait = State()
    knt_two_wait = State()
    hangman = State()


SHAPES = {"камень", "ножницы", "бумага"}
BEATS = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}

GAME_HELP_KEYWORDS = {"игра", "игры", "поиграем", "во что поиграть"}
GAME_STARTERS = {
    "кнб",
    "кнб с ботом",
    "камень ножницы бумага",
    "кнб на двоих",
    "кнб вдвоём",
    "кнб2",
    "кости",
    "кости с ботом",
    "кубик",
    "брось кости",
    "угадай",
    "угадай число",
    "загадай число",
    "шашки",
    "шашки с ботом",
    "поиграем в шашки",
    "давай в шашки",
    "сходим в шашки",
    "в шашки",
    "крестики-нолики",
    "кнт",
    "кнт с ботом",
    "крестики-нолики на двоих",
    "кнт на двоих",
    "кнт вдвоём",
    "кнт2",
    "виселица",
    "угадай слово",
    "отгадай слово",
}
CANCEL_WORDS = {"стоп", "стоп игра", "выход", "отмена", "хватит"}

GAME_LIST = (
    "Наши игры, друк:\n"
    "• <b>кнб</b> — камень-ножницы-бумага против бота\n"
    "• <b>кнб на двоих</b> — камень-ножницы-бумага вдвоём\n"
    "• <b>кости</b> — бросаем кубики против бота\n"
    "• <b>угадай число</b> — отгадай число от 1 до 20\n"
    "• <b>шашки</b> — партия против бота (ход e3-d4, бой c3:e5:g7)\n"
    "• <b>кнт</b> — крестики-нолики против бота; на двоих: «кнт на двоих»\n"
    "• <b>виселица</b> — угадай слово по буквам\n"
    "Напиши название игры, чтобы начать. Выйти из игры — «стоп»."
)


def norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


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


def player_name(message: Message) -> str:
    return html.escape(message.from_user.username or message.from_user.full_name or str(message.from_user.id))


async def say(message: Message, text: str):
    await message.answer(text, reply_parameters=ReplyParameters(message_id=message.message_id))


KNT_WIN = [
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
]


def knt_winner(cells):
    for a, b, c in KNT_WIN:
        if cells[a] and cells[a] == cells[b] == cells[c]:
            return cells[a]
    return None


def knt_full(cells):
    return all(cells)


def knt_render(cells):
    return "\n".join(
        " | ".join(cells[r * 3 + c] or str(r * 3 + c + 1) for c in range(3))
        for r in range(3)
    )


def knt_score(cells, bot, bot_turn):
    w = knt_winner(cells)
    if w == bot:
        return 1
    if w:
        return -1
    if knt_full(cells):
        return 0
    mark = bot if bot_turn else ("X" if bot == "O" else "O")
    if bot_turn:
        best = -2
        for i in range(9):
            if cells[i]:
                continue
            cells[i] = mark
            best = max(best, knt_score(cells, bot, False))
            cells[i] = None
        return best
    best = 2
    for i in range(9):
        if cells[i]:
            continue
        cells[i] = mark
        best = min(best, knt_score(cells, bot, True))
        cells[i] = None
    return best


def knt_best(cells, bot):
    best_i = None
    best_s = -2
    for i in range(9):
        if cells[i]:
            continue
        cells[i] = bot
        s = knt_score(cells, bot, False)
        cells[i] = None
        if s > best_s:
            best_s = s
            best_i = i
    return best_i


HANGMAN_WORDS = [
    "автобус", "арбуз", "белка", "вагон", "гитара", "гриб", "дружба",
    "закат", "зонт", "кофе", "кот", "лампа", "лиса", "машина",
    "облако", "пицца", "планета", "ракета", "собака", "солнце",
    "стол", "телефон", "трава", "утро", "чашка", "школа",
]


def mask_word(word, found):
    return " ".join(ch if ok else "•" for ch, ok in zip(word, found))


def hangman_text(word, found, wrong, left):
    return (
        f"Слово: {mask_word(word, found)}\n"
        f"Попыток осталось: {left}\n"
        f"Неверные: {', '.join(wrong) if wrong else '—'}"
    )


@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    await say(message, "Привет, друк! Я Друк-бот v1.2." + GAME_LIST)


@dp.message(F.text)
async def handle_message(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        raise SkipHandler
    t = norm(message.text)
    if t in GAME_HELP_KEYWORDS:
        await say(message, GAME_LIST)
        return
    if t in GAME_STARTERS:
        raise SkipHandler
    response = find_response(message.text)
    if response is None:
        raise SkipHandler
    await say(message, response)


@dp.message(F.text)
async def cancel_game(message: Message, state: FSMContext):
    if norm(message.text) not in CANCEL_WORDS:
        raise SkipHandler
    if await state.get_state() is None:
        raise SkipHandler
    await state.clear()
    await say(message, "Игра отменена, друк.")


@dp.message(F.text)
async def start_knb(message: Message, state: FSMContext):
    if norm(message.text) not in {"кнб", "кнб с ботом", "камень ножницы бумага"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.knb_wait)
    await say(message, "Погнали! Пиши свой ход: камень / ножницы / бумага.")


@dp.message(F.text)
async def knb_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knb_wait:
        raise SkipHandler
    move = norm(message.text)
    if move not in SHAPES:
        raise SkipHandler
    bot_move = random.choice(list(SHAPES))
    await state.clear()
    if move == bot_move:
        result = "Ничья, друк. Ещё разок?"
    elif BEATS[move] == bot_move:
        result = "Ты победил, друк! Реванш, если слабо?"
    else:
        result = "Бот победил, друк. Партия-реванш?"
    await say(message, f"Ты — {move}, бот — {bot_move}. {result}")


@dp.message(F.text)
async def start_knb_two(message: Message, state: FSMContext):
    if norm(message.text) not in {"кнб на двоих", "кнб вдвоём", "кнб2"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.knb_two_wait)
    await state.update_data(moves=[])
    await say(message, "Играем вдвоём, друки! Первый пишет ход: камень / ножницы / бумага.")


@dp.message(F.text)
async def knb_two_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knb_two_wait:
        raise SkipHandler
    move = norm(message.text)
    if move not in SHAPES:
        raise SkipHandler
    data = await state.get_data()
    moves = data.get("moves", [])
    if not moves:
        moves = [(player_name(message), move)]
        await state.update_data(moves=moves)
        await say(message, f"{moves[0][0]} сыграл(а) {move}. Теперь второй пишет свой ход.")
        return
    await state.clear()
    second = (player_name(message), move)
    first = moves[0]
    if first[1] == second[1]:
        result = "Ничья, друки!"
    elif BEATS[first[1]] == second[1]:
        result = f"Победа за {first[0]}!"
    else:
        result = f"Победа за {second[0]}!"
    await say(message, f"{first[0]}: {first[1]} | {second[0]}: {second[1]}. {result}")


@dp.message(F.text)
async def start_dice(message: Message, state: FSMContext):
    if norm(message.text) not in {"кости", "кости с ботом", "кубик", "брось кости"}:
        raise SkipHandler
    await state.clear()
    user_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)
    if user_roll > bot_roll:
        result = "Ты выиграл, друк! Кубик любит смелых."
    elif user_roll < bot_roll:
        result = "Бот выиграл, друк. Реванш?"
    else:
        result = "Ровно! Ничья, друк."
    await say(message, f"🎲 Твой кубик: {user_roll}\n🎲 Кубик бота: {bot_roll}\n{result}")


@dp.message(F.text)
async def start_guess(message: Message, state: FSMContext):
    if norm(message.text) not in {"угадай", "угадай число", "загадай число"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.guess_wait)
    await state.update_data(secret=random.randint(1, 20))
    await say(message, "Я загадал число от 1 до 20. Пиши варианты, друк.")


@dp.message(F.text)
async def guess_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.guess_wait:
        raise SkipHandler
    try:
        guess = int(norm(message.text))
    except ValueError:
        raise SkipHandler
    data = await state.get_data()
    secret = data.get("secret")
    if guess < secret:
        await say(message, f"{guess}? Маловато, друк. Пробуй выше.")
    elif guess > secret:
        await say(message, f"{guess}? Перебор, друк. Пробуй меньше.")
    else:
        await state.clear()
        await say(message, f"Верно! Загадано было {secret}. Ты гений, друк!")


@dp.message(F.text)
async def start_checkers(message: Message, state: FSMContext):
    if norm(message.text) not in {
        "шашки",
        "шашки с ботом",
        "поиграем в шашки",
        "давай в шашки",
        "сходим в шашки",
        "в шашки",
    }:
        raise SkipHandler
    board = start_board()
    await state.clear()
    await state.set_state(GameStates.checkers)
    await state.update_data(board=board)
    await say(
        message,
        render(board)
        + "\n\nТы играешь белыми (⛀) и ходишь первым. "
        "Ход: e3-d4. Взятие: c3:e5:g7 — цепочку доводи до конца! «стоп» — выйти.",
    )


@dp.message(F.text)
async def checkers_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.checkers:
        raise SkipHandler
    board = (await state.get_data())["board"]
    path = parse_path(message.text)
    if path is None:
        await say(message, render(board) + "\n\nНе понял ход. Формат: e3-d4 или c3:e5:g7.")
        return
    move = user_move(board, "w", path)
    if move is None:
        await say(
            message,
            render(board)
            + "\n\nТакой ход невозможен. Если есть бой — бей и доводи цепочку до конца.",
        )
        return
    board = apply_move(board, "w", move)
    if piece_count(board, "b") == 0 or not legal_moves(board, "b"):
        await state.clear()
        await say(message, render(board) + "\n\nТы выиграл, друк! Шашки — твоя стихия.")
        return
    bot_move = choose_move(board, "b")
    if bot_move is None:
        await state.clear()
        await say(message, render(board) + "\n\nБоту некуда ходить — ты выиграл, друк!")
        return
    a, z = bot_move["squares"][0], bot_move["squares"][-1]
    board = apply_move(board, "b", bot_move)
    await state.update_data(board=board)
    taken = len(bot_move["captured"])
    bot_text = f"{sq_name(*a)}-{sq_name(*z)}" + (f", взято {taken}" if taken else "")
    if piece_count(board, "w") == 0 or not legal_moves(board, "w"):
        await state.clear()
        await say(message, render(board) + f"\n\nБот сходил: {bot_text}. Бот выиграл, друк. Реванш?")
        return
    await say(message, render(board) + f"\n\nБот сходил: {bot_text}. Твой ход.")


@dp.message(F.text)
async def start_knt(message: Message, state: FSMContext):
    if norm(message.text) not in {"крестики-нолики", "кнт", "кнт с ботом"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.knt_wait)
    await state.update_data(cells=[None] * 9)
    await say(message, f"{knt_render([None] * 9)}\n\nТы — X, я — O. Пиши номер клетки (1-9).")


@dp.message(F.text)
async def knt_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knt_wait:
        raise SkipHandler
    cells = (await state.get_data())["cells"]
    try:
        cell = int(norm(message.text))
    except ValueError:
        await say(message, "Пиши номер клетки от 1 до 9, друк.")
        return
    idx = cell - 1
    if idx not in range(9):
        await say(message, "Клеток всего 9: от 1 до 9. Повтори, друк.")
        return
    if cells[idx]:
        await say(message, "Занято, друк. Выбери свободную клетку.")
        return
    cells[idx] = "X"
    w = knt_winner(cells)
    if w == "X":
        await state.clear()
        await say(message, knt_render(cells) + "\n\nТы победил, друк! Крестики — сила.")
        return
    if knt_full(cells):
        await state.clear()
        await say(message, knt_render(cells) + "\n\nНичья, друк. Ещё партию?")
        return
    bot = knt_best(cells, "O")
    cells[bot] = "O"
    w = knt_winner(cells)
    if w == "O":
        await state.clear()
        await say(message, knt_render(cells) + "\n\nБот победил, друк. Реванш?")
        return
    if knt_full(cells):
        await state.clear()
        await say(message, knt_render(cells) + "\n\nНичья, друк. Ещё партию?")
        return
    await state.update_data(cells=cells)
    await say(message, knt_render(cells) + "\n\nТвой ход, друк.")


@dp.message(F.text)
async def start_knt_two(message: Message, state: FSMContext):
    if norm(message.text) not in {"крестики-нолики на двоих", "кнт на двоих", "кнт вдвоём", "кнт2"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.knt_two_wait)
    await state.update_data(cells=[None] * 9, turn="X")
    await say(message, f"{knt_render([None] * 9)}\n\nИграем вдвоём, друки! X ходит первым — пиши номер клетки.")


@dp.message(F.text)
async def knt_two_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knt_two_wait:
        raise SkipHandler
    data = await state.get_data()
    cells = data["cells"]
    turn = data["turn"]
    try:
        cell = int(norm(message.text))
    except ValueError:
        await say(message, "Пиши номер клетки от 1 до 9, друки.")
        return
    idx = cell - 1
    if idx not in range(9):
        await say(message, "Клеток всего 9: от 1 до 9. Повтори, друки.")
        return
    if cells[idx]:
        await say(message, "Занято, друки. Выберите свободную клетку.")
        return
    cells[idx] = turn
    w = knt_winner(cells)
    if w:
        await state.clear()
        await say(message, knt_render(cells) + f"\n\nПобеда {w}, друки!")
        return
    if knt_full(cells):
        await state.clear()
        await say(message, knt_render(cells) + "\n\nНичья, друки!")
        return
    nxt = "O" if turn == "X" else "X"
    await state.update_data(cells=cells, turn=nxt)
    await say(message, knt_render(cells) + f"\n\nТеперь ходит {nxt}, друки.")


@dp.message(F.text)
async def start_hangman(message: Message, state: FSMContext):
    if norm(message.text) not in {"виселица", "угадай слово", "отгадай слово"}:
        raise SkipHandler
    word = random.choice(HANGMAN_WORDS)
    await state.clear()
    await state.set_state(GameStates.hangman)
    await state.update_data(word=word, found=[False] * len(word), wrong=[], left=6)
    await say(
        message,
        hangman_text(word, [False] * len(word), [], 6)
        + "\n\nПиши букву или слово целиком, друк.",
    )


@dp.message(F.text)
async def hangman_guess(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.hangman:
        raise SkipHandler
    data = await state.get_data()
    word = data["word"]
    found = data["found"]
    wrong = data["wrong"]
    left = data["left"]
    t = norm(message.text)
    if len(t) == 1 and t.isalpha():
        letter = t.lower()
        if letter in word:
            for i, ch in enumerate(word):
                if ch == letter:
                    found[i] = True
        elif letter not in wrong:
            wrong.append(letter)
            left -= 1
        if all(found):
            await state.clear()
            await say(message, hangman_text(word, found, wrong, left) + f"\n\nОтгадал, друк! Слово: {word}.")
            return
        if left <= 0:
            await state.clear()
            await say(message, f"Без шансов, друк. Слово было: {word}. «виселица» — реванш.")
            return
        await state.update_data(found=found, wrong=wrong, left=left)
        await say(message, hangman_text(word, found, wrong, left) + "\n\nЕщё букву или слово целиком, друк.")
        return
    if not t or not t.isalpha():
        await say(message, "Пиши букву или слово, друк.")
        return
    if t.lower() == word:
        await state.clear()
        await say(message, f"В яблочко, друк! Слово: {word}.")
        return
    left -= 1
    if left <= 0:
        await state.clear()
        await say(message, f"Не то слово, друк. Было: {word}. «виселица» — реванш.")
        return
    await state.update_data(left=left)
    await say(message, hangman_text(word, found, wrong, left) + "\n\nНе то слово, друк. Ещё вариант?")


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
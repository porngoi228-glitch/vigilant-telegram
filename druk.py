import asyncio
import glob
import html
import logging
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyParameters,
)
from dotenv import load_dotenv

from Triggers import TRIGGERS

from Checkers import (
    SYMBOLS,
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
TOKEN = (os.getenv("BOT_TOKEN") or "").strip().strip('"').strip("'")

if not TOKEN:
    raise SystemExit(
        "BOT_TOKEN не задан: скопируй .env.example в .env и вставь токен от BotFather."
    )

logging.basicConfig(level=logging.INFO)
logging.info("BOT_TOKEN loaded (length %s)", len(TOKEN))

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
LETTERS = "абвгдежзийклмнопрстуфхцчшщъыьэюя"

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
    "• <b>шашки</b> — партия против бота (жми шашку, потом клетку хода)\n"
    "• <b>кнт</b> — крестики-нолики против бота; на двоих: «кнт на двоих»\n"
    "• <b>виселица</b> — угадай слово по буквам\n"
    "Всё играется кнопками. Напиши название игры, чтобы начать. Выйти — «стоп»."
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


async def say(message: Message, text: str, markup=None):
    await message.answer(
        text,
        reply_parameters=ReplyParameters(message_id=message.message_id),
        reply_markup=markup,
    )


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def knb_board(prefix: str) -> InlineKeyboardMarkup:
    return kb([
        [btn("Камень", f"{prefix}:камень"), btn("Ножницы", f"{prefix}:ножницы"), btn("Бумага", f"{prefix}:бумага")],
        [btn("Стоп", "stop_game")],
    ])


def replay_board(again_data: str) -> InlineKeyboardMarkup:
    return kb([[btn("Ещё раз", again_data)], [btn("Выход", "stop_game")]])


def guess_board() -> InlineKeyboardMarkup:
    rows = []
    for i in range(1, 21, 5):
        rows.append([btn(str(j), f"guess:{j}") for j in range(i, i + 5)])
    rows.append([btn("Стоп", "stop_game")])
    return kb(rows)


def knt_board(cells, prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            row.append(btn(cells[i] or str(i + 1), f"{prefix}:{i}"))
        rows.append(row)
    rows.append([btn("Стоп", "stop_game")])
    return kb(rows)


def hang_board(used) -> InlineKeyboardMarkup:
    avail = [ch for ch in LETTERS if ch not in used]
    rows = [[btn(ch, f"hang:{ch}") for ch in avail[i:i + 6]] for i in range(0, len(avail), 6)]
    rows.append([btn("Стоп", "stop_game")])
    return kb(rows)


def chk_board(board, selected=None, dests=None) -> InlineKeyboardMarkup:
    d = set(dests or [])
    rows = []
    for r in range(8):
        row = []
        for c in range(8):
            if (r, c) == selected:
                label = "◉"
            elif (r, c) in d:
                label = "*"
            else:
                label = SYMBOLS.get(board[r][c], "·")
            row.append(btn(label, f"chk:{r}:{c}"))
        rows.append(row)
    rows.append([btn("Сдаться", "stop_game")])
    return kb(rows)


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


ACTIVE_CHATS: set = set()

MEDIA_DIR = "media"
MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4")


class TrackChats(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            ACTIVE_CHATS.add(event.chat.id)
        return await handler(event, data)


def random_media():
    paths = []
    for base in (".", MEDIA_DIR):
        if not os.path.isdir(base):
            continue
        for dirpath, _, files in os.walk(base):
            for fn in files:
                if fn.lower().endswith(MEDIA_EXTS):
                    paths.append(os.path.join(dirpath, fn))
    return random.choice(paths) if paths else None


async def send_random_media():
    if not ACTIVE_CHATS:
        return
    media = random_media()
    if media is None:
        logging.info("Нет медиа в папке %s — пропускаю рассылку.", MEDIA_DIR)
        return
    chat_id = random.choice(list(ACTIVE_CHATS))
    if media.lower().endswith((".gif", ".mp4")):
        await bot.send_animation(chat_id, FSInputFile(media))
    else:
        await bot.send_photo(chat_id, FSInputFile(media))
    logging.info("Отправил медиа %s в чат %s", media, chat_id)


async def media_loop():
    base = int(os.environ.get("MEDIA_MINUTES", "180"))
    if base <= 0:
        logging.info("MEDIA_MINUTES=0 — рассылка медиа отключена.")
        return
    low = max(base // 2, 15)
    high = max(base * 2, 30)
    while True:
        await asyncio.sleep(random.randint(low, high) * 60)
        try:
            await send_random_media()
        except Exception:
            logging.exception("media_loop error")


MEDIA_STOP_WORDS = {"скинь фото", "фото", "фотку", "гиф", "гифку", "картинку", "пришли фото"}


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
    if t in MEDIA_STOP_WORDS:
        await send_random_media()
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
    await say(message, "Камень, ножницы, бумага?", markup=knb_board("knb"))


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
    await say(message, f"Ты — {move}, бот — {bot_move}. {result}", markup=replay_board("knb_again"))


@dp.message(F.text)
async def start_knb_two(message: Message, state: FSMContext):
    if norm(message.text) not in {"кнб на двоих", "кнб вдвоём", "кнб2"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.knb_two_wait)
    await state.update_data(moves=[])
    await say(message, "Играем вдвоём, друки! Первый жмёт свой ход.", markup=knb_board("knb2"))


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
        await say(message, f"{moves[0][0]} сыграл(а) {move}. Теперь второй жмёт ход.", markup=knb_board("knb2"))
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
    await say(message, f"{first[0]}: {first[1]} | {second[0]}: {second[1]}. {result}", markup=replay_board("knb2_again"))


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
    await say(
        message,
        f"🎲 Твой кубик: {user_roll}\n🎲 Кубик бота: {bot_roll}\n{result}",
        markup=replay_board("dice_again"),
    )


@dp.message(F.text)
async def start_guess(message: Message, state: FSMContext):
    if norm(message.text) not in {"угадай", "угадай число", "загадай число"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.guess_wait)
    await state.update_data(secret=random.randint(1, 20))
    await say(message, "Я загадал число от 1 до 20. Жми вариант, друк.", markup=guess_board())


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
        await say(message, f"{guess}? Маловато, друк. Пробуй выше.", markup=guess_board())
    elif guess > secret:
        await say(message, f"{guess}? Перебор, друк. Пробуй меньше.", markup=guess_board())
    else:
        await state.clear()
        await say(message, f"Верно! Загадано было {secret}. Ты гений, друк!", markup=replay_board("guess_again"))


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
        + "\n\nТы играешь белыми (⛀) и ходишь первым. Жми свою шашку, потом клетку — куда сходить. Или пиши ход текстом: e3-d4. «стоп» — выйти.",
        markup=chk_board(board),
    )


@dp.message(F.text)
async def checkers_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.checkers:
        raise SkipHandler
    board = (await state.get_data())["board"]
    path = parse_path(message.text)
    if path is None:
        await say(message, render(board) + "\n\nНе понял ход. Формат: e3-d4 или c3:e5:g7.", markup=chk_board(board))
        return
    move = user_move(board, "w", path)
    if move is None:
        await say(
            message,
            render(board)
            + "\n\nТакой ход невозможен. Если есть бой — бей и доводи цепочку до конца.",
            markup=chk_board(board),
        )
        return
    board = apply_move(board, "w", move)
    if piece_count(board, "b") == 0 or not legal_moves(board, "b"):
        await state.clear()
        await say(message, render(board) + "\n\nТы выиграл, друк! Шашки — твоя стихия.", markup=replay_board("chk_again"))
        return
    bot_move = choose_move(board, "b")
    if bot_move is None:
        await state.clear()
        await say(message, render(board) + "\n\nБоту некуда ходить — ты выиграл, друк!", markup=replay_board("chk_again"))
        return
    a, z = bot_move["squares"][0], bot_move["squares"][-1]
    board = apply_move(board, "b", bot_move)
    await state.update_data(board=board)
    taken = len(bot_move["captured"])
    bot_text = f"{sq_name(*a)}-{sq_name(*z)}" + (f", взято {taken}" if taken else "")
    if piece_count(board, "w") == 0 or not legal_moves(board, "w"):
        await state.clear()
        await say(message, render(board) + f"\n\nБот сходил: {bot_text}. Бот выиграл, друк. Реванш?", markup=replay_board("chk_again"))
        return
    await say(message, render(board) + f"\n\nБот сходил: {bot_text}. Твой ход.", markup=chk_board(board))


@dp.message(F.text)
async def start_knt(message: Message, state: FSMContext):
    if norm(message.text) not in {"крестики-нолики", "кнт", "кнт с ботом"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.knt_wait)
    await state.update_data(cells=[None] * 9)
    cells = [None] * 9
    await say(message, f"{knt_render(cells)}\n\nТы — X, я — O. Жми клетку.", markup=knt_board(cells, "knt"))


@dp.message(F.text)
async def knt_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knt_wait:
        raise SkipHandler
    cells = (await state.get_data())["cells"]
    try:
        cell = int(norm(message.text))
    except ValueError:
        await say(message, "Пиши номер клетки от 1 до 9, друк.", markup=knt_board(cells, "knt"))
        return
    idx = cell - 1
    if idx not in range(9):
        await say(message, "Клеток всего 9: от 1 до 9. Повтори, друк.", markup=knt_board(cells, "knt"))
        return
    if cells[idx]:
        await say(message, "Занято, друк. Выбери свободную клетку.", markup=knt_board(cells, "knt"))
        return
    cells[idx] = "X"
    w = knt_winner(cells)
    if w == "X":
        await state.clear()
        await say(message, knt_render(cells) + "\n\nТы победил, друк! Крестики — сила.", markup=replay_board("knt_again"))
        return
    if knt_full(cells):
        await state.clear()
        await say(message, knt_render(cells) + "\n\nНичья, друк. Ещё партию?", markup=replay_board("knt_again"))
        return
    bot = knt_best(cells, "O")
    cells[bot] = "O"
    w = knt_winner(cells)
    if w == "O":
        await state.clear()
        await say(message, knt_render(cells) + "\n\nБот победил, друк. Реванш?", markup=replay_board("knt_again"))
        return
    if knt_full(cells):
        await state.clear()
        await say(message, knt_render(cells) + "\n\nНичья, друк. Ещё партию?", markup=replay_board("knt_again"))
        return
    await state.update_data(cells=cells)
    await say(message, knt_render(cells) + "\n\nТвой ход, друк.", markup=knt_board(cells, "knt"))


@dp.message(F.text)
async def start_knt_two(message: Message, state: FSMContext):
    if norm(message.text) not in {"крестики-нолики на двоих", "кнт на двоих", "кнт вдвоём", "кнт2"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.knt_two_wait)
    await state.update_data(cells=[None] * 9, turn="X")
    cells = [None] * 9
    await say(message, f"{knt_render(cells)}\n\nИграем вдвоём, друки! X ходит первым — жмите клетку.", markup=knt_board(cells, "knt2"))


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
        await say(message, "Пиши номер клетки от 1 до 9, друки.", markup=knt_board(cells, "knt2"))
        return
    idx = cell - 1
    if idx not in range(9):
        await say(message, "Клеток всего 9: от 1 до 9. Повтори, друки.", markup=knt_board(cells, "knt2"))
        return
    if cells[idx]:
        await say(message, "Занято, друки. Выберите свободную клетку.", markup=knt_board(cells, "knt2"))
        return
    cells[idx] = turn
    w = knt_winner(cells)
    if w:
        await state.clear()
        await say(message, knt_render(cells) + f"\n\nПобеда {w}, друки!", markup=replay_board("knt2_again"))
        return
    if knt_full(cells):
        await state.clear()
        await say(message, knt_render(cells) + "\n\nНичья, друки!", markup=replay_board("knt2_again"))
        return
    nxt = "O" if turn == "X" else "X"
    await state.update_data(cells=cells, turn=nxt)
    await say(message, knt_render(cells) + f"\n\nТеперь ходит {nxt}, друки.", markup=knt_board(cells, "knt2"))


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
        + "\n\nЖми букву или пиши слово целиком, друк.",
        markup=hang_board([]),
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
        used = set(wrong) | {ch for ch, ok in zip(word, found) if ok}
        if all(found):
            await state.clear()
            await say(message, hangman_text(word, found, wrong, left) + f"\n\nОтгадал, друк! Слово: {word}.", markup=replay_board("hang_again"))
            return
        if left <= 0:
            await state.clear()
            await say(message, f"Без шансов, друк. Слово было: {word}. «виселица» — реванш.", markup=replay_board("hang_again"))
            return
        await state.update_data(found=found, wrong=wrong, left=left)
        await say(message, hangman_text(word, found, wrong, left) + "\n\nЕщё букву или слово целиком, друк.", markup=hang_board(used))
        return
    if not t or not t.isalpha():
        await say(message, "Пиши букву или слово, друк.", markup=hang_board(set(wrong)))
        return
    if t.lower() == word:
        await state.clear()
        await say(message, f"В яблочко, друк! Слово: {word}.", markup=replay_board("hang_again"))
        return
    left -= 1
    if left <= 0:
        await state.clear()
        await say(message, f"Не то слово, друк. Было: {word}. «виселица» — реванш.", markup=replay_board("hang_again"))
        return
    await state.update_data(left=left)
    await say(message, hangman_text(word, found, wrong, left) + "\n\nНе то слово, друк. Ещё вариант?", markup=hang_board(set(wrong)))


@dp.callback_query(F.data)
async def on_game_callback(query: CallbackQuery, state: FSMContext):
    data = query.data
    try:
        await _route_callback(query, state, data)
    except Exception:
        logging.exception("Callback error: %s", data)
    finally:
        await query.answer()


async def _route_callback(query: CallbackQuery, state: FSMContext, data: str):
    if data == "stop_game":
        await state.clear()
        await query.message.edit_text("Игра отменена, друк.")
        return

    if data.startswith("knb:"):
        move = data.split(":", 1)[1]
        bot_move = random.choice(list(SHAPES))
        if move == bot_move:
            result = "Ничья, друк. Ещё разок?"
        elif BEATS[move] == bot_move:
            result = "Ты победил, друк! Реванш, если слабо?"
        else:
            result = "Бот победил, друк. Партия-реванш?"
        await query.message.edit_text(f"Ты — {move}, бот — {bot_move}. {result}", reply_markup=replay_board("knb_again"))
        return

    if data == "knb_again":
        await state.set_state(GameStates.knb_wait)
        await query.message.edit_text("Камень, ножницы, бумага?", reply_markup=knb_board("knb"))
        return

    if data.startswith("knb2:"):
        if await state.get_state() != GameStates.knb_two_wait:
            await query.message.edit_text("Игра уже закончилась, друки. Начните заново.")
            return
        move = data.split(":", 1)[1]
        st = await state.get_data()
        moves = st.get("moves", [])
        if not moves:
            who = html.escape(query.from_user.username or query.from_user.full_name or "игрок")
            await state.update_data(moves=[(who, move)])
            await query.message.edit_text(f"{who} сыграл(а) {move}. Теперь второй жмёт ход.", reply_markup=knb_board("knb2"))
        else:
            first_name, first_move = moves[0]
            if first_move == move:
                result = "Ничья, друки!"
            elif BEATS[first_move] == move:
                result = f"Победа за {first_name}!"
            else:
                result = "Победа за отвечавшим!"
            await state.clear()
            await query.message.edit_text(
                f"{first_name}: {first_move} | Отвечающий: {move}. {result}",
                reply_markup=replay_board("knb2_again"),
            )
        return

    if data == "knb2_again":
        await state.set_state(GameStates.knb_two_wait)
        await state.update_data(moves=[])
        await query.message.edit_text("Играем вдвоём, друки! Первый жмёт ход.", reply_markup=knb_board("knb2"))
        return

    if data == "dice_again":
        user_roll = random.randint(1, 6)
        bot_roll = random.randint(1, 6)
        if user_roll > bot_roll:
            result = "Ты выиграл, друк! Кубик любит смелых."
        elif user_roll < bot_roll:
            result = "Бот выиграл, друк. Реванш?"
        else:
            result = "Ровно! Ничья, друк."
        await query.message.edit_text(
            f"🎲 Твой кубик: {user_roll}\n🎲 Кубик бота: {bot_roll}\n{result}",
            reply_markup=replay_board("dice_again"),
        )
        return

    if data.startswith("guess:"):
        if await state.get_state() != GameStates.guess_wait:
            await query.message.edit_text("Игра уже закончилась, друк.")
            return
        guess = int(data.split(":", 1)[1])
        secret = (await state.get_data())["secret"]
        if guess < secret:
            await query.message.edit_text("Маловато, друк. Пробуй выше.", reply_markup=guess_board())
        elif guess > secret:
            await query.message.edit_text("Перебор, друк. Пробуй меньше.", reply_markup=guess_board())
        else:
            await state.clear()
            await query.message.edit_text(f"Верно! Загадано было {secret}. Ты гений, друк!", reply_markup=replay_board("guess_again"))
        return

    if data == "guess_again":
        await state.set_state(GameStates.guess_wait)
        await state.update_data(secret=random.randint(1, 20))
        await query.message.edit_text("Я загадал число от 1 до 20. Жми вариант, друк.", reply_markup=guess_board())
        return

    if data.startswith("knt:"):
        if await state.get_state() != GameStates.knt_wait:
            await query.message.edit_text("Игра уже закончилась, друк.")
            return
        cells = (await state.get_data())["cells"]
        idx = int(data.split(":", 1)[1])
        if cells[idx]:
            await query.message.edit_text(knt_render(cells) + "\n\nЗанято, друк. Выбери свободную клетку.", reply_markup=knt_board(cells, "knt"))
            return
        cells[idx] = "X"
        w = knt_winner(cells)
        if w == "X":
            await state.clear()
            await query.message.edit_text(knt_render(cells) + "\n\nТы победил, друк! Крестики — сила.", reply_markup=replay_board("knt_again"))
            return
        if knt_full(cells):
            await state.clear()
            await query.message.edit_text(knt_render(cells) + "\n\nНичья, друк. Ещё партию?", reply_markup=replay_board("knt_again"))
            return
        bot_cell = knt_best(cells, "O")
        cells[bot_cell] = "O"
        w = knt_winner(cells)
        if w == "O":
            await state.clear()
            await query.message.edit_text(knt_render(cells) + "\n\nБот победил, друк. Реванш?", reply_markup=replay_board("knt_again"))
            return
        if knt_full(cells):
            await state.clear()
            await query.message.edit_text(knt_render(cells) + "\n\nНичья, друк. Ещё партию?", reply_markup=replay_board("knt_again"))
            return
        await state.update_data(cells=cells)
        await query.message.edit_text(knt_render(cells) + "\n\nТвой ход, друк.", reply_markup=knt_board(cells, "knt"))
        return

    if data == "knt_again":
        await state.set_state(GameStates.knt_wait)
        await state.update_data(cells=[None] * 9)
        cells = [None] * 9
        await query.message.edit_text(knt_render(cells) + "\n\nТы — X, я — O. Жми клетку.", reply_markup=knt_board(cells, "knt"))
        return

    if data.startswith("knt2:"):
        if await state.get_state() != GameStates.knt_two_wait:
            await query.message.edit_text("Игра уже закончилась, друки.")
            return
        st = await state.get_data()
        cells = st["cells"]
        turn = st["turn"]
        idx = int(data.split(":", 1)[1])
        if cells[idx]:
            await query.message.edit_text(knt_render(cells) + "\n\nЗанято, друки. Выберите свободную.", reply_markup=knt_board(cells, "knt2"))
            return
        cells[idx] = turn
        w = knt_winner(cells)
        if w:
            await state.clear()
            await query.message.edit_text(knt_render(cells) + f"\n\nПобеда {w}, друки!", reply_markup=replay_board("knt2_again"))
            return
        if knt_full(cells):
            await state.clear()
            await query.message.edit_text(knt_render(cells) + "\n\nНичья, друки!", reply_markup=replay_board("knt2_again"))
            return
        nxt = "O" if turn == "X" else "X"
        await state.update_data(cells=cells, turn=nxt)
        await query.message.edit_text(knt_render(cells) + f"\n\nТеперь ходит {nxt}, друки.", reply_markup=knt_board(cells, "knt2"))
        return

    if data == "knt2_again":
        await state.set_state(GameStates.knt_two_wait)
        await state.update_data(cells=[None] * 9, turn="X")
        cells = [None] * 9
        await query.message.edit_text(knt_render(cells) + "\n\nИграем вдвоём, друки! X ходит первым.", reply_markup=knt_board(cells, "knt2"))
        return

    if data.startswith("hang:"):
        if await state.get_state() != GameStates.hangman:
            await query.message.edit_text("Игра уже закончилась, друк.")
            return
        st = await state.get_data()
        word = st["word"]
        found = st["found"]
        wrong = st["wrong"]
        left = st["left"]
        letter = data.split(":", 1)[1]
        if letter in word:
            for i, ch in enumerate(word):
                if ch == letter:
                    found[i] = True
        elif letter not in wrong:
            wrong.append(letter)
            left -= 1
        used = set(wrong) | {ch for ch, ok in zip(word, found) if ok}
        if all(found):
            await state.clear()
            await query.message.edit_text(hangman_text(word, found, wrong, left) + f"\n\nОтгадал, друк! Слово: {word}.", reply_markup=replay_board("hang_again"))
            return
        if left <= 0:
            await state.clear()
            await query.message.edit_text(f"Без шансов, друк. Слово было: {word}.", reply_markup=replay_board("hang_again"))
            return
        await state.update_data(found=found, wrong=wrong, left=left)
        await query.message.edit_text(hangman_text(word, found, wrong, left) + "\n\nЖми букву или пиши слово целиком, друк.", reply_markup=hang_board(used))
        return

    if data == "hang_again":
        word = random.choice(HANGMAN_WORDS)
        await state.set_state(GameStates.hangman)
        await state.update_data(word=word, found=[False] * len(word), wrong=[], left=6)
        await query.message.edit_text(
            hangman_text(word, [False] * len(word), [], 6) + "\n\nЖми букву или пиши слово целиком, друк.",
            reply_markup=hang_board([]),
        )
        return

    if data.startswith("chk:"):
        if await state.get_state() != GameStates.checkers:
            await query.message.edit_text("Игра уже закончилась, друк.")
            return
        _, rs, cs = data.split(":")
        r, c = int(rs), int(cs)
        st = await state.get_data()
        board = st["board"]
        selected = st.get("selected")
        if selected is None:
            if board[r][c] in ("w", "wk"):
                dests = {m["squares"][-1] for m in legal_moves(board, "w") if m["squares"][0] == (r, c)}
                if not dests:
                    await query.message.edit_text(render(board) + "\n\nУ этой шашки нет хода, друк. Выбери другую.", reply_markup=chk_board(board))
                    return
                await state.update_data(selected=(r, c))
                await query.message.edit_text(
                    render(board, (r, c), dests) + "\n\nВыбрана шашка. «*» — куда можно. Жми цель.",
                    reply_markup=chk_board(board, (r, c), dests),
                )
            else:
                await query.message.edit_text(render(board) + "\n\nЭто не твоя шашка, друк. Выбери белую (⛀).", reply_markup=chk_board(board))
            return
        if (r, c) == selected:
            await state.update_data(selected=None)
            await query.message.edit_text(render(board) + "\n\nХод за тобой, друк.", reply_markup=chk_board(board))
            return
        if board[r][c] in ("w", "wk"):
            dests = {m["squares"][-1] for m in legal_moves(board, "w") if m["squares"][0] == (r, c)}
            if dests:
                await state.update_data(selected=(r, c))
                await query.message.edit_text(render(board, (r, c), dests) + "\n\nВыбрана шашка. Жми цель.", reply_markup=chk_board(board, (r, c), dests))
            else:
                await query.message.edit_text(render(board) + "\n\nУ этой шашки нет хода, друк.", reply_markup=chk_board(board))
            return
        sel_moves = [m for m in legal_moves(board, "w") if m["squares"][0] == selected]
        sel_cell = (r, c)
        if sel_cell in {m["squares"][-1] for m in sel_moves}:
            move = next(m for m in sel_moves if m["squares"][-1] == sel_cell)
            board = apply_move(board, "w", move)
            if piece_count(board, "b") == 0 or not legal_moves(board, "b"):
                await state.clear()
                await query.message.edit_text(render(board) + "\n\nТы выиграл, друк! Шашки — твоя стихия.", reply_markup=replay_board("chk_again"))
                return
            bot_move = choose_move(board, "b")
            if bot_move is None:
                await state.clear()
                await query.message.edit_text(render(board) + "\n\nБоту некуда ходить — ты выиграл, друк!", reply_markup=replay_board("chk_again"))
                return
            a, z = bot_move["squares"][0], bot_move["squares"][-1]
            board = apply_move(board, "b", bot_move)
            taken = len(bot_move["captured"])
            bot_text = f"{sq_name(*a)}-{sq_name(*z)}" + (f", взято {taken}" if taken else "")
            if piece_count(board, "w") == 0 or not legal_moves(board, "w"):
                await state.clear()
                await query.message.edit_text(render(board) + f"\n\nБот сходил: {bot_text}. Бот выиграл, друк. Реванш?", reply_markup=replay_board("chk_again"))
                return
            await state.update_data(board=board, selected=None)
            await query.message.edit_text(render(board) + f"\n\nБот сходил: {bot_text}. Твой ход.", reply_markup=chk_board(board))
            return
        sel_dests = {m["squares"][-1] for m in sel_moves}
        await query.message.edit_text(
            render(board, selected, sel_dests) + "\n\nТуда нельзя, друк. Жми «*» или свою шашку.",
            reply_markup=chk_board(board, selected, sel_dests),
        )
        return

    if data == "chk_again":
        board = start_board()
        await state.set_state(GameStates.checkers)
        await state.update_data(board=board)
        await query.message.edit_text(
            render(board) + "\n\nНовая партия! Ты белыми (⛀), твой ход.",
            reply_markup=chk_board(board),
        )
        return


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
    dp.message.middleware.register(TrackChats())
    await asyncio.gather(dp.start_polling(bot), media_loop())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
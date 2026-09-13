import asyncio
import glob
import html
import logging
import os
import random
import re
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
from Chess import (
    SYM as CH_SYM,
    start_board as ch_start_board,
    render as ch_render,
    apply_move as ch_apply,
    legal_moves as ch_legal,
    in_check as ch_in_check,
    status as ch_status,
    dests_for as ch_dests,
    promote as ch_promote,
    bot_move as ch_bot_move,
    is_draw as ch_is_draw,
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
    checkers_two = State()
    knt_wait = State()
    knt_two_wait = State()
    hangman = State()
    wordle = State()
    wordle_two = State()
    dice_wait = State()
    chess = State()
    chess_two = State()


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
    "шашки на двоих",
    "шашки вдвоём",
    "шашки с братаном",
    "шашки2",
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
    "wordle",
    "вордл",
    "вордли",
    "шахматы",
    "шахматы с ботом",
    "шахматы на двоих",
    "шахматы вдвоём",
    "шахматы2",
    "wordle на двоих",
    "wordle2",
    "вордл на двоих",
}
CANCEL_WORDS = {"стоп", "стоп игра", "выход", "отмена", "хватит"}

GAME_LIST = (
    "Наши игры, друк:\n"
    "• <b>кнб</b> — камень-ножницы-бумага против бота\n"
    "• <b>кнб на двоих</b> — камень-ножницы-бумага вдвоём\n"
    "• <b>кости</b> — бросаем кубики против бота\n"
    "• <b>угадай число</b> — отгадай число от 1 до 20\n"
    "• <b>шашки</b> — партия против бота (жми шашку, потом клетку хода)\n"
    "• <b>шашки на двоих</b> — вдвоём на одной доске, даже с разных устройств в одной группе\n"
    "• <b>кнт</b> — крестики-нолики против бота; на двоих: «кнт на двоих»\n"
    "• <b>виселица</b> — угадай слово по буквам\n"
    "• <b>wordle</b> — угадай слово от 4 до 13 букв (длину выбираешь кнопками, за 6 попыток); на двоих: «wordle на двоих»\n"
    "• <b>шахматы</b> — сыграй с ботом (ты белыми); на двоих: «шахматы на двоих»\n"
    "Всё играется кнопками. Напиши название игры, чтобы начать. Выйти — «стоп»."
)


def norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def pick_response(response):
    if isinstance(response, (list, tuple)):
        return random.choice(response)
    return response


def tokenize(text: str):
    return re.findall(r"[а-яёa-z0-9]+", text.lower())


def text_has_phrase(tokens, phrase):
    phrase = [p for p in phrase if p]
    if not phrase:
        return False
    if len(phrase) == 1:
        return phrase[0] in tokens
    for i in range(len(tokens) - len(phrase) + 1):
        if tokens[i : i + len(phrase)] == phrase:
            return True
    return False


def find_response(text: str):
    tokens = tokenize(text)
    for trigger, response in TRIGGERS.items():
        if text_has_phrase(tokens, tokenize(trigger)):
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
    if ACTIVE_CHATS and random.random() < 0.20:
        try:
            await send_media_to_chat(message.chat.id)
        except Exception:
            logging.exception("Не смог отправить кота вместе с ответом")


async def bind_player(state, uid, max_players=1):
    st = await state.get_data()
    players = st.get("players") or []
    if uid in players:
        return True
    if len(players) >= max_players:
        return False
    await state.update_data(players=players + [uid])
    return True


async def ensure_players(state, uid, max_players=2):
    st = await state.get_data()
    players = st.get("players") or []
    if uid and uid not in players and len(players) < max_players:
        await state.update_data(players=players + [uid])


def msg_uid(message):
    return getattr(message.from_user, "id", None) or 0


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


def chk_board(board, selected=None, dests=None, prefix="chk") -> InlineKeyboardMarkup:
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
            row.append(btn(label, f"{prefix}:{r}:{c}"))
        rows.append(row)
    rows.append([btn("Сдаться", "stop_game")])
    return kb(rows)


def chm_board(board, prefix: str = "chm") -> InlineKeyboardMarkup:
    rows = []
    for r in range(8):
        row = []
        for c in range(8):
            label = CH_SYM.get(board[r][c], "·")
            row.append(btn(label, f"{prefix}:{r}:{c}"))
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

WORDLE_WORDS_BY_LEN = {
    4: [
        "атом", "беда", "вера", "вино", "волк", "враг", "жара", "зима",
        "каша", "ключ", "конь", "лиса", "луна", "мыло", "морс", "мост",
        "мука", "небо", "ночь", "окно", "осел", "пена", "пень", "пиво",
        "пила", "поле", "пора", "путь", "река", "роса", "рука", "сало",
        "сено", "сила", "соль", "соус", "стул", "тень", "тигр", "торт",
        "туча", "утро", "флаг", "хвоя", "цвет", "шуба", "юмор", "язык",
    ],
    5: [
        "абзац", "акула", "афиша", "багаж", "банан", "батон", "берег", "билет",
        "бочка", "брюки", "булка", "буква", "вагон", "вафля", "весло", "ветка",
        "вечер", "вилка", "вишня", "ворот", "вьюга", "гараж", "дверь", "дефис",
        "дождь", "дрова", "забор", "закат", "канал", "капля", "кобра", "ковер",
        "кокос", "комар", "короб", "котел", "крыша", "кулак", "лавка", "ладон",
        "лампа", "лента", "лимон", "ложка", "майка", "маска", "метла", "мешок",
        "молот", "мороз", "музей", "насос", "невод", "носки", "обман", "обувь",
        "овраг", "окунь", "орден", "осень", "палец", "парта", "пирог", "пламя",
        "порог", "поход", "поэма", "радио", "ранец", "рынок", "салат", "салют",
        "сахар", "север", "сироп", "скала", "сосна", "спорт", "судно", "табло",
        "тапки", "тачка", "театр", "тепло", "тесто", "топор", "трава", "труба",
        "туман", "тумба", "удача", "уксус", "улица", "фильм", "фокус", "фраза",
        "хвост", "химия", "холст", "чашка", "чугун", "шапка", "шахта", "шляпа",
        "штора", "щепка",
    ],
    6: [
        "абажур", "аврора", "акация", "амфора", "анкета", "аптека", "баллон",
        "береза", "бирюза", "воздух", "вокзал", "восход", "газета", "горсть",
        "глобус", "гнездо", "гранит", "дракон", "дюжина", "железо", "жемчуг",
        "журнал",
        "звезда", "зигзаг", "кабина", "камера", "карман", "качели", "клетка",
        "климат", "клумба", "кнопка", "коврик", "колдун", "компас", "корона",
        "корыто", "костюм", "краска", "кувшин", "куртка", "лавина", "лагуна",
        "лебедь", "лопата", "лошадь", "люстра", "малина", "медаль", "минута",
        "молоко", "монета", "низина", "номера", "облако", "одеяло", "оливка",
        "осадки", "павлин", "пальма", "панама", "парник", "пастух", "патрон",
        "пенсия", "перрон", "планка", "погода", "посуда", "правда", "призма",
        "ракета", "рельсы", "свитер", "сердце", "синяки", "скамья", "соболь",
        "стакан", "статуя", "стекло", "супруг", "тишина", "тормоз", "турнир",
        "уборка", "указка", "фасоль", "фаэтон", "фигура", "фонарь", "фонтан",
        "цветок", "чайник", "шедевр", "щетина", "ястреб",
    ],
    7: [
        "автомат", "баранка", "бассейн", "бегемот", "бильярд", "бинокль",
        "варежка", "ветчина", "водопой", "воронка", "воробей",
        "журавль", "загадка", "занавес", "записка", "звонарь", "зоопарк",
        "игрушка", "иллюзия", "калитка", "капуста", "карьера", "кипяток",
        "клавиша", "комната", "конверт", "копейка", "коробка", "котлета",
        "крапива", "кровать", "крыльцо", "лукошко", "лунатик", "любимый",
        "медовик", "молоток", "мышонок", "награда", "надписи", "накидка",
        "невеста", "новость", "облачко", "обложка", "оборона", "окрошка",
        "орленок", "палатка", "палитра", "пантера", "парашют", "плинтус",
        "подкова", "подушка", "подъезд", "помидор", "посылка", "правила",
        "провода", "пылесос", "разлука", "рассвет", "ребенок", "редиска",
        "ресницы", "рисунок", "ромашка", "рубашка", "сарафан", "свисток",
        "секунда", "семинар", "сержант", "скворец", "складка", "скрипка",
        "славный", "сметана", "снегирь", "спальня", "стадион", "студень",
        "сувенир", "сюрприз", "телефон", "темнота", "терапия", "тетрадь",
        "торнадо", "трактор", "трибуна", "упряжка", "хвостик", "чемпион",
        "черника", "шоколад", "ящерица",
    ],
    8: [
        "антилопа", "апельсин", "баклажан", "виноград", "грибочек", "грузовик",
        "дикобраз", "дождевик", "закладка", "картошка", "карусель", "кастрюля",
        "километр", "клубника", "королева", "крокодил", "крышечка", "кузнечик",
        "модистка", "морковка", "обезьяна", "осьминог", "пирамида", "пирожное",
        "пистолет", "поплавок", "портфель", "праздник", "пригород", "проблема",
        "пуговица", "разговор", "ресторан", "скорпион", "снеговик", "спальник",
        "спортзал", "страница", "стрекоза", "торговля", "трамплин", "трапеция",
        "туфелька", "футболка", "хлопушка", "хоккеист", "хрусталь", "цветочек",
        "чаепитие", "школьник",
    ],
    9: [
        "аккуратно", "баскетбол", "бутерброд", "велосипед",
        "волшебник", "замечание", "звездочка", "земляника", "календарь",
        "канарейка", "компьютер", "малиновка", "маленький", "маршрутка",
        "небоскреб", "олимпиада", "пантомима", "пластилин", "принцесса",
        "репетиция", "рисование", "рукавичка", "самолетик", "сантиметр",
        "светлячок", "смородина", "сокровище", "солнечный", "стремянка",
        "табуретка", "телевизор", "термометр", "транспорт", "тяжеловес",
        "чебурашка", "шоколадка", "эскалатор",
    ],
    10: [
        "автомобиль", "воспитание", "наводнение", "облачность", "парикмахер",
        "подорожник", "противогаз", "разделение", "расписание", "скороварка",
        "сладкоежка", "соединение", "сокращение", "экскаватор",
    ],
    11: [
        "вдохновение", "впечатление", "изобретение", "конструктор",
        "понедельник", "приветствие", "приключение", "путешествие",
        "температура", "университет", "уничтожение", "холодильник",
        "цивилизация",
    ],
    12: [
        "библиотекарь", "велосипедист", "оборудование", "пододеяльник",
        "поздравление",
    ],
    13: [
        "благодарность", "микроволновка", "представление", "расследование",
        "свидетельство", "строительство", "электричество",
    ],
}


def word_of_len(n):
    words = WORDLE_WORDS_BY_LEN.get(n) or []
    return random.choice(words) if words else None


def wordle_feedback(guess, word):
    res = ["⬛"] * len(guess)
    counts = {}
    for ch in word:
        counts[ch] = counts.get(ch, 0) + 1
    for i, (g, s) in enumerate(zip(guess, word)):
        if g == s:
            res[i] = "🟩"
            counts[g] -= 1
    for i, (g, s) in enumerate(zip(guess, word)):
        if g != s and counts.get(g, 0) > 0:
            res[i] = "🟨"
            counts[g] -= 1
    return "".join(res)


def wordle_view(guesses, word):
    return "\n".join(f"{i}. {html.escape(g)} {wordle_feedback(g, word)}" for i, g in enumerate(guesses, 1))


def is_word_n(t, n):
    return len(t) == n and all(ch in LETTERS for ch in t)


def mask_word(word, found):
    return " ".join(ch if ok else "•" for ch, ok in zip(word, found))


def hangman_text(word, found, wrong, left):
    return (
        f"Слово: {mask_word(word, found)}\n"
        f"Попыток осталось: {left}\n"
        f"Неверные: {', '.join(wrong) if wrong else '—'}"
    )


ACTIVE_CHATS: set = set()
LOBBIES: dict = {}

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


async def send_media_to_chat(chat_id):
    media = random_media()
    if media is None:
        logging.info("Нет медиа в папке %s — пропускаю рассылку.", MEDIA_DIR)
        return
    if media.lower().endswith((".gif", ".mp4")):
        await bot.send_animation(chat_id, FSInputFile(media))
    else:
        await bot.send_photo(chat_id, FSInputFile(media))
    logging.info("Отправил медиа %s в чат %s", media, chat_id)


async def send_random_media():
    if not ACTIVE_CHATS:
        return
    chat_id = random.choice(list(ACTIVE_CHATS))
    await send_media_to_chat(chat_id)


async def media_loop():
    base = int(os.environ.get("MEDIA_MINUTES", "35"))
    if base <= 0:
        logging.info("MEDIA_MINUTES=0 — рассылка медиа отключена.")
        return
    low = max(int(base * 0.7), 15)
    high = max(int(base * 1.3), 30)
    while True:
        await asyncio.sleep(random.randint(low, high) * 60)
        try:
            await send_random_media()
        except Exception:
            logging.exception("media_loop error")


MEDIA_STOP_WORDS = {"скинь фото", "фото", "фотку", "гиф", "гифку", "картинку", "пришли фото"}

MAT_WORDS = {
    "бля", "блядь", "бляди", "блядский",
    "хуй", "хуя", "хуи", "нахуй", "нахуя", "похуй", "хуевый",
    "пизда", "пиздец", "пизды",
    "ебать", "ебало", "ебло", "еблан", "ебаный", "уебан", "уебать", "уебок", "заебал", "заебало", "заебись",
    "пидор", "пидр", "пидорас", "пидарас",
    "мудак", "мудаки", "мудило", "мудила",
    "залупа", "гандон", "гондон", "мразь", "ублюдок", "шлюха",
    "дебил", "дебилы", "даун", "дауны", "кретин", "конченый", "дерьмо",
}


@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    await say(message, "Привет, друк! Я Друк-бот v1.3." + GAME_LIST)


@dp.message(F.text)
async def mat_block(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        raise SkipHandler
    words = {w.replace("ё", "е") for w in tokenize(message.text)}
    if not (words & MAT_WORDS):
        raise SkipHandler
    await say(message, "Эй, друк, не пиши такое при мне 🙂")


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
    await state.update_data(players=[msg_uid(message)])
    await say(message, "Камень, ножницы, бумага?", markup=knb_board("knb"))


@dp.message(F.text)
async def knb_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knb_wait:
        raise SkipHandler
    if not await bind_player(state, msg_uid(message), max_players=1):
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
    LOBBIES[message.chat.id] = {"host": msg_uid(message), "kind": "knb2"}
    await say(message, "🎮 КНБ вдвоём!\nЖдём второго игрока, друк. Второй жми «Вступить».", markup=lobby_kb("knb2"))


@dp.message(F.text)
async def knb_two_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knb_two_wait:
        raise SkipHandler
    if not await bind_player(state, msg_uid(message), max_players=2):
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
    await state.set_state(GameStates.dice_wait)
    await state.update_data(players=[msg_uid(message)])
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
    await state.update_data(secret=random.randint(1, 20), players=[msg_uid(message)])
    await say(message, "Я загадал число от 1 до 20. Жми вариант, друк.", markup=guess_board())


@dp.message(F.text)
async def guess_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.guess_wait:
        raise SkipHandler
    if not await bind_player(state, msg_uid(message), max_players=1):
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
    await state.update_data(board=board, players=[msg_uid(message)])
    await say(
        message,
        render(board)
        + "\n\nТы играешь белыми (⛀) и ходишь первым. Жми свою шашку, потом клетку — куда сходить. Или пиши ход текстом: e3-d4. «стоп» — выйти.",
        markup=chk_board(board),
    )


@dp.message(F.text)
async def start_checkers_two(message: Message, state: FSMContext):
    if norm(message.text) not in {"шашки на двоих", "шашки вдвоём", "шашки с братаном", "шашки2"}:
        raise SkipHandler
    await state.clear()
    LOBBIES[message.chat.id] = {"host": msg_uid(message), "kind": "chk2"}
    await say(message, "🎮 Шашки вдвоём!\nЖдём второго игрока, друк. Второй жми «Вступить».", markup=lobby_kb("chk2"))


@dp.message(F.text)
async def start_chess(message: Message, state: FSMContext):
    if norm(message.text) not in {"шахматы", "шахматы с ботом"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.chess)
    board = ch_start_board()
    await state.update_data(board=board, ep=None, cast="KQkq", sel=None, dests=[], players=[msg_uid(message)])
    await say(
        message,
        "Шахматы! Ты играешь белыми. Жми свою фигуру, потом клетку хода."
        + "\n\n"
        + ch_render(board),
        markup=chm_board(board, "chm"),
    )


@dp.message(F.text)
async def start_chess_two(message: Message, state: FSMContext):
    if norm(message.text) not in {"шахматы на двоих", "шахматы вдвоём", "шахматы2"}:
        raise SkipHandler
    await state.clear()
    LOBBIES[message.chat.id] = {"host": msg_uid(message), "kind": "chm2"}
    await say(message, "♞ Шахматы вдвоём!\nЖдём второго игрока, друк. Второй жми «Вступить».", markup=lobby_kb("chm2"))


@dp.message(F.text)
async def checkers_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.checkers:
        raise SkipHandler
    if not await bind_player(state, msg_uid(message), max_players=1):
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
    await state.update_data(cells=[None] * 9, players=[msg_uid(message)])
    cells = [None] * 9
    await say(message, f"{knt_render(cells)}\n\nТы — X, я — O. Жми клетку.", markup=knt_board(cells, "knt"))


@dp.message(F.text)
async def knt_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knt_wait:
        raise SkipHandler
    if not await bind_player(state, msg_uid(message), max_players=1):
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
    LOBBIES[message.chat.id] = {"host": msg_uid(message), "kind": "knt2"}
    await say(message, "🎮 КНТ вдвоём!\nЖдём второго игрока, друк. Второй жми «Вступить».", markup=lobby_kb("knt2"))


@dp.message(F.text)
async def knt_two_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.knt_two_wait:
        raise SkipHandler
    if not await bind_player(state, msg_uid(message), max_players=2):
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
    await state.update_data(word=word, found=[False] * len(word), wrong=[], left=6, players=[msg_uid(message)])
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
    if not await bind_player(state, msg_uid(message), max_players=1):
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


def stop_kb() -> InlineKeyboardMarkup:
    return kb([[btn("Сдаться", "stop_game")]])


def lobby_kb(kind: str) -> InlineKeyboardMarkup:
    return kb([[btn("Вступить", f"lobby:{kind}")], [btn("Отмена", "stop_game")]])


def length_kb() -> InlineKeyboardMarkup:
    rows = [[btn(str(n), f"wlen:{n}") for n in range(4, 10)]]
    rows.append([btn(str(n), f"wlen:{n}") for n in range(10, 14)])
    rows.append([btn("Отмена", "stop_game")])
    return kb(rows)


def word_build_kb(n, draft) -> InlineKeyboardMarkup:
    rows = []
    cols = 7
    for i in range(0, len(LETTERS), cols):
        rows.append([btn(ch, f"wl2:{ch}") for ch in LETTERS[i : i + cols]])
    rows.append([btn("Готово", "wl2:ok"), btn("Сбросить", "wl2:clr")])
    rows.append([btn("Отмена", "stop_game")])
    return kb(rows)


TWO_PLAYER_STATES = {
    "knb2": GameStates.knb_two_wait,
    "knt2": GameStates.knt_two_wait,
    "chk2": GameStates.checkers_two,
    "wordle2": GameStates.wordle_two,
    "chm2": GameStates.chess_two,
}


def lobby_payload(kind: str):
    if kind == "knb2":
        return "Играем вдвоём, друки! Первый жмёт свой ход.", knb_board("knb2")
    if kind == "knt2":
        cells = [None] * 9
        return f"{knt_render(cells)}\n\nИграем вдвоём, друки! X ходит первым.", knt_board(cells, "knt2")
    if kind == "chk2":
        board = start_board()
        return (
            render(board)
            + "\n\nИграем вдвоём! Белые (⛀) ходят первыми, затем чёрные (⛂). Жми свою шашку, потом клетку хода.",
            chk_board(board, prefix="chk2"),
        )
    if kind == "wordle2":
        return (
            "Играем вдвоём! Загадывающий жмёт кнопку с длиной слова, потом собирает его буквами — "
            "покажу скрыто, чтобы не подсматривали. Угадывающий будет писать варианты.",
            length_kb(),
        )
    if kind == "chm2":
        board = ch_start_board()
        return (
            ch_render(board)
            + "\n\nИграем в шахматы вдвоём! Хост — белые (♔), второй — чёрные (♚). "
            "Жми свою фигуру, потом клетку хода. Ходят по очереди.",
            chm_board(board, "chm2"),
        )
    return None, None


async def chess_tap(query: CallbackQuery, state: FSMContext, prefix: str, r: int, c: int):
    two = prefix == "chm2"
    if await state.get_state() != (GameStates.chess_two.state if two else GameStates.chess.state):
        await query.message.edit_text("Игра уже закончилась, друк.")
        return
    uid = getattr(query.from_user, "id", None) or 0
    st = await state.get_data()
    b = st["board"]
    ep = st.get("ep")
    cast = st.get("cast") or "KQkq"
    sel = st.get("sel")
    dests = set(st.get("dests") or [])
    turn = st.get("turn") or "w"
    players = st.get("players") or []

    if two:
        holder = players[0] if turn == "w" else (players[1] if len(players) > 1 else None)
        if uid != holder:
            await query.answer()
            return

    piece = b[r][c]
    mine = bool(piece) and piece.isupper() == (turn == "w")
    again = "chm2_again" if two else "chm_again"

    if (r, c) == sel:
        await state.update_data(sel=None, dests=[])
        await query.message.edit_text(ch_render(b) + "\n\nВыбор снят, друк.", reply_markup=chm_board(b, prefix))
        return

    if mine:
        d = ch_dests(b, (r, c), turn, ep, cast)
        if not d:
            await query.message.edit_text(ch_render(b) + "\n\nЭта фигура не может ходить, друк.", reply_markup=chm_board(b, prefix))
            return
        await state.update_data(sel=(r, c), dests=sorted(list(d)))
        await query.message.edit_text(ch_render(b, selected=(r, c), dests=d) + "\n\nЖми клетку хода.", reply_markup=chm_board(b, prefix))
        return

    if sel and (r, c) in dests:
        nb, ep2, cast2 = ch_apply(b, sel, (r, c), ep, cast)
        ch_promote(nb, turn)
        nturn = "b" if turn == "w" else "w"
        st_res = ch_status(nb, nturn, ep2, cast2)
        if st_res[0] == "checkmate":
            await state.clear()
            who = "Ты выиграл" if turn == "w" else ("Чёрные выиграли" if two else "Бот выиграл")
            await query.message.edit_text(ch_render(nb) + f"\n\nШах и мат, друк! {who}.", reply_markup=replay_board(again))
            return
        if st_res[0] == "stalemate":
            await state.clear()
            await query.message.edit_text(ch_render(nb) + "\n\nПат — ничья, друк.", reply_markup=replay_board(again))
            return
        if ch_is_draw(nb, nturn):
            await state.clear()
            await query.message.edit_text(ch_render(nb) + "\n\nНичья: сил почти не осталось, друк.", reply_markup=replay_board(again))
            return

        if not two:
            bmove = ch_bot_move(nb, ep2, cast2)
            if bmove is None:
                await state.clear()
                await query.message.edit_text(ch_render(nb) + "\n\nШах и мат, друк! Ты выиграл.", reply_markup=replay_board("chm_again"))
                return
            nb, ep2, cast2 = ch_apply(nb, (bmove[0], bmove[1]), (bmove[2], bmove[3]), ep2, cast2)
            ch_promote(nb, "b")
            st_res = ch_status(nb, "w", ep2, cast2)
            add = "Бот сходил."
            if ch_in_check(nb, "w"):
                add += " Шах тебе, друк!"
            if st_res[0] == "checkmate":
                await state.clear()
                await query.message.edit_text(ch_render(nb) + "\n\nШах и мат, друк. Бот выиграл.", reply_markup=replay_board("chm_again"))
                return
            if st_res[0] == "stalemate":
                await state.clear()
                await query.message.edit_text(ch_render(nb) + "\n\nПат — ничья, друк.", reply_markup=replay_board("chm_again"))
                return
            if ch_is_draw(nb, "w"):
                await state.clear()
                await query.message.edit_text(ch_render(nb) + "\n\nНичья: сил почти не осталось, друк.", reply_markup=replay_board("chm_again"))
                return
            await state.update_data(board=nb, ep=ep2, cast=cast2, sel=None, dests=[])
            await query.message.edit_text(ch_render(nb) + "\n\n" + add, reply_markup=chm_board(nb, "chm"))
            return

        who = "Белые" if nturn == "w" else "Чёрные"
        extra = " Шах!" if ch_in_check(nb, nturn) else ""
        await state.update_data(board=nb, ep=ep2, cast=cast2, sel=None, dests=[], turn=nturn)
        await query.message.edit_text(ch_render(nb) + f"\n\nХод {who}.{extra}", reply_markup=chm_board(nb, "chm2"))
        return

    await query.answer()


@dp.message(F.text)
async def start_wordle(message: Message, state: FSMContext):
    if norm(message.text).lower() not in {"wordle", "вордл", "вордли", "вордле"}:
        raise SkipHandler
    await state.clear()
    await state.set_state(GameStates.wordle)
    await state.update_data(word=None, length=None, guesses=[], attempts=0, players=[msg_uid(message)])
    await say(message, "Wordle, друк! Сколько букв загадываю? Жми кнопку.", markup=length_kb())


@dp.message(F.text)
async def wordle_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.wordle:
        raise SkipHandler
    if not await bind_player(state, msg_uid(message), max_players=1):
        raise SkipHandler
    data = await state.get_data()
    word = data.get("word")
    if word is None:
        await say(message, "Выбери длину слова кнопками, друк.", markup=length_kb())
        return
    t = norm(message.text).lower()
    if not is_word_n(t, len(word)):
        await say(message, f"Пиши слово ровно из {len(word)} букв, друк.", markup=stop_kb())
        return
    guesses = data["guesses"]
    attempts = data["attempts"] + 1
    guesses.append(t)
    if t == word:
        await state.clear()
        await say(message, wordle_view(guesses, word) + "\n\nВ яблочко, друк! Ты отгадал!", markup=replay_board("word_again"))
        return
    if attempts >= 6:
        await state.clear()
        await say(message, wordle_view(guesses, word) + f"\n\nПопытки кончились, друк. Слово было: {html.escape(word)}.", markup=replay_board("word_again"))
        return
    await state.update_data(guesses=guesses, attempts=attempts)
    await say(
        message,
        wordle_view(guesses, word) + f"\n\nОсталось попыток: {6 - attempts}.",
        markup=stop_kb(),
    )


@dp.message(F.text)
async def start_wordle_two(message: Message, state: FSMContext):
    if norm(message.text).lower() not in {"wordle на двоих", "wordle2", "вордл на двоих", "вордле на двоих"}:
        raise SkipHandler
    await state.clear()
    LOBBIES[message.chat.id] = {"host": msg_uid(message), "kind": "wordle2"}
    await say(message, "🎮 Wordle вдвоём!\nЖдём второго игрока, друк. Второй жми «Вступить».", markup=lobby_kb("wordle2"))


@dp.message(F.text)
async def wordle_two_move(message: Message, state: FSMContext):
    if await state.get_state() != GameStates.wordle_two:
        raise SkipHandler
    await ensure_players(state, msg_uid(message))
    data = await state.get_data()
    if data.get("building"):
        await say(message, "Слово сейчас собирается кнопками, друк. Подожди.")
        return
    word = data.get("word")
    if word is None:
        await say(message, "Загадывающий ещё не собрал слово, друк. Ждём кнопки.")
        return
    t = norm(message.text).lower()
    if not is_word_n(t, len(word)):
        await say(message, f"Пиши слово ровно из {len(word)} букв, друк.", markup=stop_kb())
        return
    guesses = data["guesses"]
    attempts = data["attempts"] + 1
    guesses.append(t)
    if t == word:
        await state.clear()
        await say(message, wordle_view(guesses, word) + f"\n\nУгадал(а) {player_name(message)}, друк! Загадывал(а): {data['setter']}.", markup=replay_board("word2_again"))
        return
    if attempts >= 6:
        await state.clear()
        await say(message, wordle_view(guesses, word) + f"\n\nПопытки кончились, друк. Слово было: {html.escape(word)}. Загадывал(а): {data['setter']}.", markup=replay_board("word2_again"))
        return
    await state.update_data(guesses=guesses, attempts=attempts)
    await say(message, wordle_view(guesses, word) + f"\n\nОсталось попыток: {6 - attempts}.", markup=stop_kb())


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
    uid = getattr(query.from_user, "id", None) or 0
    cur = await state.get_state()
    two_p = data.startswith(("knb2:", "knt2:", "chk2:", "chm2:"))
    players = []
    if cur is not None:
        st = await state.get_data()
        players = st.get("players") or []
        if players and uid and uid not in players:
            if (two_p and len(players) < 2) or data.startswith("lobby:"):
                pass
            else:
                await query.answer()
                return

    if data == "stop_game":
        chat_id = getattr(getattr(query.message, "chat", None), "id", None)
        LOBBIES.pop(chat_id, None)
        await state.clear()
        await query.message.edit_text("Игра отменена, друк.")
        return

    if data.startswith(("chm:", "chm2:")):
        prefix, rc = data.split(":", 1)
        try:
            r, c = map(int, rc.split(":"))
        except ValueError:
            return
        await chess_tap(query, state, prefix, r, c)
        return

    if data.startswith("wlen:"):
        try:
            n = int(data.split(":", 1)[1])
        except ValueError:
            return
        if n not in range(4, 14):
            return
        if cur == GameStates.wordle.state:
            word = word_of_len(n)
            if word is None:
                await query.message.edit_text("Для такой длины слов пока нет, друк. Выбери другую:", reply_markup=length_kb())
                return
            await state.update_data(word=word, length=n, guesses=[], attempts=0)
            await query.message.edit_text(
                f"Загадал слово из {n} букв, друк. У тебя 6 попыток. Пиши вариант!\n🟩 верная буква, 🟨 есть в слове, ⬛ нет.",
                reply_markup=stop_kb(),
            )
            return
        if cur == GameStates.wordle_two.state:
            st = await state.get_data()
            if st.get("building"):
                await query.answer()
                return
            await state.update_data(length=n, building=True, draft=[], setter=uid)
            await query.message.edit_text(
                f"Загадывающий, собирай слово из {n} букв кнопками. Я показываю его скрыто — остальным не видно.",
                reply_markup=word_build_kb(n, []),
            )
            return
        await query.message.edit_text("Игра уже закончилась, друк.")
        return

    if data.startswith("wl2:"):
        if cur != GameStates.wordle_two.state:
            await query.message.edit_text("Игра уже закончилась, друк.")
            return
        st = await state.get_data()
        if not st.get("building"):
            await query.answer()
            return
        if uid != st.get("setter"):
            await query.answer()
            return
        arg = data.split(":", 1)[1]
        draft = st.get("draft") or []
        n = st.get("length") or 5
        if arg == "ok":
            if len(draft) != n:
                await query.message.edit_text(f"В слове {n} букв, сейчас {len(draft)}. Добавь или сбрось:", reply_markup=word_build_kb(n, draft))
                return
            word = "".join(draft)
            await state.update_data(building=False, word=word)
            await query.message.edit_text(
                f"Слово записано (скрыто, не открывай!): <tg-spoiler>{html.escape(word)}</tg-spoiler>\nУгадывающий, пиши слово из {n} букв!",
                reply_markup=stop_kb(),
            )
            return
        if arg == "clr":
            await state.update_data(draft=[])
            await query.message.edit_text(f"Загадывающий, слово из {n} букв. Жми буквы:", reply_markup=word_build_kb(n, []))
            return
        ch = arg
        if ch not in LETTERS:
            return
        if len(draft) >= n:
            await query.message.edit_text(f"В слове уже {n} букв, друк. Жми «Готово» или «Сбросить».", reply_markup=word_build_kb(n, draft))
            return
        draft = draft + [ch]
        await state.update_data(draft=draft)
        current = "".join(draft)
        hidden = f"<tg-spoiler>{html.escape(current)}</tg-spoiler>" if current else "<tg-spoiler>…</tg-spoiler>"
        await query.message.edit_text(
            f"Загадывающий, слово из {n} букв ({len(draft)}/{n}). Твоё слово: {hidden}. Жми буквы:",
            reply_markup=word_build_kb(n, draft),
        )
        return

    if data.startswith("lobby:"):
        kind = data.split(":", 1)[1]
        if cur is not None and cur in {s.state for s in TWO_PLAYER_STATES.values()}:
            await query.message.edit_text("Игра уже идёт, друк. Дождись конца партии.")
            return
        chat_id = getattr(getattr(query.message, "chat", None), "id", None)
        lobby = LOBBIES.get(chat_id) or {}
        if lobby.get("kind") != kind:
            await query.message.edit_text("Это приглашение уже не действует, друк. Напиши игру заново.")
            return
        if uid == lobby.get("host"):
            await query.answer()
            return
        host_id = lobby["host"]
        LOBBIES.pop(chat_id, None)
        await state.clear()
        await state.set_state(TWO_PLAYER_STATES[kind])
        players = [host_id, uid]
        if kind == "knb2":
            await state.update_data(players=players, moves=[])
        elif kind == "knt2":
            await state.update_data(players=players, cells=[None] * 9, turn="X")
        elif kind == "chk2":
            await state.update_data(players=players, board=start_board(), turn="w", owners={})
        elif kind == "wordle2":
            await state.update_data(players=players, word=None, guesses=[], attempts=0, setter=None)
        elif kind == "chm2":
            await state.update_data(players=players, board=ch_start_board(), ep=None, cast="KQkq", sel=None, dests=[], turn="w")
        text, markup = lobby_payload(kind)
        await query.message.edit_text(text, reply_markup=markup)
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
        await state.update_data(players=[uid])
        await query.message.edit_text("Камень, ножницы, бумага?", reply_markup=knb_board("knb"))
        return

    if data.startswith("knb2:"):
        if await state.get_state() != GameStates.knb_two_wait:
            await query.message.edit_text("Игра уже закончилась, друки. Начните заново.")
            return
        await ensure_players(state, uid)
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
        await state.update_data(players=[uid], moves=[])
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
        await state.update_data(secret=random.randint(1, 20), players=[uid])
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
        await state.update_data(cells=[None] * 9, players=[uid])
        cells = [None] * 9
        await query.message.edit_text(knt_render(cells) + "\n\nТы — X, я — O. Жми клетку.", reply_markup=knt_board(cells, "knt"))
        return

    if data.startswith("knt2:"):
        if await state.get_state() != GameStates.knt_two_wait:
            await query.message.edit_text("Игра уже закончилась, друки.")
            return
        await ensure_players(state, uid)
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
        await state.update_data(cells=[None] * 9, turn="X", players=[uid])
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
        await state.update_data(word=word, found=[False] * len(word), wrong=[], left=6, players=[uid])
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

    if data.startswith("chk2:"):
        if await state.get_state() != GameStates.checkers_two:
            await query.message.edit_text("Игра уже закончилась, друки.")
            return
        _, rs, cs = data.split(":")
        r, c = int(rs), int(cs)
        await ensure_players(state, uid)
        st = await state.get_data()
        board = st["board"]
        turn = st["turn"]
        owners = st.get("owners", {})
        color = turn
        pieces = (color, color + "k")
        other = "b" if color == "w" else "w"
        owner = owners.get(color)
        who = html.escape(query.from_user.username or query.from_user.full_name or "игрок")
        if color not in owners:
            owners[color] = who
        turn_note = f"Ходят {SYMBOLS['w' if color == 'w' else 'b']} {owners[color]}."
        selected = st.get("selected")
        if selected is None:
            if board[r][c] in pieces:
                dests = {m["squares"][-1] for m in legal_moves(board, color) if m["squares"][0] == (r, c)}
                if not dests:
                    await query.message.edit_text(render(board) + f"\n\nУ этой шашки нет хода, друк. Выбери другую.\n{turn_note}", reply_markup=chk_board(board, prefix="chk2"))
                    return
                await state.update_data(selected=(r, c), owners=owners)
                await query.message.edit_text(
                    render(board, (r, c), dests) + f"\n\nВыбрана шашка. «*» — куда можно. Жми цель.\n{turn_note}",
                    reply_markup=chk_board(board, (r, c), dests, prefix="chk2"),
                )
            else:
                await query.message.edit_text(render(board) + f"\n\nЭто не твоя шашка, друк, и не твой ход.\n{turn_note}", reply_markup=chk_board(board, prefix="chk2"))
            return
        if (r, c) == selected:
            await state.update_data(selected=None)
            await query.message.edit_text(render(board) + f"\n\nЖми свою шашку.\n{turn_note}", reply_markup=chk_board(board, prefix="chk2"))
            return
        if board[r][c] in pieces:
            dests = {m["squares"][-1] for m in legal_moves(board, color) if m["squares"][0] == (r, c)}
            if dests:
                await state.update_data(selected=(r, c))
                await query.message.edit_text(render(board, (r, c), dests) + f"\n\nВыбрана шашка. Жми цель.\n{turn_note}", reply_markup=chk_board(board, (r, c), dests, prefix="chk2"))
            else:
                await query.message.edit_text(render(board) + f"\n\nУ этой шашки нет хода, друк.\n{turn_note}", reply_markup=chk_board(board, prefix="chk2"))
            return
        sel_moves = [m for m in legal_moves(board, color) if m["squares"][0] == selected]
        sel_cell = (r, c)
        if sel_cell in {m["squares"][-1] for m in sel_moves}:
            move = next(m for m in sel_moves if m["squares"][-1] == sel_cell)
            board = apply_move(board, color, move)
            taken = len(move["captured"])
            if piece_count(board, other) == 0 or not legal_moves(board, other):
                await state.clear()
                await query.message.edit_text(
                    render(board) + (f"\n\n{owners[color]} выиграл партию, друк!" if color in owners else "\n\nПартия окончена, друки!"),
                    reply_markup=replay_board("chk2_again"),
                )
                return
            await state.update_data(board=board, selected=None, turn=other, owners=owners)
            nxt_note = f"Ходят {SYMBOLS['w' if other == 'w' else 'b']} {owners.get(other, '—')}."
            await query.message.edit_text(render(board) + f"\n\nХод сделан." + (f" Взято: {taken}." if taken else "") + f"\n{nxt_note}", reply_markup=chk_board(board, prefix="chk2"))
            return
        sel_dests = {m["squares"][-1] for m in sel_moves}
        await query.message.edit_text(
            render(board, selected, sel_dests) + f"\n\nТуда нельзя, друк. Жми «*» или свою шашку.\n{turn_note}",
            reply_markup=chk_board(board, selected, sel_dests, prefix="chk2"),
        )
        return

    if data == "chk2_again":
        board = start_board()
        await state.set_state(GameStates.checkers_two)
        await state.update_data(board=board, turn="w", owners={}, players=[uid])
        await query.message.edit_text(
            render(board) + "\n\nНовая партия! Белые (⛀) ходят первыми.",
            reply_markup=chk_board(board, prefix="chk2"),
        )
        return

    if data == "word_again":
        await state.set_state(GameStates.wordle)
        await state.update_data(word=None, length=None, guesses=[], attempts=0, players=[uid])
        await query.message.edit_text(
            "Новый Wordle! Сколько букв загадываю? Жми кнопку.",
            reply_markup=length_kb(),
        )
        return

    if data == "word2_again":
        await state.set_state(GameStates.wordle_two)
        await state.update_data(word=None, length=None, guesses=[], attempts=0, setter=None, building=False, draft=[], players=[uid])
        await query.message.edit_text(
            "Новый раунд! Загадывающий, выбери длину слова кнопками.",
            reply_markup=length_kb(),
        )
        return

    if data == "chk_again":
        board = start_board()
        await state.set_state(GameStates.checkers)
        await state.update_data(board=board, players=[uid])
        await query.message.edit_text(
            render(board) + "\n\nНовая партия! Ты белыми (⛀), твой ход.",
            reply_markup=chk_board(board),
        )
        return

    if data == "chm_again":
        board = ch_start_board()
        await state.set_state(GameStates.chess)
        await state.update_data(board=board, ep=None, cast="KQkq", sel=None, dests=[], players=[uid])
        await query.message.edit_text(
            "Новая партия, друк! Ты белыми.\n\n" + ch_render(board),
            reply_markup=chm_board(board, "chm"),
        )
        return

    if data == "chm2_again":
        board = ch_start_board()
        await state.set_state(GameStates.chess_two)
        await state.update_data(board=board, ep=None, cast="KQkq", sel=None, dests=[], turn="w", players=[uid])
        await query.message.edit_text(
            "Новая партия вдвоём! Хост белыми.\n\n" + ch_render(board),
            reply_markup=chm_board(board, "chm2"),
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
import os, random, sqlite3, asyncio
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice

DB_PATH = os.getenv("DB_PATH", "cows.db")
db = sqlite3.connect(DB_PATH)
db.execute("""CREATE TABLE IF NOT EXISTS cows(
    chat_id INTEGER, user_id INTEGER, name TEXT,
    weight INTEGER DEFAULT 0, last_grow TEXT,
    PRIMARY KEY(chat_id, user_id))""")
db.execute("""CREATE TABLE IF NOT EXISTS hall_of_fame(
    chat_id INTEGER, name TEXT, weight INTEGER, ended_at TEXT)""")
for col, coltype in [
    ("streak", "INTEGER DEFAULT 0"), ("last_steal", "TEXT"), ("last_duel", "TEXT"),
    ("coins", "INTEGER DEFAULT 0"), ("badges", "TEXT DEFAULT ''"), ("last_decay", "TEXT"),
    ("last_trade", "TEXT")
]:
    try:
        db.execute(f"ALTER TABLE cows ADD COLUMN {col} {coltype}")
    except sqlite3.OperationalError:
        pass
db.commit()

bot = Bot(os.getenv("BOT_TOKEN"))
dp = Dispatcher()

KYIV = ZoneInfo("Europe/Kyiv")
def today():
    return datetime.now(KYIV).date()

pending_sell = set()
pending_donate = set()

WEIGHT_BADGES = [
    (10, "🥉 Перші кроки"), (50, "🥈 Міцна корова"), (100, "🥇 Центнер"),
    (250, "💎 Товстунка"), (500, "👑 Легенда ферми"), (1000, "🌟 Тонна слави"),
]
STREAK_BADGES = [
    (7, "🔥 Тиждень поспіль"), (30, "⚡ Місяць без пропусків"), (100, "🏅 Залізна дисципліна"),
]

def get_cow(chat_id, user_id):
    return db.execute(
        "SELECT name, weight, last_grow, streak, last_steal, last_duel, coins, badges, last_decay, last_trade "
        "FROM cows WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()

def apply_decay(chat_id, user_id):
    row = get_cow(chat_id, user_id)
    if not row or not row[2]:
        return row
    t = today()
    last_grow_date = date.fromisoformat(row[2])
    days_since_grow = (t - last_grow_date).days
    if days_since_grow <= 3:
        return row
    last_decay_date = date.fromisoformat(row[8]) if row[8] else last_grow_date
    days_since_decay = (t - last_decay_date).days
    if days_since_decay >= 1:
        loss = int(row[1] * 0.05 * days_since_decay)
        new_weight = max(0, row[1] - loss)
        db.execute("UPDATE cows SET weight=?, last_decay=? WHERE chat_id=? AND user_id=?",
                   (new_weight, t.isoformat(), chat_id, user_id))
        db.commit()
        return get_cow(chat_id, user_id)
    return row

async def check_badges(m, chat_id, user_id, weight, streak):
    row = get_cow(chat_id, user_id)
    have = set(row[7].split(",")) if row[7] else set()
    new_badges = []
    for threshold, badge in WEIGHT_BADGES:
        if weight >= threshold and badge not in have:
            have.add(badge)
            new_badges.append(badge)
    for threshold, badge in STREAK_BADGES:
        if streak >= threshold and badge not in have:
            have.add(badge)
            new_badges.append(badge)
    if new_badges:
        db.execute("UPDATE cows SET badges=? WHERE chat_id=? AND user_id=?",
                   (",".join(have), chat_id, user_id))
        db.commit()
        await m.answer(f"🎖 Нові бейджі: {', '.join(new_badges)}!")

@dp.message(lambda m: m.new_chat_members is not None)
async def on_added(m: types.Message):
    me = await bot.get_me()
    for member in m.new_chat_members:
        if member.id == me.id:
            await m.reply(
                "🐄 Хей! Я новий бот-ферма в цьому чаті!\n\n"
                "Кожен тут може ростити свою корову:\n"
                "/growcow — погодувати корову (раз на день)\n"
                "/mycow — моя корова\n"
                "/namecow Ім'я — назвати корову\n"
                "/steal — вкрасти кг у суперника\n"
                "/duel — дуель корів (у відповідь)\n"
                "/sell, /buy — торгівля (раз на день, оновлюється опівночі)\n"
                "/balance — баланс монет\n"
                "/badges — мої бейджі\n"
                "/top, /global — топи\n"
                "/newseason, /legends — сезони (для адмінів)\n"
                "/donate — підтримати проєкт зірками ⭐\n\n"
                "Не годуй корову понад 3 дні — почне худнути! 🏆"
            )
            return

@dp.message(Command("growcow"))
async def grow(m: types.Message):
    t = today()
    apply_decay(m.chat.id, m.from_user.id)
    row = get_cow(m.chat.id, m.from_user.id)
    if row and row[2] == t.isoformat():
        await m.reply("🐄 Твоя корова вже їла сьогодні! Приходь завтра.")
        return

    streak = 1
    if row and row[2] == (t - timedelta(days=1)).isoformat():
        streak = (row[3] or 0) + 1

    gain = random.randint(1, 20) + min(streak - 1, 10)

    if row:
        weight = row[1] + gain
        db.execute("UPDATE cows SET weight=?, last_grow=?, streak=? WHERE chat_id=? AND user_id=?",
                   (weight, t.isoformat(), streak, m.chat.id, m.from_user.id))
    else:
        weight = gain
        db.execute("INSERT INTO cows(chat_id,user_id,name,weight,last_grow,streak) VALUES(?,?,?,?,?,?)",
                   (m.chat.id, m.from_user.id, m.from_user.first_name, weight, t.isoformat(), streak))
    db.commit()

    bonus_text = f" (+{min(streak-1,10)} кг за серію {streak} дн.)" if streak > 1 else ""
    await m.reply(f"🐄 Корова гравця {m.from_user.first_name} наїла +{gain} кг{bonus_text}! Тепер важить {weight} кг.")
    await check_badges(m, m.chat.id, m.from_user.id, weight, streak)

@dp.message(Command("mycow"))
async def mycow(m: types.Message):
    apply_decay(m.chat.id, m.from_user.id)
    row = get_cow(m.chat.id, m.from_user.id)
    if row:
        name = row[0] or m.from_user.first_name
        await m.reply(f"🐄 {name} важить {row[1]} кг, серія: {row[3] or 0} дн., монет: {row[6] or 0}")
    else:
        await m.reply("У тебе ще нема корови. Напиши /growcow 🐄")

@dp.message(Command("namecow"))
async def namecow(m: types.Message):
    row = get_cow(m.chat.id, m.from_user.id)
    if not row:
        await m.reply("Спочатку заведи корову: /growcow 🐄")
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2:
        await m.reply("Напиши так: /namecow Зірочка")
        return
    new_name = parts[1].strip()[:30]
    db.execute("UPDATE cows SET name=? WHERE chat_id=? AND user_id=?",
               (new_name, m.chat.id, m.from_user.id))
    db.commit()
    await m.reply(f"🐄 Тепер твою корову звати {new_name}!")

@dp.message(Command("badges"))
async def badges(m: types.Message):
    row = get_cow(m.chat.id, m.from_user.id)
    if not row or not row[7]:
        await m.reply("Ще нема бейджів. Годуй корову і рости вагу! 🐄")
        return
    await m.reply("🎖 Твої бейджі:\n" + "\n".join(row[7].split(",")))

@dp.message(Command("balance"))
async def balance(m: types.Message):
    row = get_cow(m.chat.id, m.from_user.id)
    coins = row[6] if row else 0
    await m.reply(f"💰 У тебе {coins or 0} монет")

@dp.message(Command("sell"))
async def sell_start(m: types.Message):
    row = get_cow(m.chat.id, m.from_user.id)
    if not row:
        await m.reply("Спочатку заведи корову: /growcow 🐄")
        return
    t = today()
    if row[9] == t.isoformat():
        await m.reply("🧊 Актив заморожено на сьогодні. Наступна торгівля — завтра о 00:00.")
        return
    if row[1] <= 0:
        await m.reply("У тебе 0 кг, нема що продавати 🐄")
        return
    pending_sell.add((m.chat.id, m.from_user.id))
    await m.reply(f"✏️ Напиши число — скільки кг продати (у тебе {row[1]} кг):")

@dp.message(Command("donate"))
async def donate_start(m: types.Message):
    pending_donate.add((m.chat.id, m.from_user.id))
    await m.reply("⭐ Напиши число — скільки зірок задонатити (наприклад 50):")

@dp.message(lambda m: m.text and m.text.strip().isdigit() and (
    (m.chat.id, m.from_user.id) in pending_sell or (m.chat.id, m.from_user.id) in pending_donate))
async def handle_digit_input(m: types.Message):
    key = (m.chat.id, m.from_user.id)

    if key in pending_sell:
        pending_sell.discard(key)
        row = get_cow(m.chat.id, m.from_user.id)
        kg = int(m.text.strip())
        if kg <= 0 or kg > row[1]:
            await m.reply(f"Некоректне число, у тебе {row[1]} кг. Спробуй /sell знову.")
            return
        coins_gain = kg * 20 // 15
        t = today()
        db.execute("UPDATE cows SET weight=weight-?, coins=coins+?, last_trade=? WHERE chat_id=? AND user_id=?",
                   (kg, coins_gain, t.isoformat(), m.chat.id, m.from_user.id))
        db.commit()
        await m.reply(f"💰 Продав {kg} кг за {coins_gain} монет! Наступна торгівля — завтра о 00:00.")
        return

    if key in pending_donate:
        pending_donate.discard(key)
        stars = int(m.text.strip())
        if stars < 1 or stars > 2500:
            await m.reply("Число зірок має бути від 1 до 2500 ⭐")
            return
        await bot.send_invoice(
            chat_id=m.chat.id,
            title="Підтримати Growacow 🐄",
            description=f"Донат {stars} ⭐ на розвиток бота",
            payload=f"donate_{m.from_user.id}_{stars}",
            currency="XTR",
            prices=[LabeledPrice(label="Донат", amount=stars)],
        )

@dp.pre_checkout_query()
async def pre_checkout(pcq: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pcq.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment(m: types.Message):
    stars = m.successful_payment.total_amount
    bonus_coins = stars * 2
    row = get_cow(m.chat.id, m.from_user.id)
    if row:
        db.execute("UPDATE cows SET coins=coins+? WHERE chat_id=? AND user_id=?",
                   (bonus_coins, m.chat.id, m.from_user.id))
        db.commit()
        await m.reply(f"🙏 Дякую за {stars} ⭐! Нараховано {bonus_coins} монет у подяку.")
    else:
        await m.reply(f"🙏 Дякую за {stars}

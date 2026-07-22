import os, random, sqlite3, asyncio
from datetime import date, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

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
    ("coins", "INTEGER DEFAULT 0"), ("badges", "TEXT DEFAULT ''"), ("last_decay", "TEXT")
]:
    try:
        db.execute(f"ALTER TABLE cows ADD COLUMN {col} {coltype}")
    except sqlite3.OperationalError:
        pass
db.commit()

bot = Bot(os.getenv("BOT_TOKEN"))
dp = Dispatcher()

WEIGHT_BADGES = [
    (10, "🥉 Перші кроки"), (50, "🥈 Міцна корова"), (100, "🥇 Центнер"),
    (250, "💎 Товстунка"), (500, "👑 Легенда ферми"), (1000, "🌟 Тонна слави"),
]
STREAK_BADGES = [
    (7, "🔥 Тиждень поспіль"), (30, "⚡ Місяць без пропусків"), (100, "🏅 Залізна дисципліна"),
]

def get_cow(chat_id, user_id):
    return db.execute(
        "SELECT name, weight, last_grow, streak, last_steal, last_duel, coins, badges, last_decay "
        "FROM cows WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()

def apply_decay(chat_id, user_id):
    row = get_cow(chat_id, user_id)
    if not row or not row[2]:
        return row
    today = date.today()
    last_grow_date = date.fromisoformat(row[2])
    days_since_grow = (today - last_grow_date).days
    if days_since_grow <= 3:
        return row
    last_decay_date = date.fromisoformat(row[8]) if row[8] else last_grow_date
    days_since_decay = (today - last_decay_date).days
    if days_since_decay >= 1:
        loss = int(row[1] * 0.05 * days_since_decay)
        new_weight = max(0, row[1] - loss)
        db.execute("UPDATE cows SET weight=?, last_decay=? WHERE chat_id=? AND user_id=?",
                   (new_weight, today.isoformat(), chat_id, user_id))
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
                "/sell, /buy, /balance — ринок\n"
                "/badges — мої бейджі\n"
                "/top, /global — топи\n"
                "/newseason, /legends — сезони (для адмінів)\n\n"
                "Не годуй корову понад 3 дні — почне худнути! 🏆"
            )
            return

@dp.message(Command("growcow"))
async def grow(m: types.Message):
    today = date.today()
    apply_decay(m.chat.id, m.from_user.id)
    row = get_cow(m.chat.id, m.from_user.id)
    if row and row[2] == today.isoformat():
        await m.reply("🐄 Твоя корова вже їла сьогодні! Приходь завтра.")
        return

    streak = 1
    if row and row[2] == (today - timedelta(days=1)).isoformat():
        streak = (row[3] or 0) + 1

    gain = random.randint(1, 20) + min(streak - 1, 10)

    if row:
        weight = row[1] + gain
        db.execute("UPDATE cows SET weight=?, last_grow=?, streak=? WHERE chat_id=? AND user_id=?",
                   (weight, today.isoformat(), streak, m.chat.id, m.from_user.id))
    else:
        weight = gain
        db.execute("INSERT INTO cows(chat_id,user_id,name,weight,last_grow,streak) VALUES(?,?,?,?,?,?)",
                   (m.chat.id, m.from_user.id, m.from_user.first_name, weight, today.isoformat(), streak))
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
async def sell(m: types.Message):
    row = get_cow(m.chat.id, m.from_user.id)
    if not row:
        await m.reply("Спочатку заведи корову: /growcow 🐄")
        return
    parts = m.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await m.reply("Напиши так: /sell 20 (кг)")
        return
    kg = int(parts[1].strip())
    if kg <= 0 or kg > row[1]:
        await m.reply(f"У тебе тільки {row[1]} кг 🐄")
        return
    coins_gain = kg * 2
    db.execute("UPDATE cows SET weight=weight-?, coins=coins+? WHERE chat_id=? AND user_id=?",
               (kg, coins_gain, m.chat.id, m.from_user.id))
    db.commit()
    await m.reply(f"💰 Продав {kg} кг за {coins_gain} монет!")

@dp.message(Command("buy"))
async def buy(m: types.Message):
    row = get_cow(m.chat.id, m.from_user.id)
    if not row:
        await m.reply("Спочатку заведи корову: /growcow 🐄")
        return
    cost, gain = 20, 15
    if (row[6] or 0) < cost:
        await m.reply(f"💸 Треба {cost} монет, у тебе {row[6] or 0}. Продай кг: /sell")
        return
    db.execute("UPDATE cows SET weight=weight+?, coins=coins-? WHERE chat_id=? AND user_id=?",
               (gain, cost, m.chat.id, m.from_user.id))
    db.commit()
    await m.reply(f"🌾 Купив їжі за {cost} монет, корова +{gain} кг!")

@dp.message(Command("top"))
async def top(m: types.Message):
    rows = db.execute(
        "SELECT name, weight FROM cows WHERE chat_id=? ORDER BY weight DESC LIMIT 10",
        (m.chat.id,)).fetchall()
    if not rows:
        await m.reply("Ферма пуста 🌾")
        return
    text = "🏆 Топ корів чату:\n" + "\n".join(
        f"{i+1}. {name} — {w} кг" for i, (name, w) in enumerate(rows))
    await m.reply(text)

@dp.message(Command("global"))
async def global_top(m: types.Message):
    rows = db.execute(
        "SELECT name, MAX(weight) as w FROM cows GROUP BY user_id ORDER BY w DESC LIMIT 10").fetchall()
    if not rows:
        await m.reply("Світова ферма ще пуста 🌍")
        return
    text = "🌍 Топ корів світу:\n" + "\n".join(
        f"{i+1}. {name} — {w} кг" for i, (name, w) in enumerate(rows))
    await m.reply(text)

@dp.message(Command("steal"))
async def steal(m: types.Message):
    today = date.today().isoformat()
    row = get_cow(m.chat.id, m.from_user.id)
    if not row:
        await m.reply("Спочатку заведи корову: /growcow 🐄")
        return
    if row[4] == today:
        await m.reply("🕵️ Ти вже крав сьогодні! Завтра спробуй знову.")
        return

    victims = db.execute(
        "SELECT user_id, name, weight FROM cows WHERE chat_id=? AND user_id!=? AND weight>0",
        (m.chat.id, m.from_user.id)).fetchall()
    if not victims:
        await m.reply("Нема в кого красти 🐄")
        return

    victim_id, victim_name, victim_weight = random.choice(victims)
    db.execute("UPDATE cows SET last_steal=? WHERE chat_id=? AND user_id=?",
               (today, m.chat.id, m.from_user.id))

    if random.random() < 0.5:
        amount = max(1, int(victim_weight * random.uniform(0.05, 0.15)))
        db.execute("UPDATE cows SET weight=weight-? WHERE chat_id=? AND user_id=?",
                   (amount, m.chat.id, victim_id))
        db.execute("UPDATE cows SET weight=weight+? WHERE chat_id=? AND user_id=?",
                   (amount, m.chat.id, m.from_user.id))
        db.commit()
        await m.reply(f"🥷 Вдалося! Ти вкрав {amount} кг у {victim_name}.")
    else:
        penalty = max(1, int(row[1] * 0.1))
        db.execute("UPDATE cows SET weight=MAX(weight-?,0) WHERE chat_id=? AND user_id=?",
                   (penalty, m.chat.id, m.from_user.id))
        db.commit()
        await m.reply(f"🚨 Тебе спіймали! Втратив {penalty} кг.")

@dp.message(Command("duel"))
async def duel(m: types.Message):
    if not m.reply_to_message or not m.reply_to_message.from_user:
        await m.reply("Дай /duel у відповідь на повідомлення суперника 🤺")
        return
    opponent = m.reply_to_message.from_user
    if opponent.is_bot:
        await m.reply("Дай /duel у відповідь на повідомлення живого суперника, не бота 🤺")
        return
    if opponent.id == m.from_user.id:
        await m.reply("Не можна дуелювати самого себе 😅")
        return

    row1 = get_cow(m.chat.id, m.from_user.id)
    row2 = get_cow(m.chat.id, opponent.id)
    if not row1 or not row2:
        await m.reply("У обох має бути корова: /growcow 🐄")
        return

    today = date.today().isoformat()
    if row1[5] == today:
        await m.reply("🕒 Ти вже дуелював сьогодні!")
        return

    w1, w2 = row1[1], row2[1]
    win1 = random.random() < (w1 / (w1 + w2))

    winner_id, loser_id = (m.from_user.id, opponent.id) if win1 else (opponent.id, m.from_user.id)
    loser_weight = w2 if win1 else w1
    amount = max(1, int(loser_weight * 0.1))

    db.execute("UPDATE cows SET weight=weight+? WHERE chat_id=? AND user_id=?",
               (amount, m.chat.id, winner_id))
    db.execute("UPDATE cows SET weight=MAX(weight-?,0) WHERE chat_id=? AND user_id=?",
               (amount, m.chat.id, loser_id))
    db.execute("UPDATE cows SET last_duel=? WHERE chat_id=? AND user_id=?",
               (today, m.chat.id, m.from_user.id))
    db.commit()

    winner_name = m.from_user.first_name if win1 else opponent.first_name
    loser_name = opponent.first_name if win1 else m.from_user.first_name
    await m.reply(f"🤺 Дуель! {winner_name} переміг {loser_name} і забрав {amount} кг!")

@dp.message(Command("newseason"))
async def newseason(m: types.Message):
    member = await bot.get_chat_member(m.chat.id, m.from_user.id)
    if member.status not in ("creator", "administrator"):
        await m.reply("🔒 Тільки адмін чату може закрити сезон.")
        return

    champ = db.execute(
        "SELECT name, weight FROM cows WHERE chat_id=? ORDER BY weight DESC LIMIT 1",
        (m.chat.id,)).fetchone()
    if not champ or champ[1] == 0:
        await m.reply("Ферма пуста, нема кого коронувати 🌾")
        return

    db.execute("INSERT INTO hall_of_fame(chat_id, name, weight, ended_at) VALUES(?,?,?,?)",
               (m.chat.id, champ[0], champ[1], date.today().isoformat()))
    db.execute("UPDATE cows SET weight=0, streak=0, badges='' WHERE chat_id=?", (m.chat.id,))
    db.commit()
    await m.reply(f"🎉 Сезон завершено! Чемпіон: {champ[0]} з {champ[1]} кг!\nВсі ваги обнулено, новий сезон почався 🐄")

@dp.message(Command("legends"))
async def legends(m: types.Message):
    rows = db.execute(
        "SELECT name, weight, ended_at FROM hall_of_fame WHERE chat_id=? ORDER BY ended_at DESC LIMIT 10",
        (m.chat.id,)).fetchall()
    if not rows:
        await m.reply("Зал слави ще пустий. Заверши перший сезон: /newseason 🏆")
        return
    text = "👑 Зал слави:\n" + "\n".join(
        f"{d} — {name} ({w} кг)" for name, w, d in rows)
    await m.reply(text)

async def main():
    await bot.set_my_commands([
        types.BotCommand(command="growcow", description="🐄 Погодувати корову"),
        types.BotCommand(command="mycow", description="📋 Моя корова"),
        types.BotCommand(command="namecow", description="✏️ Назвати корову"),
        types.BotCommand(command="steal", description="🥷 Вкрасти кг у суперника"),
        types.BotCommand(command="duel", description="🤺 Дуель корів (у відповідь)"),
        types.BotCommand(command="sell", description="💰 Продати кг"),
        types.BotCommand(command="buy", description="🌾 Купити їжу"),
        types.BotCommand(command="balance", description="💰 Мій баланс"),
        types.BotCommand(command="badges", description="🎖 Мої бейджі"),
        types.BotCommand(command="top", description="🏆 Топ чату"),
        types.BotCommand(command="global", description="🌍 Топ світу"),
        types.BotCommand(command="newseason", description="🎉 Закрити сезон (адмін)"),
        types.BotCommand(command="legends", description="👑 Зал слави"),
    ])
    await dp.start_polling(bot)

asyncio.run(main())

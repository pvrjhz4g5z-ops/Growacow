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
for col, coltype in [("streak", "INTEGER DEFAULT 0"), ("last_steal", "TEXT"), ("last_duel", "TEXT")]:
    try:
        db.execute(f"ALTER TABLE cows ADD COLUMN {col} {coltype}")
    except sqlite3.OperationalError:
        pass
db.commit()

bot = Bot(os.getenv("BOT_TOKEN"))
dp = Dispatcher()

def get_cow(chat_id, user_id):
    return db.execute(
        "SELECT name, weight, last_grow, streak, last_steal, last_duel FROM cows WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)).fetchone()

@dp.message(Command("growcow"))
async def grow(m: types.Message):
    today = date.today()
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

@dp.message(Command("mycow"))
async def mycow(m: types.Message):
    row = get_cow(m.chat.id, m.from_user.id)
    if row:
        name = row[0] or m.from_user.first_name
        await m.reply(f"🐄 {name} важить {row[1]} кг, серія: {row[3] or 0} дн.")
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
    if not m.reply_to_message:
        await m.reply("Дай /duel у відповідь на повідомлення суперника 🤺")
        return
    opponent = m.reply_to_message.from_user
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

async def main():
    await dp.start_polling(bot)

asyncio.run(main())

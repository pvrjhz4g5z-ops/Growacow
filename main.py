import os, random, sqlite3, asyncio
from datetime import date
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

DB_PATH = os.getenv("DB_PATH", "cows.db")
db = sqlite3.connect(DB_PATH)
db.execute("""CREATE TABLE IF NOT EXISTS cows(
    chat_id INTEGER, user_id INTEGER, name TEXT,
    weight INTEGER DEFAULT 0, last_grow TEXT,
    PRIMARY KEY(chat_id, user_id))""")
db.commit()

bot = Bot(os.getenv("BOT_TOKEN"))
dp = Dispatcher()

@dp.message(Command("growcow"))
async def grow(m: types.Message):
    today = date.today().isoformat()
    row = db.execute(
        "SELECT weight, last_grow FROM cows WHERE chat_id=? AND user_id=?",
        (m.chat.id, m.from_user.id)).fetchone()
    if row and row[1] == today:
        await m.reply("🐄 Твоя корова вже їла сьогодні! Приходь завтра.")
        return
    gain = random.randint(1, 20)
    if row:
        weight = row[0] + gain
        db.execute("UPDATE cows SET weight=?, last_grow=? WHERE chat_id=? AND user_id=?",
                   (weight, today, m.chat.id, m.from_user.id))
    else:
        weight = gain
        db.execute("INSERT INTO cows VALUES(?,?,?,?,?)",
                   (m.chat.id, m.from_user.id, m.from_user.first_name, weight, today))
    db.commit()
    await m.reply(f"🐄 Корова гравця {m.from_user.first_name} наїла +{gain} кг! Тепер важить {weight} кг.")

@dp.message(Command("mycow"))
async def mycow(m: types.Message):
    row = db.execute("SELECT weight FROM cows WHERE chat_id=? AND user_id=?",
                     (m.chat.id, m.from_user.id)).fetchone()
    if row:
        await m.reply(f"🐄 Твоя корова важить {row[0]} кг")
    else:
        await m.reply("У тебе ще нема корови. Напиши /growcow 🐄")

@dp.message(Command("top"))
async def top(m: types.Message):
    rows = db.execute(
        "SELECT name, weight FROM cows WHERE chat_id=? ORDER BY weight DESC LIMIT 10",
        (m.chat.id,)).fetchall()
    if not rows:
        await m.reply("Ферма пуста 🌾")
        return
    text = "🏆 Топ корів:\n" + "\n".join(
        f"{i+1}. {name} — {w} кг" for i, (name, w) in enumerate(rows))
    await m.reply(text)

async def main():
    await dp.start_polling(bot)

asyncio.run(main())

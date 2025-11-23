import json
import os
import asyncio
import re

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv
from openai import OpenAI
import pymorphy3
morph = pymorphy3.MorphAnalyzer()


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    parse_mode=ParseMode.MARKDOWN)
    )



dp = Dispatcher()
client = OpenAI(api_key=OPENAI_KEY)


# ------------------ LOAD RECIPES ----------------------
def load_json_file(filename):
    """Поддержка файлов с несколькими JSON-объектами подряд"""
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # Если это массив — просто читаем
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Если нет — разбиваем на объекты
    parts = re.split(r'\n\s*\}\s*\n\s*\{', content)
    recipes = []
    for part in parts:
        if not part.startswith("{"):
            part = "{" + part
        if not part.endswith("}"):
            part += "}"
        try:
            recipes.append(json.loads(part))
        except json.JSONDecodeError as e:
            print(f"⚠️ Ошибка парсинга {filename}: {e}")
    return recipes


recipes = []
recipes.extend(load_json_file("recipes.json"))
recipes.extend(load_json_file("skoraya_pomoshch.json"))
recipes.extend(load_json_file("postnoe_menu.json"))
recipes.extend(load_json_file("pro100.json"))
recipes.extend(load_json_file("detoks.json"))
recipes.extend(load_json_file("prazdnik.json"))
recipes.extend(load_json_file("pp_desert.json"))
recipes.extend(load_json_file("konstruktor.json"))
recipes.extend(load_json_file("Ne_dieta.json"))
recipes.extend(load_json_file("vafly.json"))
recipes.extend(load_json_file("programma_na_2_nedeli.json"))

print("📄 Загружено рецептов:", len(recipes))


# ---------------- NORMALIZATION + STEMMING ----------------

import re

def normalize(text):
    # Приведение к нижнему регистру и чистка
    text = text.lower()
    text = re.sub(r"[–—−]", "-", text)
    text = text.replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9\- ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Лемматизация — приводим слова к начальной форме
    words = text.split()
    lemmas = [morph.parse(w)[0].normal_form for w in words]
    return " ".join(lemmas)



def stem(word):
    # Убрали старые окончания — они ломали слова
    # Теперь очень простой и надёжный стемминг
    return word[:4]



# ------------------- SEARCH FUNCTION ---------------------

import re

def search_recipes(search_term):
    term = normalize(search_term)
    found = []

    for r in recipes:
        name = normalize(r["name"])
        ingredients = normalize(" ".join(r["ingredients"]))
        instructions = normalize(" ".join(r["instructions"]))
        recipe_type = normalize(r.get("type", ""))  # добавляем поиск по типу блюда

        # поиск по целым словам, а не по подстрокам
        if (re.search(rf"\b{term}\b", name) or
            re.search(rf"\b{term}\b", ingredients) or
            re.search(rf"\b{term}\b", recipe_type) or
            re.search(rf"\b{term}\b", instructions)):
            print(f"✅ НАЙДЕНО В: {r['name']}")
            found.append(r)
        else:
            print(f"❌ НЕ НАЙДЕНО В: {r['name']}")

    print(f"📦 Найдено рецептов: {len(found)}")
    return found



# ------------------- GPT KEYWORD EXTRACTION --------------------

SYSTEM_PROMPT = """
Ты — модуль, который извлекает ключевое слово для поиска рецепта.
Если пользователь спрашивает про блюдо, верни название блюда.
Если спрашивает про ингредиент, верни ингредиент.
Отвечай только одним словом или короткой фразой.
"""


def extract_keyword(text):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
    )
    return resp.choices[0].message.content.strip().lower()


# ------------------- HANDLERS ---------------------------

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Привет! Напиши, что хочешь приготовить 😊")


@dp.message()
async def handle_message(message: Message):
    try:
        user_text = message.text

        # Проверка на тип блюда (завтрак, обед, ужин, десерт)
        meal_types = ["завтрак", "обед", "ужин", "десерт"]
        if any(mt in user_text.lower() for mt in meal_types):
            keyword = next(mt for mt in meal_types if mt in user_text.lower())
        else:
            keyword = extract_keyword(user_text)

        print("🔍 KEYWORD:", keyword)
        await message.answer(f"Ищу по ключу: {keyword}")
        matches = search_recipes(keyword)
        if not matches:
            await message.answer("Ничего не нашёл 😔")
            return
        
        # Отправляем каждый рецепт отдельным сообщением
        for r in matches:
            text = f"🍽 *{r['name']}*\n"
            text += f"⏱ Время: {r.get('time', '—')}\n"
            if r.get("type"):
                text += f"📂 Тип: {r['type']}\n"
            text += "\n*Ингредиенты:*\n"
            for ingr in r["ingredients"]:
                text += f"• {ingr}\n"
        
            text += "\n*Приготовление:*\n"
            for i, step in enumerate(r["instructions"], start=1):
                text += f"{i}. {step}\n"
        
            text += "\n" + ("—" * 30)
        
            # Если рецепт слишком длинный — режем на части
            if len(text) > 3500:
                chunks = [text[i:i+3500] for i in range(0, len(text), 3500)]
                for chunk in chunks:
                    await message.answer(chunk)
            else:
                await message.answer(text)
        

    except Exception as e:
        print("❌ ERROR:", e)
        await message.answer("Ошибка в обработке. Смотри логи.")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

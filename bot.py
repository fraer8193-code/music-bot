import re
import os
import asyncio
import aiohttp
from dotenv import load_dotenv
from yandex_music import Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN")
VK_TOKEN = os.getenv("VK_TOKEN")

cache = {}
yandex_client = None

def init_yandex():
    global yandex_client
    try:
        yandex_client = Client(YANDEX_TOKEN).init()
        print("✅ Яндекс Музыка подключена")
        return True
    except Exception as e:
        print(f"❌ Ошибка Яндекс: {e}")
        return False

def init_vk():
    if VK_TOKEN:
        print("✅ ВК Музыка подключена")
        return True
    return False

def search_yandex(query, limit=50):
    """Поиск на Яндекс Музыке"""
    results = []
    try:
        if not yandex_client:
            return results
        search = yandex_client.search(query, type_='track')
        if search and search.tracks:
            for track in search.tracks.results[:limit]:
                artists = ', '.join([a.name for a in track.artists]) if track.artists else '?'
                results.append({
                    'id': str(track.id),
                    'title': track.title[:50] if track.title else '?',
                    'channel': artists[:30],
                    'duration': (track.duration_ms // 1000) if track.duration_ms else 0,
                    'source': 'yandex'
                })
    except Exception as e:
        print(f"Yandex search error: {e}")
    return results


def search_vk(query, limit=50):
    """Поиск на ВК Музыке через API"""
    results = []
    try:
        import requests
        url = "https://api.vk.com/method/audio.search"
        params = {
            'q': query,
            'count': limit,
            'access_token': VK_TOKEN,
            'v': '5.131'
        }
        r = requests.get(url, params=params)
        data = r.json()
        
        if 'response' in data and 'items' in data['response']:
            for item in data['response']['items']:
                results.append({
                    'id': item.get('url', ''),
                    'title': item.get('title', '?')[:50],
                    'channel': item.get('artist', '?')[:30],
                    'duration': item.get('duration', 0),
                    'source': 'vk'
                })
    except Exception as e:
        print(f"VK search error: {e}")
    return results

def search_all(query):
    """Поиск по всем источникам"""
    results = []
    
    ya_results = search_yandex(query, 50)
    results.extend(ya_results)
    
    if VK_TOKEN:
        vk_results = search_vk(query, 50)
        results.extend(vk_results)
    
    return results

def download_yandex(track_id, filename):
    """Скачивание с Яндекса"""
    try:
        track = yandex_client.tracks([track_id])[0]
        track.download(filename)
        if os.path.exists(filename):
            return filename
    except Exception as e:
        print(f"Yandex download error: {e}")
    return None

def download_vk(url, filename):
    """Скачивание с ВК"""
    try:
        import requests
        r = requests.get(url, timeout=60)
        if r.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(r.content)
            return filename
    except Exception as e:
        print(f"VK download error: {e}")
    return None


def make_keyboard(key, page):
    results = cache.get(key, [])
    total = len(results)
    pages = max(1, (total + 4) // 5)
    
    kb = []
    start = page * 5
    for i, r in enumerate(results[start:start+5], start+1):
        dur = f"{r['duration']//60}:{r['duration']%60:02d}" if r.get('duration') else ""
        icon = "🟡" if r['source'] == 'yandex' else "🔵"
        text = f"{icon} {r['channel'][:10]} - {r['title'][:18]}"
        if dur:
            text += f" [{dur}]"
        kb.append([InlineKeyboardButton(text, callback_data=f"s_{key}_{start+i-1}")])
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"p_{key}_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data="x"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"p_{key}_{page+1}"))
    if nav:
        kb.append(nav)
    
    return InlineKeyboardMarkup(kb)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sources = []
    if yandex_client:
        sources.append("🟡 Яндекс")
    if VK_TOKEN:
        sources.append("🔵 ВК")
    
    await update.message.reply_text(
        f"🎵 Привет! Я скачиваю музыку.\n\n"
        f"Источники: {', '.join(sources)}\n\n"
        f"Отправь название песни или /search запрос"
    )

async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(ctx.args) if ctx.args else None
    if not query:
        await update.message.reply_text("/search название")
        return
    await do_search(update, query)

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    m = re.match(r'^[Нн]айти\s+(.+)$', text)
    if m:
        await do_search(update, m.group(1))
    elif len(text) > 2:
        await do_search(update, text)

async def do_search(update: Update, query: str):
    msg = await update.message.reply_text(f"🔍 Ищу: {query}...")
    
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, search_all, query)
    
    if not results:
        await msg.edit_text("😔 Ничего не нашёл.")
        return
    
    key = str(update.message.message_id)
    cache[key] = results
    
    if len(cache) > 50:
        del cache[list(cache.keys())[0]]
    
    pages = (len(results) + 4) // 5
    kb = make_keyboard(key, 0)
    await msg.edit_text(f"🎵 Найдено {len(results)} треков ({pages} стр.):", reply_markup=kb)


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    
    if data == "x":
        await q.answer()
        return
    
    parts = data.split("_")
    
    if parts[0] == "p":
        key, page = parts[1], int(parts[2])
        if key not in cache:
            await q.answer("Устарело, поищи заново")
            return
        kb = make_keyboard(key, page)
        await q.edit_message_reply_markup(reply_markup=kb)
        await q.answer()
    
    elif parts[0] == "s":
        key, idx = parts[1], int(parts[2])
        if key not in cache:
            await q.answer("Устарело")
            return
        
        r = cache[key][idx]
        await q.answer("⏳ Скачиваю...")
        
        chat_id = q.message.chat_id
        src = "Яндекс" if r['source'] == 'yandex' else "ВК"
        status_msg = await ctx.bot.send_message(chat_id, f"⏳ [{src}] {r['channel']} - {r['title']}...")
        
        filename = f"temp_{chat_id}_{idx}.mp3"
        
        try:
            loop = asyncio.get_event_loop()
            
            if r['source'] == 'yandex':
                audio_file = await loop.run_in_executor(None, download_yandex, r['id'], filename)
            else:
                audio_file = await loop.run_in_executor(None, download_vk, r['id'], filename)
            
            if audio_file and os.path.exists(audio_file):
                size = os.path.getsize(audio_file)
                if size > 50 * 1024 * 1024:
                    await status_msg.edit_text("😔 Файл > 50MB")
                    os.remove(audio_file)
                    return
                
                await status_msg.edit_text("📤 Отправляю...")
                
                with open(audio_file, 'rb') as f:
                    await ctx.bot.send_audio(
                        chat_id, audio=f,
                        title=r['title'],
                        performer=r['channel'],
                        duration=r.get('duration', 0)
                    )
                
                await status_msg.delete()
                os.remove(audio_file)
            else:
                await status_msg.edit_text("😔 Не удалось скачать")
        except Exception as e:
            print(f"Error: {e}")
            await status_msg.edit_text("😔 Ошибка")
            if os.path.exists(filename):
                os.remove(filename)

def main():
    ya_ok = init_yandex()
    vk_ok = init_vk()
    
    if not ya_ok and not vk_ok:
        print("❌ Ни один источник не подключен!")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("find", cmd_search))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🎵 Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()



import os
import io
import sqlite3
import logging
import requests
from datetime import datetime
from flask import Flask, request
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.background import BackgroundScheduler
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
import textwrap
import time

# --- Configuration ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')  # e.g. https://yourapp.onrender.com
CHANNEL_ID = os.environ.get('CHANNEL_ID')  # @channelusername or -1001234567890
DATABASE = 'data.db'
PORT = int(os.environ.get('PORT', '10000'))

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError('Please set BOT_TOKEN and WEBHOOK_URL environment variables (WEBHOOK_URL without trailing slash).')

WEBHOOK_PATH = f"/{BOT_TOKEN}"

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Initialize bot & flask ---
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Database helpers ---
def init_db():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS scheduled (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat TEXT,
            send_time TEXT, -- HH:MM
            text TEXT,
            active INTEGER DEFAULT 1
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_scheduled(chat, hhmm, text):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute('INSERT INTO scheduled(chat, send_time, text, active) VALUES (?,?,?,1)', (chat, hhmm, text))
    conn.commit()
    conn.close()

def get_all_scheduled():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute('SELECT id, chat, send_time, text, active FROM scheduled')
    rows = cur.fetchall()
    conn.close()
    return rows

def add_note(user_id, content):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute('INSERT INTO notes(user_id, content, created_at) VALUES (?,?,?)', (user_id, content, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_notes(user_id):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute('SELECT id, content, created_at FROM notes WHERE user_id=? ORDER BY id DESC', (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

# --- Scheduler: checks DB every minute and sends messages when time matches ---
scheduler = BackgroundScheduler()
def check_and_send():
    now = datetime.now().strftime('%H:%M')
    rows = get_all_scheduled()
    for r in rows:
        id_, chat, send_time, text, active = r
        if active and send_time == now:
            try:
                bot.send_message(chat, text, disable_web_page_preview=False)
                logger.info(f"Sent scheduled message id={id_} to {chat}")
            except Exception as e:
                logger.exception('Failed to send scheduled message')

# Start scheduler
scheduler.add_job(check_and_send, 'interval', seconds=30)
scheduler.start()

# --- UI / Menu ---
MENU_BUTTONS = [
    ("Aparat Video", "aparat"),
    ("Google Search", "gsearch"),
    ("Barcode Read", "barcode"),
    ("Text → Image", "textimg"),
    ("Weather", "weather"),
    ("Currency/Gold", "money"),
    ("Crypto", "crypto"),
    ("Calendar", "calendar"),
    ("Joke", "joke"),
    ("Translate", "translate"),
    ("Random", "random"),
    ("News", "news"),
    ("Notes", "notes"),
    ("Music Link", "music"),
    ("Settings", "settings"),
]

def make_menu():
    markup = InlineKeyboardMarkup()
    row = []
    for text, key in MENU_BUTTONS:
        row.append(InlineKeyboardButton(text, callback_data=key))
        if len(row) == 3:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
    return markup

# --- Helper utilities ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36'
}

from googlesearch import search

def google_search(query, num_results=5):
    results = []
    for url in search(query, num_results=num_results):
        results.append(url)
    return results


from PIL import Image, ImageDraw, ImageFont

def text_to_image(text, output="output.png", font_path="B.ttf"):
    img = Image.new("RGB", (600, 200), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 24)
    w, h = d.textsize(text, font=font)
    d.text(((600-w)/2, (200-h)/2), text, fill=(0,0,0), font=font)
    img.save(output)
    return output


from pyzbar.pyzbar import decode
from PIL import Image
import io

def read_barcode(file_bytes):
    img = Image.open(io.BytesIO(file_bytes))
    data_list = decode(img)
    if data_list:
        return [d.data.decode("utf-8") for d in data_list]
    return []



# Aparat preview: just send URL back and Telegram will show preview (if allowed)

# --- Bot handlers ---
@bot.message_handler(commands=['start', 'menu'])
def handle_start(msg):
    bot.send_message(msg.chat.id, 'سلام! من ربات همه‌کاره هستم. یکی از گزینه‌ها را انتخاب کن:', reply_markup=make_menu())

# Add scheduled message via command: /schedule HH:MM | text
@bot.message_handler(commands=['schedule'])
def cmd_schedule(message):
    try:
        payload = message.text.split(' ',1)[1]
        hhmm, text = payload.split('|',1)
        hhmm = hhmm.strip()
        text = text.strip()
        add_scheduled(CHANNEL_ID or message.chat.id, hhmm, text)
        bot.reply_to(message, f'پیام برای ساعت {hhmm} تنظیم شد.')
    except Exception:
        bot.reply_to(message, 'فرمت اشتباه. مثال: /schedule 14:30 | متن پیام')

# Notes commands
@bot.message_handler(commands=['mynotes'])
def cmd_mynotes(message):
    notes = get_notes(message.from_user.id)
    if not notes:
        bot.reply_to(message, 'یادداشت ندارید.')
        return
    text = '\n\n'.join([f"{r[0]}: {r[1]}" for r in notes])
    bot.reply_to(message, text)

@bot.message_handler(commands=['addnote'])
def cmd_addnote(message):
    try:
        content = message.text.split(' ',1)[1]
        add_note(message.from_user.id, content)
        bot.reply_to(message, 'ذخیره شد.')
    except Exception:
        bot.reply_to(message, 'مثال: /addnote متن شما')

# Callback queries for menu buttons
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    data = call.data
    cid = call.message.chat.id
    if data == 'aparat':
        bot.send_message(cid, 'لطفا لینک آپارات را ارسال کنید (مثال: https://www.aparat.com/v/xxxxx)')
    elif data == 'gsearch':
        bot.send_message(cid, 'عبارت برای جستجو را ارسال کنید:')
    elif data == 'barcode':
        bot.send_message(cid, 'یک عکس بارکد ارسال کنید تا خوانده شود.')
    elif data == 'textimg':
        bot.send_message(cid, 'متن را ارسال کنید تا به عکس تبدیل شود.')
    elif data == 'notes':
        bot.send_message(cid, 'برای اضافه کردن یادداشت: /addnote متن\nبرای دیدن یادداشت‌ها: /mynotes')
    else:
        bot.send_message(cid, f'دکمه {data} فشرده شد — این قابلیت نصب نشده است (نسخه اولیه).')

# Generic handlers for content (links, images, text)
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    text = message.text.strip()
    cid = message.chat.id
    # Detect if user is replying for certain actions (simple stateful approach)
    # For simplicity, we use keywords
    if text.lower().startswith('http') and ('aparat.com' in text.lower()):
        # send back the link (Telegram will attempt to show preview)
        bot.send_message(cid, text)
        return
    # If previous message requested google search: we use a simple heuristic
    if text.startswith('/search '):
        q = text[len('/search '):].strip()
        links = google_search(q)
        if not links:
            bot.send_message(cid, 'نتیجه‌ای یافت نشد یا سرویس در دسترس نیست.')
        else:
            out = 'نتایج برتر:\n' + '\n'.join(links[:5])
            bot.send_message(cid, out)
        return
    # fallback: if it's plain text, offer menu
    bot.send_message(cid, 'متن دریافت شد — از منو استفاده کنید یا /menu', reply_markup=make_menu())

# Photo handler (for barcode and general images)
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    # download highest quality photo
    file_info = bot.get_file(message.photo[-1].file_id)
    file_bytes = requests.get(f'https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}', timeout=15).content
    # try barcode decode
    decoded = read_barcode(file_bytes)
    if decoded:
        # send decoded results plus search links
        for d in decoded:
            bot.reply_to(message, f'بارکد خوانده شد: {d}\nجستجوی وب برای آن...')
            links = google_search(d)
            if links:
                bot.send_message(message.chat.id, '\n'.join(links[:5]))
        return
    # else just ack
    bot.reply_to(message, 'عکس دریافت شد. برای خواندن بارکد، از عکس بارکد استفاده کنید.')

# Text -> image handler (user sends /img Your text...)
@bot.message_handler(commands=['img'])
def cmd_img(message):
    try:
        content = message.text.split(' ',1)[1]
        bio = text_to_image(content)
        bot.send_photo(message.chat.id, photo=bio)
    except Exception:
        bot.reply_to(message, 'مثال: /img متن شما')

# Webhook route for Flask
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook_handler():
    json_str = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

# Health check (optional)
@app.route('/')
def index():
    return 'Bot is running', 200

# --- Webhook setup on start ---
def setup_webhook():
    webhook_url = WEBHOOK_URL.rstrip('/') + WEBHOOK_PATH
    logger.info(f'Setting webhook: {webhook_url}')
    bot.remove_webhook()
    r = bot.set_webhook(url=webhook_url)
    logger.info('Webhook set: %s' % r)

# --- App entrypoint ---
if __name__ == '__main__':
    init_db()
    setup_webhook()
    # Flask runs and bot processes via webhook
    app.run(host='0.0.0.0', port=PORT)

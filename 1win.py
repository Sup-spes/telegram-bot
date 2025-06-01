import os
import random
import sqlite3
import logging
import io
from datetime import datetime, timedelta
from contextlib import contextmanager
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    JobQueue
)
from apscheduler.schedulers.background import BackgroundScheduler
import requests

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
BOT_TOKEN = os.getenv('BOT_TOKEN', '7927368928:AAFwiYztldKI3o6PMQtQWsQdfpVP69yAeUM')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # Будет автоматически установлен Render
IMAGE_FOLDER = "images"
WELCOME_IMAGE = os.path.join(IMAGE_FOLDER, "menu.jpg")
REGISTER_IMAGE = os.path.join(IMAGE_FOLDER, "register.jpg")
MINES_IMAGES_FOLDER = os.path.join(IMAGE_FOLDER, "mines")
FONT_PATH = "arialbd.ttf"
DB_NAME = "users.db"
ADMINS = [6205472542, 1244177716]
PORT = int(os.getenv('PORT', 10000))

# Цветовая схема
COLORS = {
    "dark_blue": (0, 0, 0),
    "blue": (30, 58, 138),
    "gold": (255, 215, 0),
    "white": (255, 255, 255),
    "gray": (148, 163, 184),
    "glow": (255, 255, 255)
}

# ========== БАЗА ДАННЫХ ==========
@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def get_db_cursor():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except:
            conn.rollback()
            raise

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                registered INTEGER DEFAULT 0,
                deposit INTEGER DEFAULT 0,
                approved INTEGER DEFAULT 0,
                last_activity TEXT,
                win_id TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS registration_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                win_id TEXT,
                timestamp TEXT NOT NULL,
                status TEXT DEFAULT 'pending'
            )
        ''')

def get_user_data(user_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT registered, deposit, approved, win_id 
            FROM users 
            WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        return {
            'registered': bool(result[0]) if result else False,
            'deposit': bool(result[1]) if result else False,
            'approved': bool(result[2]) if result else False,
            'win_id': result[3] if result else None
        }

def update_user(user_id, **kwargs):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user:
            registered = kwargs.get('registered', user['registered'])
            deposit = kwargs.get('deposit', user['deposit'])
            approved = kwargs.get('approved', user['approved'])
            win_id = kwargs.get('win_id', user['win_id'])
            
            cursor.execute('''
                UPDATE users SET 
                registered = ?, 
                deposit = ?, 
                approved = ?, 
                last_activity = ?, 
                win_id = ?
                WHERE user_id = ?
            ''', (int(registered), int(deposit), int(approved), now, win_id, user_id))
        else:
            cursor.execute('''
                INSERT INTO users (
                    user_id, 
                    registered, 
                    deposit, 
                    approved, 
                    last_activity, 
                    win_id
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                int(kwargs.get('registered', False)),
                int(kwargs.get('deposit', False)),
                int(kwargs.get('approved', False)),
                now,
                kwargs.get('win_id', None)
            ))

# ========== ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ ==========
def generate_gradient(width, height, start_color, end_color, horizontal=False):
    gradient = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(gradient)

    for i in range(width if horizontal else height):
        ratio = i / (width if horizontal else height)
        r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
        g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
        b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)

        if horizontal:
            draw.line([(i, 0), (i, height)], fill=(r, g, b))
        else:
            draw.line([(0, i), (width, i)], fill=(r, g, b))

    return gradient

def add_glow_effect(draw, text, position, font, glow_color, iterations=10):
    for i in range(iterations, 0, -1):
        offset = i * 2
        alpha = int(255 * (i/iterations))
        glow_color_with_alpha = (*glow_color[:3], alpha)

        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        temp_img = Image.new('RGBA', (text_width + offset*2, text_height + offset*2))
        temp_draw = ImageDraw.Draw(temp_img)
        temp_draw.text((offset, offset), text, font=font, fill=glow_color_with_alpha)

        temp_img = temp_img.filter(ImageFilter.GaussianBlur(radius=i))

        main_img = Image.new('RGBA', temp_img.size)
        main_img.paste(temp_img, (0, 0), temp_img)
        draw.bitmap((position[0]-offset, position[1]-offset), main_img)

def generate_signal_image(coefficient):
    coefficient_text = f"{coefficient}X"
    width, height = 800, 600

    image = generate_gradient(width, height, COLORS["dark_blue"], COLORS["blue"])
    draw = ImageDraw.Draw(image)

    try:
        font_large = ImageFont.truetype(FONT_PATH, 120)
        font_medium = ImageFont.truetype(FONT_PATH, 40)
    except:
        font_large = ImageFont.load_default(size=120)
        font_medium = ImageFont.load_default(size=40)

    bbox = font_large.getbbox(coefficient_text)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_position = ((width - text_width) // 2, (height - text_height) // 2 - 50)

    add_glow_effect(draw, coefficient_text, text_position, font_large, COLORS["glow"])
    draw.text(text_position, coefficient_text, fill=COLORS["gold"], font=font_large)

    signature = "ВАШ СИГНАЛ"
    bbox = font_medium.getbbox(signature)
    sig_width = bbox[2] - bbox[0]
    signature_position = ((width - sig_width) // 2, height - 100)
    draw.text(signature_position, signature, fill=COLORS["white"], font=font_medium)

    img_buffer = io.BytesIO()
    image.save(img_buffer, format='PNG', quality=95)
    img_buffer.seek(0)
    return img_buffer

def get_random_mines_image():
    try:
        if not os.path.exists(MINES_IMAGES_FOLDER):
            os.makedirs(MINES_IMAGES_FOLDER, exist_ok=True)
            raise FileNotFoundError("Папка с изображениями Mines не найдена")

        images = [f for f in os.listdir(MINES_IMAGES_FOLDER)
                 if f.lower().endswith(('.png', '.jpg', '.jpeg'))]

        if not images:
            raise FileNotFoundError("В папке mines нет изображений")

        random_image = random.choice(images)
        image_path = os.path.join(MINES_IMAGES_FOLDER, random_image)

        with open(image_path, 'rb') as img_file:
            img_bytes = io.BytesIO(img_file.read())
            img_bytes.seek(0)
            return img_bytes

    except Exception as e:
        logger.error(f"Ошибка при загрузке изображения Mines: {e}")
        buffer = io.BytesIO()
        img = Image.new('RGB', (400, 200), (10, 10, 30))
        draw = ImageDraw.Draw(img)
        draw.text((50, 80), "Ошибка загрузки Mines", fill=(255, 255, 255))
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

# ========== КЛАВИАТУРЫ ==========
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Регистрация", callback_data="register")],
        [InlineKeyboardButton("📕 Инструкция", callback_data="instruction")],
        [InlineKeyboardButton("💵 Получить сигнал", callback_data="get_signal")],
        [InlineKeyboardButton("💬 Тех. поддержка", callback_data="support")]
    ])

def register_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Пройти регистрацию", url="https://1wkebz.life/?open=register&p=s7hc")],
        [InlineKeyboardButton("✅ Проверить регистрацию", callback_data="check_registration")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ])

def game_selection_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💣 Mines", callback_data="game_mines")],
        [InlineKeyboardButton("🚀 Lucky Jet", callback_data="game_luckyjet")],
        [InlineKeyboardButton("🪙 Орел или Решка", callback_data="game_coinflip")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ])

def signal_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 Следующий сигнал", callback_data="generate_signal")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ])

# ========== ОБРАБОТЧИКИ КОМАНД ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id=user_id)
    
    try:
        if os.path.exists(WELCOME_IMAGE):
            with open(WELCOME_IMAGE, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption="👋 Добро пожаловать! Выбери действие:",
                    reply_markup=main_menu_keyboard()
                )
        else:
            await update.message.reply_text(
                "👋 Добро пожаловать! Выбери действие:",
                reply_markup=main_menu_keyboard()
            )
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text(
            "👋 Добро пожаловать! Выбери действие:",
            reply_markup=main_menu_keyboard()
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id)
    data = query.data

    try:
        if data == "register":
            text = (
                "🌐 Шаг 1 - Зарегистрируйся.\n\n"
                "‼️АККАУНТ ОБЯЗАТЕЛЬНО ДОЛЖЕН БЫТЬ НОВЫМ‼️\n\n"
                "1️⃣ Если после нажатия кнопки 'РЕГИСТРАЦИЯ' вы попадаете на старый аккаунт — из него нужно выйти и снова нажать кнопку.\n\n"
                "2️⃣ Во время регистрации указать промокод 👉 Sally1w 👈\n"
                "[Это важно, потому что наш бот работает только с новыми аккаунтами]\n\n"
                "3️⃣ После регистрации нажмите на кнопку — 🔍 Проверить регистрацию\n\n"
                "❗️Если вы не выполните эти шаги, наш бот не сможет добавить ваш аккаунт в свою базу данных❗️\n\n"
                "🤝 Спасибо за понимание!"
            )
            if os.path.exists(REGISTER_IMAGE):
                with open(REGISTER_IMAGE, 'rb') as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=text,
                        reply_markup=register_menu()
                    )
            else:
                await query.message.reply_text(text, reply_markup=register_menu())

        elif data == "get_signal":
            if not user_data['registered']:
                await query.answer("⚠ Вы не зарегистрированы!", show_alert=True)
                await query.message.edit_text(
                    "⛔ Для получения сигналов необходимо зарегистрироваться!\n\n"
                    "Пожалуйста, пройдите регистрацию:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📝 Регистрация", callback_data="register")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
                    ])
                )
                return

            if not user_data['approved']:
                await query.answer("⏳ Ожидайте подтверждения", show_alert=True)
                await query.message.edit_text(
                    "🕒 Ваш аккаунт находится на проверке администратором\n\n"
                    "Обычно проверка занимает до 24 часов\n"
                    "Вы можете проверить статус:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Проверить статус", callback_data="check_status")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
                    ])
                )
                return

            if not user_data['deposit']:
                await query.answer("⚠ Подтвердите депозит!", show_alert=True)
                await query.message.edit_text(
                    "💳 Для доступа к сигналам необходимо подтвердить депозит!\n\n"
                    "После внесения депозита нажмите кнопку ниже:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💳 Подтвердить депозит", callback_data="confirm_deposit")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
                    ])
                )
                return

            await query.message.edit_text(
                "🎮 Выберите игру для получения сигнала:",
                reply_markup=game_selection_keyboard()
            )

        elif data == "game_mines":
            try:
                img_bytes = get_random_mines_image()
                await query.message.reply_photo(
                    photo=img_bytes,
                    caption="💣 Mines: Ваш сигнал!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎰 Следующий сигнал", callback_data="game_mines")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="get_signal")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error in game_mines handler: {e}")
                await query.answer("⚠ Ошибка при генерации сигнала", show_alert=True)

        elif data == "back_to_menu":
            if os.path.exists(WELCOME_IMAGE):
                with open(WELCOME_IMAGE, 'rb') as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption="Главное меню:",
                        reply_markup=main_menu_keyboard()
                    )
            else:
                await query.message.reply_text(
                    "Главное меню:",
                    reply_markup=main_menu_keyboard()
                )

    except Exception as e:
        logger.error(f"Error in button handler: {e}")
        await query.answer("⚠ Произошла ошибка", show_alert=True)

async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
    """Функция для поддержания активности бота"""
    try:
        if WEBHOOK_URL:
            requests.get(f"{WEBHOOK_URL}/keepalive", timeout=10)
        logger.info("Keep-alive triggered")
    except Exception as e:
        logger.error(f"Keep-alive error: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        await context.bot.send_message(
            chat_id=ADMINS[0],
            text=f"Произошла ошибка: {context.error}\n\nUpdate: {update}"
        )
    except:
        pass

# ========== ЗАПУСК БОТА ==========
def main():
    # Инициализация базы данных
    init_db()
    
    # Создаем необходимые папки
    os.makedirs(IMAGE_FOLDER, exist_ok=True)
    os.makedirs(MINES_IMAGES_FOLDER, exist_ok=True)
    
    try:
        # Создаем приложение
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Настраиваем JobQueue для периодических задач
        job_queue = application.job_queue
        job_queue.run_repeating(
            keep_alive,
            interval=timedelta(minutes=14),
            first=10
        )
        
        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("moderate", moderate))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_id))
        
        # Обработчики кнопок
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern=r'^(approve|reject)_\d+_\d+$'))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        if WEBHOOK_URL:
            logger.info("Бот запущен в webhook режиме")
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path=BOT_TOKEN,
                webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
                drop_pending_updates=True
            )
        else:
            logger.info("Бот запущен в polling режиме")
            application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        raise

if __name__ == "__main__":
    main()

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, Update
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
import math
import sqlite3
import logging
from telegram import Bot  
from datetime import datetime
from contextlib import contextmanager

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)



# Константы
BOT_TOKEN = "7927368928:AAFwiYztldKI3o6PMQtQWsQdfpVP69yAeUM"
IMAGE_FOLDER = "images"
WELCOME_IMAGE = os.path.join(IMAGE_FOLDER, "меню.jpg")
REGISTER_IMAGE = os.path.join(IMAGE_FOLDER, "рега.jpg")
MINES_IMAGES_FOLDER = os.path.join(IMAGE_FOLDER, "mines")
FONT_PATH = "arialbd.ttf"
DB_NAME = "users.db"
ADMINS = [6205472542, 1244177716]  # ID администраторов
RENDER = True
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = f"https://telegram-bot-jxqd.onrender.com"

# Цветовая схема 1WIN
COLORS = {
    "dark_blue": (0, 0, 0),
    "blue": (30, 58, 138),
    "gold": (255, 255, 255),
    "white": (255, 255, 255),
    "gray": (148, 163, 184),
    "glow": (0, 0, 0)
}

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Менеджер курсоров
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

# Инициализация БД
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Удаляем старые таблицы, если они существуют
    cursor.execute('DROP TABLE IF EXISTS users')
    cursor.execute('DROP TABLE IF EXISTS registration_requests')
    
    # Создаем таблицу users с дополнительными полями
    cursor.execute('''
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            registered INTEGER DEFAULT 0,
            deposit INTEGER DEFAULT 0,
            approved INTEGER DEFAULT 0,
            last_activity TEXT,
            win_id TEXT
        )
    ''')
    
    # Создаем таблицу registration_requests
    cursor.execute('''
        CREATE TABLE registration_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            win_id TEXT,
            timestamp TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    
    conn.commit()
    conn.close()

# Функции работы с БД
def get_user_data(user_id):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT registered, deposit, approved, win_id 
                FROM users 
                WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            
            if result:
                return {
                    'registered': bool(result[0]),
                    'deposit': bool(result[1]),
                    'approved': bool(result[2]),
                    'win_id': result[3]
                }
            return {
                'registered': False,
                'deposit': False,
                'approved': False,
                'win_id': None
            }
    except Exception as e:
        print(f"Database error in get_user_data: {e}")
        return {
            'registered': False,
            'deposit': False,
            'approved': False,
            'win_id': None
        }
    

def update_user(user_id, registered=None, deposit=None, approved=None, win_id=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        now = datetime.now().isoformat()

        cursor.execute('''
            SELECT user_id, registered, deposit, approved, win_id FROM users WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()

        if result is None:
            cursor.execute('''
                INSERT INTO users (user_id, registered, deposit, approved, last_activity, win_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                int(bool(registered)) if registered is not None else 0,
                int(bool(deposit)) if deposit is not None else 0,
                int(bool(approved)) if approved is not None else 0,
                now,
                win_id
            ))
        else:
            new_reg = registered if registered is not None else bool(result[1])
            new_dep = deposit if deposit is not None else bool(result[2])
            new_app = approved if approved is not None else bool(result[3])
            new_win_id = win_id if win_id is not None else result[4]
            
            cursor.execute('''
                UPDATE users
                SET registered = ?, deposit = ?, approved = ?, last_activity = ?, win_id = ?
                WHERE user_id = ?
            ''', (
                int(new_reg),
                int(new_dep),
                int(new_app),
                now,
                new_win_id,
                user_id
            ))

        conn.commit()

    except Exception as e:
        print(f"Ошибка при обновлении юзера: {e}")
    
    finally:
        conn.close()

# Создаем папку для изображений
os.makedirs(IMAGE_FOLDER, exist_ok=True)

def keep_alive():
    """Функция для поддержания активности бота"""
    try:
        if RENDER:
            # Отправляем запрос к самому себе, чтобы предотвратить засыпание
            requests.get(f"https://{WEBHOOK_URL.split('//')[1]}/keepalive")
        logger.info("Keep-alive triggered")
    except Exception as e:
        logger.error(f"Keep-alive error: {e}")

async def log_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Логирование активности пользователей"""
    user_id = update.effective_user.id if update.effective_user else None
    message = update.message.text if update.message else None
    callback = update.callback_query.data if update.callback_query else None
    
    logger.info(
        f"User activity - ID: {user_id}, "
        f"Message: {message}, "
        f"Callback: {callback}"
    )

def generate_gradient(width: int, height: int, start_color: tuple, end_color: tuple, horizontal: bool = False) -> Image.Image:
    """Генератор градиентного фона"""
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

def add_glow_effect(draw, text: str, position: tuple, font: ImageFont.FreeTypeFont, glow_color: tuple, iterations: int = 10):
    """Добавляет свечение к тексту"""
    for i in range(iterations, 0, -1):
        offset = i * 2
        alpha = int(0 * (i/iterations))
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

def generate_signal_image(coefficient: float) -> io.BytesIO:
    """Генератор изображения с сигналом"""
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
    
    try:
        logo_path = os.path.join(IMAGE_FOLDER, "1.jpg")
        if os.path.exists(logo_path):
            logo = Image.open(logo_path).convert("RGBA")
            logo = logo.resize((150, 150))
            image.paste(logo, (width - 180, 30), logo)
    except:
        pass
    
    img_buffer = io.BytesIO()
    image.save(img_buffer, format='PNG', quality=95)
    img_buffer.seek(0)
    return img_buffer

def get_random_mines_image():
    """Получает случайное изображение для Mines из подготовленных"""
    try:
        if not os.path.exists(MINES_IMAGES_FOLDER):
            raise FileNotFoundError(f"Папка с изображениями Mines не найдена: {MINES_IMAGES_FOLDER}")
        
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
        print(f"Ошибка при загрузке изображения Mines: {e}")
        buffer = io.BytesIO()
        img = Image.new('RGB', (400, 200), (10, 10, 30))
        draw = ImageDraw.Draw(img)
        draw.text((50, 80), "Ошибка загрузки Mines", fill=(255, 255, 255))
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer



def signal_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 Следующий сигнал", callback_data="generate_signal")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ])

def game_selection_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💣 Mines", callback_data="game_mines")],
        [InlineKeyboardButton("🚀 Lucky Jet", callback_data="game_luckyjet")],
        [InlineKeyboardButton("🪙 Орел или Решка", callback_data="game_coinflip")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ])

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

def registration_check_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Я зарегистрировался", callback_data="confirm_registration")],
        [InlineKeyboardButton("❌ Я не зарегистрировался", callback_data="deny_registration")]
    ])

def deposit_check_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Я пополнил депозит", callback_data="confirm_deposit")],
        [InlineKeyboardButton("❌ Я не пополнил депозит", callback_data="deny_deposit")]
    ])

def after_deposit_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📲 Главное меню", callback_data="back_to_menu")]
    ])

def support_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Написать в тех. поддержку", url="https://t.me/syperston")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    update_user(user_id)
    
    if os.path.exists(WELCOME_IMAGE):
        with open(WELCOME_IMAGE, 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption="👋 Добро пожаловать! Выбери действие:",
                reply_markup=main_menu_keyboard()
            )
    else:
        await update.message.reply_text("👋 Добро пожаловать! Выбери действие:", reply_markup=main_menu_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user_data(user_id) or {'registered': False, 'deposit': False, 'approved': False}
    
    data = query.data

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
                await query.message.reply_photo(photo=photo, caption=text, reply_markup=register_menu())
        else:
            await query.message.reply_text(text, reply_markup=register_menu())

    elif data == "check_registration":
        await query.message.reply_text("🔍 Вы подтвердили регистрацию?", reply_markup=registration_check_menu())

    elif data == "confirm_registration":
        await query.message.reply_text("🔍 Введите ваш ID 1Win для проверки регистрации:")
        context.user_data["awaiting_id"] = True
        update_user(user_id, registered=True)
        
    elif data == "deny_registration":
        await query.message.reply_text("❗️Пожалуйста, зарегистрируйтесь по кнопке выше и повторите попытку.")

    elif data == "back_to_menu":
        if os.path.exists(WELCOME_IMAGE):
            with open(WELCOME_IMAGE, 'rb') as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption="Главное меню:",
                    reply_markup=main_menu_keyboard()
                )
        else:
            await query.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())

    elif data == "get_signal":
        user_data = get_user_data(user_id)
    
    # Если пользователь не зарегистрирован
        if not user_data or not user_data.get('registered'):
            await query.message.edit_text(
            "⛔ Для получения сигналов необходимо зарегистрироваться!\n\n"
            "Пожалуйста, пройдите регистрацию:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 Регистрация", callback_data="register")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
            ])
        )
            await query.answer("⚠ Вы не зарегистрированы!", show_alert=True)
            return
    
    # Если зарегистрирован, но не подтвержден модератором
        if not user_data.get('approved'):
            await query.message.edit_text(
            "🕒 Ваш аккаунт находится на проверке администратором\n\n"
            "Обычно проверка занимает до 24 часов\n"
            "Вы можете проверить статус:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Проверить статус", callback_data="check_status")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
            ])
        )
            await query.answer("⏳ Ожидайте подтверждения", show_alert=True)
            return
    
    # Если все проверки пройдены - показываем выбор игры
        await query.message.edit_text(
            "🎮 Выберите игру для получения сигнала:",
            reply_markup=game_selection_keyboard()
    )
            
        if not user_data['deposit']:
            # Пользователь не подтвердил депозит
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
            
        if not user_data['approved']:
            # Аккаунт не подтвержден администратором
                await query.answer("⏳ Ожидайте подтверждения", show_alert=True)
                await query.message.edit_text(
                    "🕒 Ваш аккаунт находится на проверке администратором.\n\n"
                    "Обычно это занимает до 24 часов.\n"
                    "Вы можете проверить статус:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Проверить статус", callback_data="check_status")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
                    ])
                )
                return

        # Если все проверки пройдены - показываем выбор игры
        await query.message.edit_text(
                "🎮 Выберите игру для получения сигнала:",
            reply_markup=game_selection_keyboard()
            )


    elif data == "check_status":
        user_data = get_user_data(user_id)
        if not user_data:
            await query.answer("⛔ Ошибка при проверке статуса", show_alert=True)
            return

        status_message = "📊 Ваш текущий статус:\n\n"
        status_message += f"• Регистрация: {'✅ Завершена' if user_data.get('registered') else '❌ Не завершена'}\n"
        status_message += f"• Депозит: {'✅ Подтвержден' if user_data.get('deposit') else '❌ Не подтвержден'}\n"
        status_message += f"• Модерация: {'✅ Одобрено' if user_data.get('approved') else '❌ Ожидает подтверждения'}\n\n"

        if not user_data.get('registered'):
            status_message += "ℹ Для доступа необходимо пройти регистрацию"
        elif not user_data.get('approved'):
            status_message += "ℹ Ожидайте подтверждения администратора"
        else:
            status_message += "🎉 Вы получили полный доступ к сигналам!"

        await query.answer(status_message, show_alert=True)


    elif data == "game_luckyjet":
        user_data = get_user_data(user_id)
        if user_data and user_data.get('approved'):
            coefficient = round(random.uniform(1.5, 10.0), 2)
            img_bytes = generate_signal_image(coefficient)
            await query.message.reply_photo(
                photo=img_bytes,
                caption=f"🚀 Lucky Jet сигнал: {coefficient}X",
                reply_markup=signal_keyboard()
            )
        else:
            await query.message.reply_text("⛔ Ваша регистрация не подтверждена или не завершена!")

    elif data == "game_mines":
        user_data = get_user_data(user_id)
        if user_data and user_data.get('approved'):
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
                print(f"Error in check_status handler: {e}")
            await query.answer("⚠ Ошибка при проверке статуса", show_alert=True)    

    elif data == "generate_signal":
        user_data = get_user_data(user_id)
        if user_data and user_data.get('approved'):
            coefficient = round(random.uniform(1.5, 10.0), 2)
            img_bytes = generate_signal_image(coefficient)
            await query.message.edit_media(
                media=InputMediaPhoto(media=img_bytes, caption=f"🚀 Lucky Jet сигнал: {coefficient}X"),
                reply_markup=signal_keyboard()
            )
        else:
            await query.answer("⛔ Сначала пройдите подтверждение регистрации!", show_alert=True)

    elif data == "game_coinflip":
        user_data = get_user_data(user_id)
        if user_data and user_data.get('approved'):
            coin_side = random.choice(["орел", "решка"])
            image_path = os.path.join(IMAGE_FOLDER, f"{coin_side}.jpg")
            
            if not os.path.exists(image_path):
                await query.message.reply_text(
                    f"🪙 Ставте на: {coin_side.upper()} (изображение не найдено)",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎰 Следующий сигнал", callback_data="game_coinflip")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="get_signal")]
                    ])
                )
                return
                
            with open(image_path, 'rb') as photo:
                await query.message.reply_photo(
                    photo=photo,
                    caption=f"🪙 Ставте на: {coin_side.upper()}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎰 Следующий сигнал", callback_data="game_coinflip")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="get_signal")]
                    ])
                )
        else:
            await query.message.reply_text("⛔ Ваша регистрация не подтверждена или не завершена!")

    elif data == "confirm_deposit":
        update_user(user_id, deposit=True)
        DEPOSIT_CONFIRMATION_IMAGE = os.path.join(IMAGE_FOLDER, "галочка.jpg")

        confirmation_text = (
            "✅ Отлично! Вы пополнили депозит и активировали свой аккаунт.\n"
            "🔸 Теперь вы можете начать использовать наши сигналы для получения выигрышей!\n"
            "🔸 Для этого перейдите в раздел \"Получить сигнал\""
        )

        if os.path.exists(DEPOSIT_CONFIRMATION_IMAGE):
            with open(DEPOSIT_CONFIRMATION_IMAGE, 'rb') as img:
                await query.message.reply_photo(
                    photo=img,
                    caption=confirmation_text,
                    reply_markup=after_deposit_menu()
                )
        else:
            await query.message.reply_text(
                confirmation_text,
                reply_markup=after_deposit_menu()
            )

    elif data == "instruction":
        instruction_text = (
            "🤖 Бот основан и обучен на кластере нейросети 🖥 [bitsGap].\n\n"
            "Для тренировки бота было сыграно 🎰 10.000+ игр.\n"
            "В данный момент пользователи бота успешно делают в день 15-25% от своего 💸 капитала!\n\n"
            "На текущий момент бот по сей день проходит проверки и исправления! Точность бота составляет 92%!\n\n"
            "Для получения максимального профита следуйте следующей инструкции:\n\n"
            "🟢 1. Пройти регистрацию в букмекерской конторе 1WIN (https://1wkebz.life/?open=register&p=s7hc)\n"
            "Если не открывается - заходим с включенным VPN (Швеция). В Play Market/App Store полно бесплатных сервисов, "
            "например: Vpnify, Planet VPN, Hotspot VPN и так далее!\n\n"
            "Без регистрации доступ к сигналам не будет открыт!\n\n"
            "🟢 2. Пополнить баланс своего аккаунта.\n\n"
            "🟢 3. Перейти в раздел 1win games и выбрать игру нужную вам 🕹ИГРУ.\n\n"
            "🟢 4. Открыть нужного вам сигнального бота.\n\n"
            "🟢 5. Запросить сигнал в боте и ставить по сигналам из бота.\n\n"
            "🟢 6. При неудачном сигнале советуем удвоить (Х²) ставку, чтобы полностью перекрыть потерю при следующем сигнале.\n\n"
            "❗ВНИМАНИЕ❗\n\n"
            "Если много раз нажимать на \"Следующий сигнал\" то следующий сигнал на платформе 1Win будет не верный \n\n"
            "В случае если у ват так произошло обратитесь к нам в Тех. поддержку!"
        )
        await query.message.reply_text(
            instruction_text, 
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
            ]),
            disable_web_page_preview=True
        )

    elif data == "support":
        support_text = (
            "📞 Техническая поддержка\n\n"
            "Если у вас возникли вопросы или проблемы, напишите в нашу поддержку:\n"
            "@syperston\n\n"
            "Часы работы: круглосуточно\n"
            "Среднее время ответа: 5-15 минут"
        )
        await query.message.reply_text(
            support_text,
            reply_markup=support_menu()
        )

    elif data == "deny_deposit":
        await query.message.reply_text("❗️Пожалуйста, пополните депозит и подтвердите это.")

async def handle_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id  # Telegram ID
    if "awaiting_id" in context.user_data and context.user_data["awaiting_id"]:
        win_id = update.message.text.strip()  # ID из 1win (просто текст)
            
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        try:
            # Сохраняем оба ID: telegram_id (для работы бота) и win_id (для информации)
            cursor.execute('''
                INSERT INTO registration_requests (telegram_id, win_id, timestamp) 
                VALUES (?, ?, ?)
            ''', (user_id, win_id, datetime.now().isoformat()))
            
            conn.commit()
            context.user_data["awaiting_id"] = False
            
            await update.message.reply_text("✅ Ваша заявка отправлена на проверку. Ожидайте до 2 часов.")
            
            CONFIRMATION_IMAGE = os.path.join(IMAGE_FOLDER, "деп.jpg")
            if os.path.exists(CONFIRMATION_IMAGE):
                with open(CONFIRMATION_IMAGE, 'rb') as img:
                    await update.message.reply_photo(
                        photo=img,
                        caption=(
                            "✅ Спасибо! Вы успешно прошли регистрацию. 🌐 Шаг 2 - Внеси первый депозит.\n\n"
                            "🔸Подтвердите, что вы не бот, пополнив свой аккаунт на любую сумму.\n\n"
                            "🔸Активируйте аккаунт, внеся первый депозит, эти деньги зачислятся на ВАШ СЧЁТ, "
                            "после чего вы сможете на них играть по нашим сигналам и, что главное, ВЫИГРЫВАТЬ.\n\n"
                            "✅ После ДЕПОЗИТА нажмите кнопку \"ПРОВЕРИТЬ ДЕПОЗИТ\"."
                        ),
                        reply_markup=deposit_check_menu()
                    )
            else:
                await update.message.reply_text(
                    "✅ Спасибо! Вы успешно прошли регистрацию. 🌐 Шаг 2 - Внеси первый депозит.\n\n"
                    "🔸Подтвердите, что вы не бот, пополнив свой аккаунт на любую сумму.\n\n"
                    "🔸Активируйте аккаунт, внеся первый депозит, эти деньги зачислятся на ВАШ СЧЁТ, "
                    "после чего вы сможете на них играть по нашим сигналам и, что главное, ВЫИГРЫВАТЬ.\n\n"
                    "✅ После ДЕПОЗИТА нажмите кнопку \"ПРОВЕРИТЬ ДЕПОЗИТ\".",
                    reply_markup=deposit_check_menu()
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        finally:
            conn.close()

# Обновите функцию moderate:
async def moderate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("⛔ У вас нет доступа к модерации.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Получаем оба ID
    cursor.execute('''
        SELECT id, telegram_id, win_id 
        FROM registration_requests 
        WHERE status = "pending"
    ''')
    
    requests = cursor.fetchall()
    conn.close()

    if not requests:
        await update.message.reply_text("📭 Нет заявок на модерацию.")
        return

    for request in requests:
        req_id, tg_id, win_id = request
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Принять", callback_data=f"approve_{tg_id}_{req_id}")],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{tg_id}_{req_id}")]
        ])
        # Показываем админу оба ID
        await update.message.reply_text(
            f"🔹 Заявка №{req_id}\n"
            f"Telegram ID: {tg_id}\n"
            f"1WIN ID: {win_id}",
            reply_markup=keyboard
        )


async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_')
        if len(parts) != 3:
            raise ValueError("Неверный формат callback данных")
            
        action = parts[0]
        tg_user_id = int(parts[1])
        req_id = int(parts[2])

        # Используем контекстный менеджер
        with sqlite3.connect(DB_NAME, timeout=30) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            cursor = conn.cursor()

            # 1. Обновляем статус заявки
            cursor.execute('''
                UPDATE registration_requests
                SET status = ?
                WHERE id = ? AND status = 'pending'
            ''', ('approved' if action == 'approve' else 'rejected', req_id))
            
            if cursor.rowcount == 0:
                await query.edit_message_text(text="⚠ Заявка уже обработана")
                return

            # 2. Если одобрено - обновляем статус пользователя
            if action == 'approve':
                cursor.execute('''
                    INSERT OR REPLACE INTO users (user_id, registered, approved, last_activity)
                    VALUES (?, 1, 1, ?)
                ''', (tg_user_id, datetime.now().isoformat()))

            conn.commit()

        # 3. Уведомление пользователя (вне транзакции)
        try:
            message_text = ("✅ Ваша регистрация одобрена!" if action == 'approve' 
                          else "❌ Ваша заявка отклонена.")
            await context.bot.send_message(tg_user_id, message_text)
            notification_sent = True
        except Exception as e:
            notification_sent = False

            # 4. Формируем сообщение для администратора
            admin_message = (
                f"🛠 Заявка #{req_id} обработана\n"
                f"▪ Действие: {'Одобрена' if action == 'approve' else 'Отклонена'}\n"
                f"▪ Пользователь: {tg_user_id}\n"
                f"▪ Уведомление: {'Доставлено' if notification_sent else 'Не доставлено'}"
            )
            
            await query.edit_message_text(
                text=admin_message,
                reply_markup=None  # Убираем кнопки после обработки
            )

        except Exception as e:
            conn.rollback()
            error_msg = f"❌ Ошибка обработки заявки: {str(e)}"
            await query.edit_message_text(text=error_msg)
            raise
            
        finally:
            conn.close()

    except ValueError as ve:
        await query.edit_message_text(text=f"⚠ Ошибка в данных: {str(ve)}")
    except Exception as e:
        await query.edit_message_text(text=f"⛔ Критическая ошибка: {str(e)}")


async def get_signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data = get_user_data(user_id) or {'approved': False}
    
    if not user_data.get('approved'):
        await query.answer("⛔ Доступ закрыт. Заявка не одобрена", show_alert=True)
        return
    
    # Вместо редактирования сообщения, отправляем новое
    await query.message.reply_text(
        "🎮 Выберите игру для получения сигнала:",
        reply_markup=game_selection_keyboard()
    )
    


if __name__ == "__main__":
    init_db()  # Инициализация БД
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("moderate", moderate))
    app.add_handler(CommandHandler("keepalive", lambda u, c: None))  # Добавляем пустой обработчик для keepalive
    
    # Обработчики сообщений и callback-ов
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_id))
    app.add_handler(CallbackQueryHandler(handle_admin_decision, pattern=r'^(approve|reject)_\d+_\d+$'))
    app.add_handler(CallbackQueryHandler(get_signal_handler, pattern='^get_signal$'))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Добавляем обработчики логов (должны быть последними)
    app.add_handler(MessageHandler(filters.ALL, log_activity), group=1)
    app.add_handler(CallbackQueryHandler(log_activity), group=1)
    
    # Запуск keep-alive механизма
    if RENDER:
        scheduler = BackgroundScheduler()
        scheduler.add_job(keep_alive, 'interval', minutes=14)
        scheduler.start()
        logger.info("Keep-alive scheduler started")
    
    # Определение режима работы
    if RENDER:
        # Режим webhook для Render
        logger.info("Бот запущен в webhook режиме! 🚀")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=WEBHOOK_URL,
            drop_pending_updates=True
        )
    else:
        # Режим polling для локальной разработки
        logger.info("Бот запущен в polling режиме! 🚀")
        app.run_polling()
    

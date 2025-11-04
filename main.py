import os
import logging
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import pytz  # Добавляем для работы с часовыми поясами

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Московский часовой пояс
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Создаем Flask приложение для порта
app = Flask(__name__)

# Глобальные переменные
user_data = {}
scheduler = None

@app.route('/')
def home():
    return "🤖 Бот для повторения по методу Эббингауза работает! 🚀"

@app.route('/ping')
def ping():
    return "pong", 200

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": "running", "timestamp": datetime.now().isoformat()}), 200

def run_flask():
    """Запускает Flask сервер в отдельном потоке"""
    app.run(host='0.0.0.0', port=5000, debug=False)

# Константы
DATA_FILE = "user_data.json"
INTERVALS = [
    timedelta(minutes=30),
    timedelta(days=1),
    timedelta(days=2),  
    timedelta(days=8),
    timedelta(days=30)
]

def get_moscow_time():
    """Возвращает текущее время в Московском часовом поясе"""
    return datetime.now(MOSCOW_TZ)

def parse_moscow_time(date_string):
    """Парсит строку даты и возвращает в Московском часовом поясе"""
    try:
        naive_dt = datetime.strptime(date_string, '%d.%m.%Y %H:%M')
        return MOSCOW_TZ.localize(naive_dt)
    except ValueError:
        raise ValueError("Неверный формат даты")

def load_data():
    """Загрузка данных из файла"""
    global user_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for user_id_str, topics in data.items():
                    user_id = int(user_id_str)
                    user_data[user_id] = []
                    for topic in topics:
                        # Загружаем даты с учетом часового пояса
                        study_date = datetime.fromisoformat(topic['study_date'])
                        if study_date.tzinfo is None:
                            study_date = MOSCOW_TZ.localize(study_date)
                        
                        topic_data = {
                            'topic': topic['topic'],
                            'study_date': study_date,
                            'repetitions': [
                                {
                                    'date': MOSCOW_TZ.localize(datetime.fromisoformat(rep['date'])) if datetime.fromisoformat(rep['date']).tzinfo is None else datetime.fromisoformat(rep['date']),
                                    'completed': rep['completed']
                                }
                                for rep in topic['repetitions']
                            ]
                        }
                        user_data[user_id].append(topic_data)
            print(f"✅ Данные загружены из {DATA_FILE}")
        else:
            print("📁 Файл данных не найден, начинаем с чистого листа")
            user_data = {}
    except Exception as e:
        print(f"❌ Ошибка при загрузке данных: {e}")
        user_data = {}

def save_data():
    """Сохранение данных в файл"""
    try:
        data_to_save = {}
        for user_id, topics in user_data.items():
            data_to_save[str(user_id)] = []
            for topic in topics:
                topic_data = {
                    'topic': topic['topic'],
                    'study_date': topic['study_date'].isoformat(),
                    'repetitions': [
                        {
                            'date': rep['date'].isoformat(),
                            'completed': rep['completed']
                        }
                        for rep in topic['repetitions']
                    ]
                }
                data_to_save[str(user_id)].append(topic_data)
        
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"💾 Данные сохранены в {DATA_FILE}")
    except Exception as e:
        print(f"❌ Ошибка при сохранении данных: {e}")

async def send_reminder(application, user_id, topic_name, repetition_date, repetition_number):
    """Отправка напоминания пользователю"""
    try:
        # Конвертируем время в московское для отображения
        moscow_time = repetition_date.astimezone(MOSCOW_TZ)
        
        message = f"🔔 **Напоминание о повторении**\n\n"
        message += f"📚 Тема: {topic_name}\n"
        message += f"🕐 Время повторения: {moscow_time.strftime('%d.%m.%Y %H:%M')} (МСК)\n"
        message += f"📅 Это повторение №{repetition_number} по методу Эббингауза\n\n"
        message += "Используйте /done чтобы отметить как выполненное"
        
        await application.bot.send_message(
            chat_id=user_id, 
            text=message,
            parse_mode='Markdown'
        )
        print(f"✅ Напоминание отправлено пользователю {user_id} для темы '{topic_name}'")
    except Exception as e:
        print(f"❌ Ошибка отправки напоминания: {e}")

def schedule_reminders(application):
    """Планирование всех напоминаний при запуске"""
    global scheduler
    
    if scheduler is None:
        scheduler = BackgroundScheduler(timezone=MOSCOW_TZ)  # Указываем московский часовой пояс
        scheduler.start()
        print("🕐 Планировщик напоминаний запущен (Московское время)")
    
    # Очищаем старые задания
    scheduler.remove_all_jobs()
    
    # Планируем напоминания для всех пользователей
    for user_id, topics in user_data.items():
        for topic_index, topic in enumerate(topics):
            for rep_index, repetition in enumerate(topic['repetitions']):
                if not repetition['completed'] and repetition['date'] > get_moscow_time():
                    job_id = f"reminder_{user_id}_{topic_index}_{rep_index}"
                    
                    scheduler.add_job(
                        send_reminder,
                        trigger=DateTrigger(run_date=repetition['date']),
                        args=[application, user_id, topic['topic'], repetition['date'], rep_index + 1],
                        id=job_id
                    )
                    print(f"📅 Запланировано напоминание: {job_id} на {repetition['date'].strftime('%d.%m.%Y %H:%M')} МСК")
    
    print(f"✅ Запланировано {len(scheduler.get_jobs())} напоминаний")

def schedule_single_reminder(application, user_id, topic_index, rep_index):
    """Планирование одного напоминания"""
    if scheduler is None:
        return
    
    topic = user_data[user_id][topic_index]
    repetition = topic['repetitions'][rep_index]
    
    if not repetition['completed'] and repetition['date'] > get_moscow_time():
        job_id = f"reminder_{user_id}_{topic_index}_{rep_index}"
        
        scheduler.add_job(
            send_reminder,
            trigger=DateTrigger(run_date=repetition['date']),
            args=[application, user_id, topic['topic'], repetition['date'], rep_index + 1],
            id=job_id
        )
        print(f"📅 Запланировано новое напоминание: {job_id} на {repetition['date'].strftime('%d.%m.%Y %H:%M')} МСК")

# Существующие функции бота с обновлением для московского времени
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🤖 Добро пожаловать в бота для повторения по методу Эббингауза!

Доступные команды:
/newtopic - добавить новую тему
/list - показать все темы
/done - отметить повторение как выполненное

🔔 *Новая функция:* автоматические напоминания о повторениях!
⏰ *Часовой пояс:* Московское время (UTC+3)
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def new_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Запишите тему, которую вы изучили:")
    context.user_data['waiting_for'] = 'topic'

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    waiting_for = context.user_data.get('waiting_for', None)
    
    if waiting_for == 'topic':
        context.user_data['temp_topic'] = user_text
        context.user_data['waiting_for'] = 'date'
        await update.message.reply_text(
            "🕐 Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ (Московское время)\nИли 'сейчас'"
        )
    
    elif waiting_for == 'date':
        try:
            if user_text.lower() == 'сейчас':
                study_date = get_moscow_time()  # Используем московское время
            else:
                study_date = parse_moscow_time(user_text)  # Парсим с учетом московского пояса
            
            topic = context.user_data['temp_topic']
            
            if user_id not in user_data:
                user_data[user_id] = []
            
            repetitions = []
            for interval in INTERVALS:
                repetition_date = study_date + interval
                repetitions.append({
                    'date': repetition_date,
                    'completed': False
                })
            
            topic_data = {
                'topic': topic,
                'study_date': study_date,
                'repetitions': repetitions
            }
            
            user_data[user_id].append(topic_data)
            save_data()
            
            # Планируем напоминания для новой темы
            topic_index = len(user_data[user_id]) - 1
            for rep_index in range(len(INTERVALS)):
                schedule_single_reminder(context.application, user_id, topic_index, rep_index)
            
            response = f"✅ Тема '{topic}' добавлена!\n\n📅 Расписание повторений (Московское время):\n"
            for i, rep in enumerate(repetitions, 1):
                status = "✅" if rep['completed'] else "⏳"
                moscow_time = rep['date'].astimezone(MOSCOW_TZ) if rep['date'].tzinfo else rep['date']
                response += f"{i}. {moscow_time.strftime('%d.%m.%Y %H:%M')} {status}\n"
            
            response += "\n🔔 Напоминания запланированы автоматически!"
            
            await update.message.reply_text(response)
            context.user_data.pop('temp_topic', None)
            context.user_data.pop('waiting_for', None)
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат даты! Попробуйте еще раз:")
    
    elif waiting_for == 'topic_choice':
        try:
            topic_index = int(user_text) - 1
            user_topics = user_data.get(user_id, [])
            
            if 0 <= topic_index < len(user_topics):
                context.user_data['selected_topic_index'] = topic_index
                context.user_data['waiting_for'] = 'repetition_choice'
                
                topic_data = user_topics[topic_index]
                response = f"🎯 Тема: {topic_data['topic']}\n\nВыберите номер повторения:\n"
                
                for i, repetition in enumerate(topic_data['repetitions'], 1):
                    status = "✅" if repetition['completed'] else "❌"
                    moscow_time = repetition['date'].astimezone(MOSCOW_TZ) if repetition['date'].tzinfo else repetition['date']
                    response += f"{i}. {moscow_time.strftime('%d.%m.%Y %H:%M')} {status}\n"
                
                await update.message.reply_text(response)
            else:
                await update.message.reply_text("❌ Неверный номер темы!")
                
        except ValueError:
            await update.message.reply_text("❌ Введите число!")
    
    elif waiting_for == 'repetition_choice':
        try:
            repetition_index = int(user_text) - 1
            topic_index = context.user_data['selected_topic_index']
            user_topics = user_data.get(user_id, [])
            
            if 0 <= repetition_index < len(user_topics[topic_index]['repetitions']):
                user_topics[topic_index]['repetitions'][repetition_index]['completed'] = True
                save_data()
                
                # Удаляем запланированное напоминание, если оно есть
                if scheduler:
                    job_id = f"reminder_{user_id}_{topic_index}_{repetition_index}"
                    job = scheduler.get_job(job_id)
                    if job:
                        job.remove()
                        print(f"🗑️ Удалено напоминание: {job_id}")
                
                context.user_data.pop('selected_topic_index', None)
                context.user_data.pop('waiting_for', None)
                
                topic_name = user_topics[topic_index]['topic']
                rep_date = user_topics[topic_index]['repetitions'][repetition_index]['date']
                moscow_time = rep_date.astimezone(MOSCOW_TZ) if rep_date.tzinfo else rep_date
                
                await update.message.reply_text(
                    f"✅ Повторение {repetition_index + 1} для '{topic_name}' выполнено!\nВремя: {moscow_time.strftime('%d.%m.%Y %H:%M')} МСК"
                )
            else:
                await update.message.reply_text("❌ Неверный номер повторения!")
                
        except ValueError:
            await update.message.reply_text("❌ Введите число!")
    
    else:
        await update.message.reply_text("🤔 Используйте команды: /start, /newtopic, /list, /done")

async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_data or not user_data[user_id]:
        await update.message.reply_text("📭 У вас пока нет добавленных тем.")
        return
    
    response = "📚 Ваши темы для повторения:\n\n"
    
    for topic_index, topic_data in enumerate(user_data[user_id], 1):
        response += f"🎯 Тема {topic_index}: {topic_data['topic']}\n"
        study_date = topic_data['study_date']
        moscow_study_time = study_date.astimezone(MOSCOW_TZ) if study_date.tzinfo else study_date
        response += f"   Изучена: {moscow_study_time.strftime('%d.%m.%Y %H:%M')} МСК\n"
        response += "   Повторения:\n"
        
        completed_count = sum(1 for rep in topic_data['repetitions'] if rep['completed'])
        total_count = len(topic_data['repetitions'])
        
        for rep_index, repetition in enumerate(topic_data['repetitions'], 1):
            status = "✅ Выполнено" if repetition['completed'] else "⏳ Ожидает"
            rep_date = repetition['date']
            moscow_rep_time = rep_date.astimezone(MOSCOW_TZ) if rep_date.tzinfo else rep_date
            response += f"   {rep_index}. {moscow_rep_time.strftime('%d.%m.%Y %H:%M')} МСК - {status}\n"
        
        response += f"   Прогресс: {completed_count}/{total_count} выполнено\n\n"
    
    await update.message.reply_text(response)

async def mark_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_data or not user_data[user_id]:
        await update.message.reply_text("❌ У вас нет тем для отметки.")
        return
    
    response = "📋 Выберите тему для отметки (введите номер):\n\n"
    for i, topic_data in enumerate(user_data[user_id], 1):
        completed = sum(1 for rep in topic_data['repetitions'] if rep['completed'])
        total = len(topic_data['repetitions'])
        response += f"{i}. {topic_data['topic']} ({completed}/{total} выполнено)\n"
    
    await update.message.reply_text(response)
    context.user_data['waiting_for'] = 'topic_choice'

async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Используйте /start, /newtopic, /list или /done"
    )

def main():
    """Основная функция запуска бота"""
    load_data()
    
    TOKEN = os.getenv('BOT_TOKEN')
    if not TOKEN:
        print("❌ Токен бота не найден!")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("newtopic", new_topic))
    application.add_handler(CommandHandler("list", list_topics))
    application.add_handler(CommandHandler("done", mark_done))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(MessageHandler(filters.COMMAND, handle_unknown))
    
    print("🚀 Запускаем Flask сервер для порта 5000...")
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Запускаем планировщик напоминаний
    schedule_reminders(application)
    
    print("🤖 Запускаем Telegram бота...")
    
    # Улучшенный запуск с автоматическим восстановлением
    while True:
        try:
            application.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                poll_interval=1,
                timeout=10,
                close_loop=False
            )
        except Exception as e:
            print(f"❌ Ошибка бота: {e}")
            print("🔄 Перезапускаем бота через 30 секунд...")
            time.sleep(30)
            # Пересоздаем application для чистого перезапуска
            application = Application.builder().token(TOKEN).build()
            # Пере добавляем обработчики
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("newtopic", new_topic))
            application.add_handler(CommandHandler("list", list_topics))
            application.add_handler(CommandHandler("done", mark_done))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
            application.add_handler(MessageHandler(filters.COMMAND, handle_unknown))
            # Перезапускаем планировщик
            schedule_reminders(application)

if __name__ == '__main__':
    main()

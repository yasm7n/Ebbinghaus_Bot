import os
import logging
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Создаем Flask приложение для порта
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Бот для повторения по методу Эббингауза работает! 🚀"

@app.route('/ping')
def ping():
    return "pong", 200

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": "running", "timestamp": datetime.now().isoformat()}), 200

@app.route('/status')
def status():
    return jsonify({
        "status": "operational",
        "service": "Ebbinghaus Bot",
        "timestamp": datetime.now().isoformat(),
        "users_count": len(user_data)
    }), 200

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

user_data = {}

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
                        topic_data = {
                            'topic': topic['topic'],
                            'study_date': datetime.fromisoformat(topic['study_date']),
                            'repetitions': [
                                {
                                    'date': datetime.fromisoformat(rep['date']),
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

# Функции бота (остаются без изменений)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🤖 Добро пожаловать в бота для повторения по методу Эббингауза!

Доступные команды:
/newtopic - добавить новую тему
/list - показать все темы
/done - отметить повторение как выполненное
    """
    await update.message.reply_text(welcome_text)

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
            "🕐 Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ\nИли 'сейчас'"
        )
    
    elif waiting_for == 'date':
        try:
            if user_text.lower() == 'сейчас':
                study_date = datetime.now()
            else:
                study_date = datetime.strptime(user_text, '%d.%m.%Y %H:%M')
            
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
            
            response = f"✅ Тема '{topic}' добавлена!\n\n📅 Расписание:\n"
            for i, rep in enumerate(repetitions, 1):
                status = "✅" if rep['completed'] else "⏳"
                response += f"{i}. {rep['date'].strftime('%d.%m.%Y %H:%M')} {status}\n"
            
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
                    response += f"{i}. {repetition['date'].strftime('%d.%m.%Y %H:%M')} {status}\n"
                
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
                
                context.user_data.pop('selected_topic_index', None)
                context.user_data.pop('waiting_for', None)
                
                topic_name = user_topics[topic_index]['topic']
                rep_date = user_topics[topic_index]['repetitions'][repetition_index]['date'].strftime('%d.%m.%Y %H:%M')
                
                await update.message.reply_text(
                    f"✅ Повторение {repetition_index + 1} для '{topic_name}' выполнено!\nВремя: {rep_date}"
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
        response += f"   Изучена: {topic_data['study_date'].strftime('%d.%m.%Y %H:%M')}\n"
        response += "   Повторения:\n"
        
        completed_count = sum(1 for rep in topic_data['repetitions'] if rep['completed'])
        total_count = len(topic_data['repetitions'])
        
        for rep_index, repetition in enumerate(topic_data['repetitions'], 1):
            status = "✅ Выполнено" if repetition['completed'] else "⏳ Ожидает"
            response += f"   {rep_index}. {repetition['date'].strftime('%d.%m.%Y %H:%M')} - {status}\n"
        
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
    
    # 🔧 ПОЛУЧАЕМ ТОКЕН ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
    TOKEN = os.getenv('BOT_TOKEN')
    
    if not TOKEN:
        print("❌ Токен бота не найден! Установите переменную окружения BOT_TOKEN.")
        return
    
    application = Application.builder().token(TOKEN).build()
    
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

if __name__ == '__main__':
    main()

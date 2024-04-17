import telebot
from telebot import types
import qrcode
import psycopg2
import datetime
import locale
import time
from datetime import datetime, timedelta
from io import BytesIO
from psycopg2 import OperationalError
from psycopg2 import InterfaceError
import pytz
import re



# Данные для подключения к базе данных
db_name = '-'
db_user = '-'
db_password = '-'
db_host = '-'

conn = psycopg2.connect(dbname=db_name, user=db_user, password=db_password, host=db_host)
cursor = conn.cursor()

def connect_to_database():
    try:
        conn = psycopg2.connect(dbname=db_name, user=db_user, password=db_password, host=db_host)
        return conn
    except OperationalError as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return None

# Переподключение при ошибке OperationalError
def ensure_database_connection():
    global conn
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
    except OperationalError:
        conn = connect_to_database()
    except InterfaceError:
        conn = connect_to_database()
        
bot = telebot.TeleBot('-')

# Словарь для хранения информации о пользователях
users = {}

@bot.message_handler(commands=['start'])
def start(message):
    ensure_database_connection()
    users[message.chat.id] = {"status": message.text, "auth_attempts": 0, "is_authenticated": False, "current_action": None, "current_step": None, "prev_message_id": None,"button_message": None, "admin": False}
    bot.send_message(message.chat.id, "Здравствуйте, введите логин и пароль через пробел (например, 'mylogin mypassword'):", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda message: message.chat.id in users and (users[message.chat.id]["current_action"]==None or users[message.chat.id]["current_action"].startswith("view")))
def handle_message(message):
    ensure_database_connection()
    chat_id = message.chat.id
    user_data = users[chat_id]
    if not user_data["is_authenticated"]:
        if len(message.text.split())!=2:
            users[chat_id]["auth_attempts"] += 1
            if users[chat_id]["auth_attempts"] >= 3:
                bot.send_message(chat_id, "Превышено количество попыток. Попробуйте позднее.")
                del users[chat_id]
            else:
                bot.send_message(chat_id, "Авторизация не удалась. Пожалуйста, попробуйте еще раз:")
        else:
            login, password = message.text.split()
            if not (login == "admin" and password == "admin"):
                cursor.execute("SELECT id, role FROM users WHERE login = %s AND password = %s", (login, password))
                result = cursor.fetchone()
                if result:
                    id, role = result
                    cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (chat_id,))
                    existing_user = cursor.fetchone()
                    if  not (existing_user and existing_user[0] != id):
                        users[chat_id].update({"user_id": id, "role": role, "auth_attempts": 0, "is_authenticated": True})
                        bot.send_message(chat_id, "Авторизация успешна!")
                        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                        buttons = [types.KeyboardButton(text) for text in ["Посмотреть расписание", "Список группы"]]
                        if role == "Студент":
                            buttons.append(types.KeyboardButton("Сгенерировать QR-code"))
                        else:
                            buttons.append(types.KeyboardButton("Посещаемость"))
                        markup.add(*buttons)
                        cursor.execute("UPDATE users SET telegram_id = %s WHERE id = %s", (chat_id, id))
                        conn.commit()
                        bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)
                    else:
                        bot.send_message(chat_id, "Вам принадлежит другой аккаунт, попробуйте ещё раз!")
                else:
                    users[chat_id]["auth_attempts"] += 1
                    if users[chat_id]["auth_attempts"] >= 3:
                        bot.send_message(chat_id, "Превышено количество попыток. Попробуйте позднее.")
                        del users[chat_id]
                    else:
                        bot.send_message(chat_id, "Авторизация не удалась. Пожалуйста, попробуйте еще раз:")
            else:               
                users[chat_id].update({"user_id": -1, "admin": True, "auth_attempts": 0, "is_authenticated": True, "role":"admin"})
                bot.send_message(chat_id, "Приветствую, повелитель!")
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                buttons = [types.KeyboardButton(text) for text in ["Группы", "Пользователи","Предметы","Расписание","Посещение"]]
                markup.add(*buttons)
                bot.send_message(chat_id, "Выберите действие:", reply_markup=markup)
                            
            
    else:
        if message.text == "Сгенерировать QR-code" and users[message.chat.id]["role"]=="Студент":
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            generate_qr_code(message)
        elif message.text == "Посмотреть расписание" and (users[message.chat.id]["role"]=="Студент" or users[message.chat.id]["role"]=="Преподаватель"):
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            show_schedule_teacher(message)
        elif message.text == "Список группы" and (users[message.chat.id]["role"]=="Студент" or users[message.chat.id]["role"]=="Преподаватель"):
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            show_group_list_for_teacher(message)
        elif message.text == "Посещаемость" and users[message.chat.id]["role"]=="Преподаватель":
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            keyboard = [
                [
                    types.InlineKeyboardButton("Поставить посещение", callback_data='add_attendance_t'),
                    types.InlineKeyboardButton("Убрать посещаемость", callback_data='delete_attendance_t'),
                    types.InlineKeyboardButton("Просмотреть посещение", callback_data='view_attendance_t')
                ]
            ]
            reply_markup = types.InlineKeyboardMarkup(keyboard)
            sent_message = bot.send_message(message.chat.id, 'Выберите действие:', reply_markup=reply_markup)
            users[message.chat.id]["button_message"] = sent_message.message_id
        elif message.text == "Группы" and users[message.chat.id]["admin"]==True:
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            keyboard = [
                [
                    types.InlineKeyboardButton("Добавить группу", callback_data='add_group'),
                    types.InlineKeyboardButton("Удалить группу", callback_data='delete_group'),
                    types.InlineKeyboardButton("Просмотреть список групп", callback_data='view_group')
                ]
            ]
            reply_markup = types.InlineKeyboardMarkup(keyboard)
            sent_message = bot.send_message(message.chat.id, 'Выберите действие:', reply_markup=reply_markup)
            users[message.chat.id]["button_message"] = sent_message.message_id 
        elif message.text == "Пользователи" and users[message.chat.id]["admin"]==True:
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            keyboard = [
                [
                    types.InlineKeyboardButton("Добавить пользователя", callback_data='add_user'),
                    types.InlineKeyboardButton("Удалить пользователя", callback_data='delete_user'),
                    types.InlineKeyboardButton("Просмотреть список пользователей", callback_data='view_user')
                ]
            ]
            reply_markup = types.InlineKeyboardMarkup(keyboard)
            sent_message = bot.send_message(message.chat.id, 'Выберите действие:', reply_markup=reply_markup)
            users[message.chat.id]["button_message"] = sent_message.message_id
        elif message.text == "Предметы" and users[message.chat.id]["admin"]==True:
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            keyboard = [
                [
                    types.InlineKeyboardButton("Добавить предмет", callback_data='add_subject'),
                    types.InlineKeyboardButton("Удалить предмет", callback_data='delete_subject'),
                    types.InlineKeyboardButton("Просмотреть список предметов", callback_data='view_subject')
                ]
            ]
            reply_markup = types.InlineKeyboardMarkup(keyboard)
            sent_message = bot.send_message(message.chat.id, 'Выберите действие:', reply_markup=reply_markup)
            users[message.chat.id]["button_message"] = sent_message.message_id
        elif message.text == "Расписание" and users[message.chat.id]["admin"]==True:
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            keyboard = [
                [
                    types.InlineKeyboardButton("Добавить пару", callback_data='add_schedule'),
                    types.InlineKeyboardButton("Удалить пару", callback_data='delete_schedule'),
                    types.InlineKeyboardButton("Просмотреть расписание", callback_data='view_schedule')
                ]
            ]
            reply_markup = types.InlineKeyboardMarkup(keyboard)
            sent_message = bot.send_message(message.chat.id, 'Выберите действие:', reply_markup=reply_markup)
            users[message.chat.id]["button_message"] = sent_message.message_id
        elif message.text == "Посещение" and users[message.chat.id]["admin"]==True:
            try:
                bot.delete_message(message.chat.id, users[message.chat.id]["button_message"])
            except Exception as e:
                print(f"Ошибка при удалении сообщения: {e}")
            keyboard = [
                [
                    types.InlineKeyboardButton("Поставить посещение", callback_data='add_attendance'),
                    types.InlineKeyboardButton("Убрать посещаемость", callback_data='delete_attendance'),
                    types.InlineKeyboardButton("Просмотреть посещение", callback_data='view_attendance')
                ]
            ]
            reply_markup = types.InlineKeyboardMarkup(keyboard)
            sent_message = bot.send_message(message.chat.id, 'Выберите действие:', reply_markup=reply_markup)
            users[message.chat.id]["button_message"] = sent_message.message_id
        else:
            bot.reply_to(message, "Извините, я не понимаю ваш запрос. Воспользуйтесь встроенными командами")

        
            
                

def generate_qr_code(message):
    ensure_database_connection()
    chat_id = message.chat.id
    user_id = users[chat_id]["user_id"]
    locale.setlocale(locale.LC_ALL, "ru")
    current_time = datetime.now()
    # Форматирование текущего времени и дня недели для SQL-запроса
    current_day = current_time.strftime("%Y-%m-%d")
    current_time_str = current_time.strftime("%H:%M:%S")
    # SQL-запрос для получения предмета, который идет в данный момент времени
    cursor.execute("""
        SELECT subject_id 
        FROM newschedule 
        WHERE group_id = (SELECT group_id FROM users WHERE id = %s) 
        AND date = %s 
        AND %s::time BETWEEN start_time - INTERVAL '10 minutes' AND start_time + INTERVAL '10 minutes'
        ORDER BY start_time ASC 
        LIMIT 1"""
    ,(user_id, current_day, current_time_str))
    result = cursor.fetchone()
    if result:
        subject = result[0]
        # Формирование данных для QR-кода
        qr_data = f"student_id:{user_id}, subject_id:{subject}, timestamp:{current_time.timestamp()}"
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white")
        qr_image_bytes = BytesIO()
        qr_image.save(qr_image_bytes)  # Измените формат на тот, который вам нужен
        qr_image_bytes.seek(0)  # Возвращаем указатель в начало байтового потока
        bot.send_photo(chat_id, qr_image_bytes)
        bot.send_message(chat_id, "Ваш QR-code готов!")
        timestamp_str = current_time.astimezone(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S')
        time.sleep(8)
        # Проверка наличия записи в таблице qr
        cursor.execute("""
            SELECT COUNT(*) FROM qr 
            WHERE student_id = %s AND subject_id = %s AND timestamp = %s""",
            (user_id, subject,timestamp_str)
        )
        count = cursor.fetchone()[0]
        if count > 0:
            cursor.execute("""
                DELETE FROM qr 
                WHERE student_id = %s AND subject_id = %s AND timestamp  = %s""",
                (user_id, subject, timestamp_str)
            )
            conn.commit()
            cursor.execute("SELECT group_id FROM users WHERE id = %s", (user_id,))
            group_id = cursor.fetchone()[0]
            cursor.execute("SELECT start_time, teacher_id FROM newschedule WHERE date=%s AND group_id = %s AND subject_id = %s LIMIT 1", (current_day, group_id,subject))
            data = cursor.fetchall()
            starttime = data[0][0].strftime("%H:%M:%S")
            teacher_id = data[0][1]
            # Вставка записи в таблицу с посещениями
            cursor.execute("""
                SELECT * FROM attendance WHERE student_id=%s AND teacher_id=%s AND subject_id=%s AND date=CURRENT_DATE AND time_start=%s
                """,
            (user_id, teacher_id, subject, starttime))
            res = cursor.fetchall()
            if (len(res)>0):
                bot.send_message(chat_id,"Вы уже проставили посещение")
            else:
                cursor.execute("""
                    INSERT INTO attendance (student_id, teacher_id, subject_id, date, time_start)
                    VALUES (%s, %s, %s, CURRENT_DATE, %s)""",
                (user_id, teacher_id, subject, starttime))
                conn.commit()
                bot.send_message(chat_id, "Посещение проставлено.")
        else:
            bot.send_message(chat_id, "QR-code устарел. Попробуйте сгенерировать новый.")
    else:
        bot.send_message(chat_id, "Информация о текущем занятии не найдена.")

def show_schedule_teacher(message):
    ensure_database_connection()
    chat_id = message.chat.id
    user_id = users[chat_id]["user_id"]
    
    # Получаем роль пользователя
    cursor.execute("SELECT role, group_id FROM users WHERE id = %s", (user_id,))
    role, group_id = cursor.fetchone()
    today = datetime.today()
    # Вычисляем разницу в днях между сегодняшним днем и понедельником
    days_since_monday = today.weekday()
    monday_of_current_week = today - timedelta(days=days_since_monday)
    sunday_of_current_week = monday_of_current_week+timedelta(days=6)
    if role.lower() == 'преподаватель':
        # Для преподавателя получаем расписание по teacher_id
        cursor.execute("""
            SELECT date, start_time, end_time, subject_id, group_id
            FROM newschedule 
            WHERE teacher_id = %s AND date >= %s AND date<=%s
            ORDER BY 
                date ASC, 
                start_time ASC
        """, (user_id,monday_of_current_week,sunday_of_current_week))
        schedule = cursor.fetchall()
        schedule_message = ""
        current_day = None
        for day, starttime, endtime, subject_id, group_id in schedule:
            cursor.execute("""
                SELECT group_number FROM groups
                WHERE id = %s 
            """, (group_id,))
            group = cursor.fetchone()
            cursor.execute("""
                SELECT name FROM subjects
                WHERE id = %s 
            """, (subject_id,))
            subject = cursor.fetchone()
            locale.setlocale(locale.LC_ALL,'ru_RU.UTF-8')
            if day != current_day:
                # Начинаем новый день
                schedule_message += f"{day.strftime("%A").capitalize()}:\n"
                current_day = day
            schedule_message += f"  {starttime.strftime('%H:%M')}-{endtime.strftime('%H:%M')} {subject[0]} {group[0]}\n"
    else:
        # Для студентов получаем расписание по group_id
        cursor.execute("""
            SELECT date, start_time, end_time, subject_id, teacher_id 
            FROM newschedule 
            WHERE group_id = %s AND date >= %s AND date<=%s
            ORDER BY 
                date ASC, 
                start_time ASC
        """, (group_id,monday_of_current_week,sunday_of_current_week))
        schedule = cursor.fetchall()   
        schedule_message = ""
        current_day = None
        for day, starttime, endtime, subject_id, teacher_id in schedule:
            cursor.execute("""
            SELECT full_name FROM users 
            WHERE id = %s 
        """, (teacher_id,))
            teacher = cursor.fetchall()
            teacher_name = teacher[0][0].split()
            cursor.execute("""
                SELECT name FROM subjects
                WHERE id = %s 
            """, (subject_id,))
            subject = cursor.fetchall()
            locale.setlocale(locale.LC_ALL,'ru_RU.UTF-8')
            if day != current_day:
                # Начинаем новый день
                schedule_message += f"{day.strftime("%A").capitalize()}:\n"
                current_day = day
            schedule_message += f"  {starttime.strftime('%H:%M')}-{endtime.strftime('%H:%M')} {subject[0][0]} {teacher_name[0]} {teacher_name[1][0]}. {teacher_name[2][0]}.\n"

    bot.send_message(chat_id, f"Ваше расписание на неделю:\n```\n{schedule_message}```", parse_mode='Markdown')


def show_group_list_for_teacher(message):
    ensure_database_connection()
    chat_id = message.chat.id
    users[chat_id]["current_action"]="show_group_list_for_teacher"
    user_id = users[chat_id]["user_id"]
    cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
    role = cursor.fetchone()[0]
    if role.lower() == 'преподаватель':
        users[chat_id]["current_group_page"]= 0
        send_groups_page_for_teach(chat_id)
    else:
        # Для студентов выводим их группу
        display_group_members(chat_id, user_id)
        
def send_groups_page_for_teach(chat_id):
    start_index = users[chat_id]["current_group_page"] * 10
    # Получаем все группы, у которых пользователь является преподавателем
    cursor.execute("SELECT DISTINCT group_id FROM schedule WHERE teacher_id = %s ORDER BY group_id ASC", (users[chat_id]["user_id"],))
    groups = cursor.fetchall()
    end_index = min((users[chat_id]["current_group_page"] + 1) * 10, len(groups))
    # Создаем inline-разметку для кнопок
    markup = types.InlineKeyboardMarkup()
    # Добавляем inline-кнопки для каждой группы
    names=[]
    for group in groups[start_index:end_index]:
        cursor.execute("SELECT DISTINCT group_number, id FROM groups WHERE id = %s ORDER BY group_number ASC", (group[0],))
        names=cursor.fetchall()
    for name in names:
        markup.add(types.InlineKeyboardButton(f"Группа {name[0]}", callback_data=f"group_{name[1]}"))
    control_buttons = []
    if users[chat_id]["current_group_page"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))
    if control_buttons:
        markup.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=markup)
    users[chat_id]["button_message"] = sent_message.message_id
    users[chat_id]["prev_message_id"] = sent_message.message_id
    
@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users.get(call.message.chat.id) and users[call.message.chat.id]['role'] == "Преподаватель" and users[call.message.chat.id]["current_action"]=="show_group_list_for_teacher")
def handle_group_list_for_teacher(call):
    # Извлекаем group_id из callback_data
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    users[chat_id]["prev_message_id"]=None
    group_id = call.data.split('_')[1]

    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (group_id,))
    group_number = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_number}")

    # Получаем список членов группы
    cursor.execute("SELECT full_name FROM users WHERE group_id = %s ORDER BY full_name ASC", (group_id,))
    group_members = cursor.fetchall()

    # Составляем сообщение со списком группы
    group_list_message = ""
    for index, member in enumerate(group_members, start=1):
        group_list_message += f"{index}. {member[0]}\n"
    users[call.message.chat.id]["current_action"]=None
    bot.send_message(call.message.chat.id, f"Список группы {group_number}:\n```\n{group_list_message}```", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["role"]=="Преподаватель" and users[call.message.chat.id]["current_action"]=="show_group_list_for_teacher")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_group_page"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_group_page"] += 1

    chat_id = call.message.chat.id
    send_groups_page_for_teach(chat_id)

def display_group_members(chat_id, user_id):
    # Получаем group_id пользователя
    cursor.execute("SELECT group_id FROM users WHERE id = %s", (user_id,))
    group_id = cursor.fetchone()[0]

    # Получаем список членов группы
    cursor.execute("SELECT full_name FROM users WHERE group_id = %s ORDER BY full_name ASC", (group_id,))
    group_members = cursor.fetchall()
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (group_id,))
    group_number = cursor.fetchone()[0]
    # Составляем сообщение со списком группы
    group_list_message = ""
    for index, member in enumerate(group_members, start=1):
        group_list_message += f"{index}. {member[0]}\n"

    bot.send_message(chat_id, f"Список группы {group_number}:\n```\n{group_list_message}```", parse_mode='Markdown')



@bot.callback_query_handler(func=lambda call: call.data == 'add_attendance_t')
def view_attendence_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    users[chat_id]["para"]={}
    users[chat_id]["current_action"]="add_attendance_t"
    bot.send_message(chat_id,"Введите дату в виде YYYY-MM-DD")

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_attendance_t')
def add_attendance(message):
    chat_id = message.chat.id
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    date = message.text
    if date_pattern.match(date):
        cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (chat_id,))
        teacher_id = cursor.fetchone()[0]
        users[chat_id]["para"]["teacher"]=teacher_id
        cursor.execute("SELECT * FROM newschedule WHERE date = %s", (date,))
        if len(cursor.fetchall()) > 0:
            users[chat_id]["para"]["date"]=date
            users[chat_id]["prev_message_id"] = None
            users[chat_id]["current_page_groups"] = 0
            cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g
        INNER JOIN newschedule s ON g.id = s.group_id
        WHERE s.date = %s
        AND s.teacher_id = %s""", (date,teacher_id))
            groups_list = cursor.fetchall()
            if not groups_list:
                bot.send_message(chat_id, "Список групп пуст.")
                users[chat_id]["current_action"]=None
                return
            send_groups_page_atten_teach(chat_id, groups_list)
        else:
            bot.send_message(chat_id, "Пар не было в эту дату.")
            users[chat_id]["current_action"]=None
    else:
        bot.send_message(chat_id, "Неверный формат даты, попробуйде ещё раз.")
        
def send_groups_page_atten_teach(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["button_message"] = sent_message.message_id
    users[chat_id]["prev_message_id"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="add_attendance_t")
def select_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    users[chat_id]["para"]["group"]=selected_group
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN newschedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s AND sc.teacher_id = %s
""", (users[chat_id]["para"]["date"], users[chat_id]["para"]["group"],users[chat_id]["para"]["teacher"]))
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="add_attendance_t")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g
        INNER JOIN newschedule s ON g.id = s.group_id
        WHERE s.date = %s
        AND s.teacher_id = %s""", (users[chat_id]["para"]["date"],users[chat_id]["para"]["teacher"]))
    groups_list = cursor.fetchall()
    send_groups_page_atten_teach(chat_id, groups_list)

def send_subjects_page(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="add_attendance_t")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    users[chat_id]["para"]["subject"] = selected_subject
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_students"] = 0
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id NOT IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN newschedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (users[chat_id]["para"]["group"], users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"]))

    students_list = cursor.fetchall()  # Получите список групп из базы данных

    if not students_list:
        bot.send_message(chat_id, "Список студентов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_students_attendance_page(chat_id, students_list)

def send_students_attendance_page(chat_id, students_list):
    start_index = users[chat_id]["current_page_students"] * 10
    end_index = min((users[chat_id]["current_page_students"] + 1) * 10, len(students_list))

    keyboard = types.InlineKeyboardMarkup()
    for student in students_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{student[0]}', callback_data=f'student_{student[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_students"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_students'))
    if end_index < len(students_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_students'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите студента:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="add_attendance_t")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN newschedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s AND sc.teacher_id = %s
""", (users[chat_id]["para"]["date"], users[chat_id]["para"]["group"],users[chat_id]["para"]["teacher"]))
    subjects_list = cursor.fetchall()
    send_subjects_page(chat_id, subjects_list)
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_students', 'next_page_students'] and users[call.message.chat.id]["current_action"]=="add_attendance_t")
def change_students_page(call):
    if call.data == 'prev_page_students':
        users[call.message.chat.id]["current_page_students"] -= 1
    elif call.data == 'next_page_students':
        users[call.message.chat.id]["current_page_students"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id NOT IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN newschedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (users[chat_id]["para"]["group"], users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"]))

    students_list = cursor.fetchall() 
    send_students_attendance_page(chat_id, students_list)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_') and users[call.message.chat.id]["current_action"]=="add_attendance_t")
def select_student(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    select_student = call.data.split('_')[1]

    cursor.execute("SELECT full_name FROM users WHERE id = %s", (select_student,))
    student_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран студент - {student_name}")
    cursor.execute("""
    SELECT start_time
    FROM newschedule
    WHERE subject_id = %s AND date = %s AND group_id = %s
""", (users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"], users[chat_id]["para"]["group"]))
    result = cursor.fetchone()
    time_start = result[0]
    # Добавление посещения студента на пару
    cursor.execute("""
        INSERT INTO attendance (student_id, teacher_id, subject_id, date, time_start)
        VALUES (%s, %s, %s, %s, %s)
    """, (select_student, users[chat_id]["para"]["teacher"], users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"], time_start))
    conn.commit()
    users[chat_id]["current_action"]=None
    bot.send_message(chat_id, "Посещение проставлено.")


@bot.callback_query_handler(func=lambda call: call.data == 'delete_attendance_t')
def del_attendence_callback(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    users[chat_id]["para"] = {}
    bot.send_message(chat_id,"Введите дату в формате YYYY-MM-DD")
    users[chat_id]["current_action"]="del_attendance_t"

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'del_attendance_t')
def del_attendance(message):
    ensure_database_connection()
    chat_id = message.chat.id
    date = message.text
    users[chat_id]["para"] = {}
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    if date_pattern.match(date):
        cursor.execute("SELECT * FROM newschedule WHERE date = %s", (date,))
        if len(cursor.fetchall()) > 0:
            users[chat_id]["para"]["date"]=date
            users[chat_id]["prev_message_id"] = None
            users[chat_id]["current_page_groups"] = 0
            cursor.execute("""SELECT id FROM users WHERE telegram_id = %s""", (chat_id,))
            users[chat_id]["para"]["teacher"] = cursor.fetchone()[0]
            cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g
        INNER JOIN newschedule s ON g.id = s.group_id
        WHERE s.date = %s
        AND s.teacher_id = %s""", (date,users[chat_id]["para"]["teacher"]))
            groups_list = cursor.fetchall()
            if not groups_list:
                bot.send_message(chat_id, "Список групп пуст.")
                users[chat_id]["current_action"]=None
                return
            send_groups_page(chat_id, groups_list)
        else:
            bot.send_message(chat_id, "Пар не было в эту дату.")
            users[chat_id]["current_action"]=None
    else:
            bot.send_message(chat_id, "Неверный формат даты, попробуйте ещё раз")
        
def send_groups_page(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="del_attendance_t")
def select_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    users[chat_id]["para"]["group"]=selected_group
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN newschedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s AND sc.teacher_id=%s
""", (users[chat_id]["para"]["date"], users[chat_id]["para"]["group"],users[chat_id]["para"]["teacher"]))
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="del_attendance_t")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g
        INNER JOIN newschedule s ON g.id = s.group_id
        WHERE s.date = %s
        AND s.teacher_id = %s""", (users[chat_id]["para"]["date"],users[chat_id]["para"]["teacher"]))
    groups_list = cursor.fetchall()
    send_groups_page(chat_id, groups_list)

def send_subjects_page(chat_id, subjects_list):

    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="del_attendance_t")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    users[chat_id]["para"]["subject"] = selected_subject
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_students"] = 0
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN newschedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (users[chat_id]["para"]["group"], users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"]))

    students_list = cursor.fetchall()  # Получите список групп из базы данных

    if not students_list:
        bot.send_message(chat_id, "Список студентов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_students_page(chat_id, students_list)

def send_students_page(chat_id, students_list):
    start_index = users[chat_id]["current_page_students"] * 10
    end_index = min((users[chat_id]["current_page_students"] + 1) * 10, len(students_list))

    keyboard = types.InlineKeyboardMarkup()
    for student in students_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{student[0]}', callback_data=f'student_{student[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_students"]> 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_students'))
    if end_index < len(students_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_students'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите студента:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"]= sent_message.message_id
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="del_attendance")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN schedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s AND sc.teacher_id = %s
""", (users[chat_id]["para"]["date"], users[chat_id]["para"]["group"],users[chat_id]["para"]["teacher"]))
    subjects_list = cursor.fetchall()
    send_subjects_page(chat_id, subjects_list)
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_students', 'next_page_students'] and users[call.message.chat.id]["current_action"]=="del_attendance_t")
def change_students_page(call):
    if call.data == 'prev_page_students':
        users[call.message.chat.id]["current_page_students"] -= 1
    elif call.data == 'next_page_students':
        users[call.message.chat.id]["current_page_students"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN schedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (users[chat_id]["para"]["group"], users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"]))

    students_list = cursor.fetchall() 
    send_students_page(chat_id, students_list)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_') and users[call.message.chat.id]["current_action"]=="del_attendance_t")
def select_student(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    select_student = call.data.split('_')[1]

    cursor.execute("SELECT full_name FROM users WHERE id = %s", (select_student,))
    student_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран студент - {student_name}")
    cursor.execute("""
    SELECT start_time
    FROM newschedule
    WHERE subject_id = %s AND date = %s AND group_id = %s
""", (users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"], users[chat_id]["para"]["group"]))
    result = cursor.fetchone()
    time_start = result[0]
    cursor.execute("""
        DELETE FROM attendance WHERE student_id=%s AND teacher_id=%s AND subject_id=%s AND date=%s AND time_start=%s
    """, (select_student, users[chat_id]["para"]["teacher"], users[chat_id]["para"]["subject"], users[chat_id]["para"]["date"], time_start))
    conn.commit()
    bot.send_message(chat_id, "Посещение удалено")
    users[chat_id]["current_action"]=None
    users[chat_id]["prev_message_id"]=None

@bot.callback_query_handler(func=lambda call: call.data == 'view_attendance_t')
def view_attendence_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    users[chat_id]["para"] = {}
    users[chat_id]["current_action"]="view_attendance_t"
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_groups"] = 0
    cursor.execute("""SELECT DISTINCT g.group_number, g.id FROM groups g INNER JOIN newschedule ON group_id = g.id WHERE teacher_id=(SELECT id FROM users WHERE telegram_id=%s)  """,(chat_id,))
    groups_list = cursor.fetchall()
    if not groups_list:
        bot.send_message(chat_id, "Список групп пуст.")
        users[chat_id]["current_action"]=None
        return
    send_abgroups_page(chat_id, groups_list)
        
def send_abgroups_page(chat_id, groups_list):

    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="view_attendance_t")
def select_group(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    users[chat_id]["para"]["group"]=selected_group
    cursor.execute("""SELECT DISTINCT sb.name, sb.id
        FROM subjects sb
        INNER JOIN newschedule sc ON sb.id = sc.subject_id
        WHERE sc.group_id = %s AND sc.teacher_id = (SELECT id FROM users WHERE telegram_id = %s)
    """, (users[chat_id]["para"]["group"],chat_id))
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="view_attendance_t")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT g.group_number, g.id FROM groups g INNER JOIN newschedule ON group_id = g.id WHERE teacher_id=(SELECT id FROM users WHERE telegram_id=%s)  """,(chat_id,))
    groups_list = cursor.fetchall()
    send_abgroups_page(chat_id, groups_list)

def send_subjects_page(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="view_attendance_t")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1
    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT sb.name, sb.id
        FROM subjects sb
        INNER JOIN newschedule sc ON sb.id = sc.subject_id
        WHERE sc.group_id = %s AND sc.teacher_id = (SELECT id FROM users WHERE telegram_id = %s)
    """, (users[chat_id]["para"]["group"]),chat_id)
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="view_attendance_t")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]
    students = {}
    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    users[chat_id]["para"]["subject"] = selected_subject
    cursor.execute("SELECT full_name, id FROM users WHERE group_id = %s ORDER BY full_name ASC", (users[chat_id]["para"]["group"],))
    student_list = cursor.fetchall()
    students.clear()
    for student in student_list:
        students[student[0]]=student[1]
    cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (chat_id,))
    teacher_id = cursor.fetchone()[0]
    cursor.execute("SELECT date FROM newschedule WHERE group_id = %s and subject_id = %s and teacher_id = %s ORDER BY date", (users[chat_id]["para"]["group"], users[chat_id]["para"]["subject"],teacher_id))
    date_list = cursor.fetchall()
    dates = []
    dates.clear()
    for date in date_list:
        dates.append(date[0])
    users[chat_id]["current_page_dates"] = 0
    users[chat_id]["current_page_students"] = 0
    show_attendance_teacher(chat_id, students, dates)
    

def show_attendance_teacher(chat_id, students, dates):
    start_indexdates = users[chat_id]["current_page_dates"] * 5
    end_indexdates = min((users[chat_id]["current_page_dates"] + 1) * 5, len(dates))
    start_indexstudents = users[chat_id]["current_page_students"] * 20
    end_indexstudents = min((users[chat_id]["current_page_students"] + 1) * 20, len(students))
    keyboard = types.InlineKeyboardMarkup()
    table = f"{"ФИО":^35}"
    for date in dates[start_indexdates:end_indexdates]:
        table+=f"|{date.strftime('%Y-%m-%d'):^10}"
    table += f"\n"
    newlist = list(students.keys())
    for student in newlist[start_indexstudents:end_indexstudents]:
        table += f"{student:^35}"
        for date in dates[start_indexdates:end_indexdates]:
            cursor.execute("SELECT * FROM attendance WHERE subject_id = %s AND student_id = %s AND date = %s", (users[chat_id]["para"]["subject"], students[student], date))
            res = cursor.fetchall()
            if len(res) > 0:
                table+=f"|{"✅":^9}"
            else:
                table+=f"|{"❌":^9}"
        table += f"\n"
    control_buttons = []
    if users[chat_id]["current_page_dates"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_dates'))
    if end_indexdates < len(dates):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_dates'))
    if users[chat_id]["current_page_students"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='🔼', callback_data='up_page_students'))
    if end_indexstudents < len(students):
        control_buttons.append(types.InlineKeyboardButton(text='🔽', callback_data='down_page_students'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, f"Журнал посещений:\n```\n{table}```",parse_mode="Markdown", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_dates', 'next_page_dates'] and users[call.message.chat.id]["current_action"]=="view_attendance_t")
def change_subjects_page(call):
    if call.data == 'prev_page_dates':
        users[call.message.chat.id]["current_page_dates"] -= 1
    elif call.data == 'next_page_dates':
        users[call.message.chat.id]["current_page_dates"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT full_name, id FROM users WHERE group_id = %s ORDER BY full_name ASC", (users[chat_id]["para"]["group"],))
    student_list = cursor.fetchall()
    students={}
    for student in student_list:
        students[student[0]]=student[1]
    cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (chat_id,))
    teacher_id = cursor.fetchone()[0]
    cursor.execute("SELECT date FROM newschedule WHERE group_id = %s and subject_id = %s and teacher_id = %s ORDER BY date", (users[chat_id]["para"]["group"], users[chat_id]["para"]["subject"],teacher_id))
    date_list = cursor.fetchall()
    dates=[]
    for date in date_list:
        dates.append(date[0])
    show_attendance_teacher(chat_id, students, dates)

@bot.callback_query_handler(func=lambda call: call.data in ['up_page_students', 'down_page_students'] and users[call.message.chat.id]["current_action"]=="view_attendance_t")
def change_students_page(call):
    if call.data == 'up_page_students':
        users[call.message.chat.id]["current_page_students"] -= 1
    elif call.data == 'down_page_students':
        users[call.message.chat.id]["current_page_students"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT full_name, id FROM users WHERE group_id = %s ORDER BY full_name ASC", (users[chat_id]["para"]["group"],))
    student_list = cursor.fetchall()
    for student in student_list:
        students[student[0]]=student[1]
    cursor.execute("SELECT id FROM users WHERE telegram_id = %s", (chat_id,))
    teacher_id = cursor.fetchone()[0]
    cursor.execute("SELECT date FROM newschedule WHERE group_id = %s and subject_id = %s and teacher_id = %s ORDER BY date", (users[chat_id]["para"]["group"], users[chat_id]["para"]["subject"],teacher_id))
    date_list = cursor.fetchall()
    for date in date_list:
        dates.append(date[0])
    show_attendance_teacher(chat_id, students, dates)

@bot.callback_query_handler(func=lambda call: call.data == 'add_user')
def add_user_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(types.InlineKeyboardButton(text='Преподаватель', callback_data='teacher'),
                 types.InlineKeyboardButton(text='Студент', callback_data='student'))
    msg = bot.send_message(chat_id, "Выберите роль пользователя:", reply_markup=keyboard)
    users[chat_id]['current_action'] = 'add_user'
    users[chat_id]['current_step'] = 'role_selection'
    users[chat_id]['prevent_message_id'] = msg.message_id
    users[chat_id]['button_message'] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'student' and users.get(call.message.chat.id) and users[call.message.chat.id]['current_action'] == 'add_user' and users[call.message.chat.id]['current_step'] == 'role_selection')
def select_student_role(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]['prevent_message_id'])
    bot.send_message(chat_id, "Роль пользователя - студент")
    users[chat_id]["role"]="Студент"
    cursor.execute("SELECT group_number, id FROM groups ORDER BY group_number ASC")
    groups_list = cursor.fetchall() # Получите список групп из базы данных

    if not groups_list:
        bot.send_message(chat_id, "Добавить студента не получится, так как нет групп.")
        users[chat_id]['current_action'] = None
        users[chat_id]['current_step'] = None
        users[chat_id]['prevent_message_id'] = None
    else:
        users[chat_id]['current_step'] = 'group_selection'
        users[chat_id]['current_page_groups'] = 0
        users[chat_id]['prevent_message_id'] = call.message.chat.id
        users[chat_id]['button_message'] = call.message.chat.id
        send_groups_users(chat_id, groups_list)
 
def send_groups_users(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))
    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))
    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))
    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prevent_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prevent_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prevent_message_id"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="add_user" and users[call.message.chat.id]["current_step"]=="group_selection")
def change_groups_page_user(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT group_number, id FROM groups ORDER BY group_number ASC")
    groups_list = cursor.fetchall()
    send_groups_users(chat_id, groups_list)       

        
@bot.callback_query_handler(func=lambda call: call.data == 'teacher' and users.get(call.message.chat.id) and users[call.message.chat.id]['current_action'] == 'add_user' and users[call.message.chat.id]['current_step'] == 'role_selection')
def select_teacher_role(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]['prevent_message_id'])
    bot.send_message(chat_id, "Роль пользователя - преподаватель")
    users[chat_id]["role"]="Преподаватель"
    bot.send_message(chat_id, "Введите ФИО пользователя:")
    users[chat_id]['current_step'] = 'name'
    
@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users.get(call.message.chat.id) and users[call.message.chat.id]['current_action'] == 'add_user' and users[call.message.chat.id]['current_step'] == 'group_selection')
def select_group_user(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]['prevent_message_id'])
    selected_group = call.data.split('_')[1]
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Группа студента - {group_name}")
    users[chat_id]["group"]=selected_group
    bot.send_message(chat_id, "Введите ФИО пользователя:")
    users[chat_id]['current_step'] = 'name'

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_user' and users[message.chat.id]['current_step'] == 'name')
def add_user_name(message):
    chat_id = message.chat.id
    name = message.text
    bot.send_message(chat_id, f"ФИО пользователя - {name}")
    # Здесь можно добавить логику для сохранения ФИО в базе данных или в вашей программе
    users[chat_id]["name"]=name
    bot.send_message(chat_id, "Введите логин пользователя:")
    users[chat_id]['current_step'] = 'login'

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_user' and users[message.chat.id]['current_step'] == 'login')
def add_user_login(message):
    chat_id = message.chat.id
    login = message.text
    bot.send_message(chat_id, f"Логин пользователя - {login}")
    users[chat_id]["login"]=login
    # Здесь можно добавить логику для сохранения логина в базе данных или в вашей программе

    bot.send_message(chat_id, "Введите пароль пользователя:")
    users[chat_id]['current_step'] = 'password'

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_user' and users[message.chat.id]['current_step'] == 'password')
def add_user_password(message):
    chat_id = message.chat.id
    password = message.text
    bot.send_message(chat_id, f"Пароль пользователя - {password}")
    users[chat_id]["password"]=password
    if (users[chat_id]["role"]=="Студент"):
        cursor.execute("""
            INSERT INTO users (full_name, login, password, role, group_id)
            VALUES ( %s, %s, %s, %s, %s)""", 
            (users[chat_id]['name'], users[chat_id]['login'], users[chat_id]['password'], users[chat_id]['role'], users[chat_id]['group']))
    else:
        cursor.execute("""
            INSERT INTO users (full_name, login, password, role)
            VALUES ( %s, %s, %s, %s)""", 
            (users[chat_id]['name'], users[chat_id]['login'], users[chat_id]['password'], users[chat_id]['role']))
    conn.commit()
    bot.send_message(chat_id, "Пользователь успешно добавлен.")
    users[chat_id]['current_action'] = None
    users[chat_id]['current_step'] = None

@bot.callback_query_handler(func=lambda call: call.data == 'delete_user')
def del_user_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    bot.send_message(chat_id, "Введите логин пользователя, которого хотите удалить:")
    users[chat_id]['current_action'] = 'delete_user'
    users[chat_id]['current_step'] = 'login'


@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'delete_user' and users[message.chat.id]['current_step'] == 'login')
def del_user_login(message):
    chat_id = message.chat.id
    login = message.text
    users[chat_id]["login"]=login
    bot.send_message(chat_id, "Введите пароль пользователя:")
    users[chat_id]['current_step'] = 'password'

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'delete_user' and users[message.chat.id]['current_step'] == 'password')
def del_user_password(message):
    chat_id = message.chat.id
    password = message.text
    users[chat_id]["password"]=password
    try:
        cursor.execute("""
        DELETE FROM users WHERE login = %s AND password = %s""", 
        (users[chat_id]['login'], users[chat_id]['password']))
        conn.commit()
        if (cursor.rowcount != 0):
            bot.send_message(chat_id, "Пользователь успешно удален.")
        else:
            bot.send_message(chat_id, "Пользователь не был найден.")
        users[chat_id]['current_action'] = None
        users[chat_id]['current_step'] = None
    except:
        cursor.execute("ROLLBACK")
        bot.send_message(chat_id, "Преподаватель есть расписании, удалите сначала его пары")
        users[chat_id]['current_action'] = None
        users[chat_id]['current_step'] = None

users_list = []

@bot.callback_query_handler(func=lambda call: call.data == 'view_user')
def view_users_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    users[chat_id]["current_page"] = 0
    bot.delete_message(chat_id,call.message.id)
    cursor.execute("SELECT full_name, role, login, password FROM users ORDER BY role ASC, full_name ASC")
    global users_list
    users_list = cursor.fetchall()
    send_users_page(chat_id)

def send_users_page(chat_id):
    start_index = users[chat_id]["current_page"] * 20
    end_index = min((users[chat_id]["current_page"] + 1) * 20, len(users_list))

    table = f"{"ФИО":^38}|{"Роль":^13}|{"Логин":^13}|{"Пароль":^3}\n"
    for user in users_list[start_index:end_index]:
        table += f"{user[0]:^38}|{user[1]:^13}|{user[2]:^13}|{user[3]:^3}\n"

    keyboard = types.InlineKeyboardMarkup()
    if users[chat_id]["current_page"] > 0:
        keyboard.add(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_users'))
    if end_index < len(users_list):
        keyboard.add(types.InlineKeyboardButton(text='▶️', callback_data='next_page_users'))

    # Удаление предыдущего сообщения, если оно существует
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, f"Список пользователей:\n```\n{table}```", parse_mode="Markdown", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'prev_page_users')
def prev_page_callback(call):
    if users[call.message.chat.id]["current_page"] > 0:
        users[call.message.chat.id]["current_page"] -= 1
    send_users_page(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'next_page_users')
def next_page_callback(call):
    users[call.message.chat.id]["current_page"] += 1
    send_users_page(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'delete_group')
def del_group_callback(call):
    ensure_database_connection()
    cursor = conn.cursor()
    chat_id = call.message.chat.id
    users[chat_id]["prevent_message_id"] = None
    users[chat_id]["current_page_groups"] = 0
    bot.delete_message(chat_id,call.message.id)
    cursor.execute("SELECT group_number, id FROM groups")
    groups_list = cursor.fetchall()  # Получите список групп из базы данных

    if not groups_list:
        bot.send_message(chat_id, "Список групп пуст.")
        return
    users[chat_id]['current_action'] = "del_group"
    send_groups_page_new_old(chat_id, groups_list)


def send_groups_page_new_old(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prevent_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prevent_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prevent_message_id"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="del_group")
def select_group_del_new_old(call):
    selected_group = call.data.split('_')[1]
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prevent_message_id"])
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    try:
        cursor.execute("DELETE FROM groups WHERE id = %s", (selected_group,))
        conn.commit()
        users[chat_id]['current_action'] = None
        bot.send_message(chat_id, "Группа удалена")
    except:
        cursor.execute("ROLLBACK")
        bot.send_message(chat_id, "В данной группе ещё есть студенты, для удаления данной группы нужно сначала удалить студентов этой группы")

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="del_group")
def change_groups_page_del(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT group_number, id FROM groups")
    groups_list = cursor.fetchall()
    send_groups_page_new_old(chat_id, groups_list)

@bot.callback_query_handler(func=lambda call: call.data == 'view_group')
def view_group_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    users[chat_id]["current_action"]="view_group" 
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_groups"] = 0
    bot.delete_message(chat_id,call.message.id)
    cursor.execute("SELECT group_number, id FROM groups")
    groups_list = cursor.fetchall()  # Получите список групп из базы данных

    if not groups_list:
        bot.send_message(chat_id, "Список групп пуст.")
        return
    send_view_user_groups_page(chat_id, groups_list)

def send_view_user_groups_page(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Список групп:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id


@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="view_group" )
def change_user_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT group_number, id FROM groups")
    groups_list = cursor.fetchall()
    send_view_user_groups_page(chat_id, groups_list)

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="view_group")
def select_user_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    cursor.execute("SELECT full_name FROM users WHERE group_id = %s ORDER BY full_name ASC",(selected_group,))
    users[chat_id]["users_list"] = []
    users[chat_id]["users_list"] = cursor.fetchall()
    send_users_page_group(chat_id)

def send_users_page_group(chat_id):
    start_index = users[chat_id]["current_page"] * 20
    end_index = min((users[chat_id]["current_page"] + 1) * 20, len(users[chat_id]["users_list"]))
    table = ""
    i=start_index+1
    for user in users[chat_id]["users_list"][start_index:end_index]:
        table += f"{i:>2}. {user[0]}\n"
        i+=1

    keyboard = types.InlineKeyboardMarkup()
    if users[chat_id]["current_page"] > 0:
        keyboard.add(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_users_groups'))
    if end_index < len(users[chat_id]["users_list"]):
        keyboard.add(types.InlineKeyboardButton(text='▶️', callback_data='next_page_users_groups'))

    # Удаление предыдущего сообщения, если оно существует
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, f"Список студентов:\n```\n{table}```", parse_mode="Markdown", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'prev_page_users_groups' and users[call.message.chat.id]["current_action"]=="view_group")
def prev_user_page_callback(call):
    if users[call.message.chat.id]["current_page"] > 0:
        users[call.message.chat.id]["current_page"] -= 1
    send_users_page_group(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'next_page_users_groups'and users[call.message.chat.id]["current_action"]=="view_group")
def next_user_page_callback(call):
    users[call.message.chat.id]["current_page"] += 1
    send_users_page_group(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'add_group')
def add_group_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    users[chat_id]["current_action"]="add_group"
    bot.send_message(chat_id,"Введите номер группы")

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_group')
def add_group(message):
    chat_id = message.chat.id
    group = message.text
    try:
        cursor.execute("INSERT INTO groups (group_number) VALUES (%s)", (group,))
        conn.commit()
        bot.send_message(chat_id, "Группа добавлена")
    except Exception as e:
        cursor.execute("ROLLBACK")
        bot.send_message(chat_id, f"Произошла ошибка: {e}")
    users[chat_id]["current_action"]=None

    
@bot.callback_query_handler(func=lambda call: call.data == 'delete_subject')
def del_subject_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    bot.delete_message(chat_id,call.message.id)
    cursor.execute("SELECT name, id FROM subjects")
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        return
    users[chat_id]['current_action'] = "del_subject"
    send_subjects_page(chat_id, subjects_list)

def send_subjects_page(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="del_subject")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")

    # Здесь можно добавить логику для сохранения выбранной группы в базе данных или вашей программе
    try:
        cursor.execute("DELETE FROM subjects WHERE id = %s", (selected_subject,))
        conn.commit()
        users[chat_id]['current_action'] = None
        bot.send_message(chat_id, "Предмет удален")
    except:
        cursor.execute("ROLLBACK")
        bot.send_message(chat_id, "Данный предмет есть в расписании, сначала удалите все пары по этому предмету")
        users[chat_id]['current_action'] = None

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="del_subject")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT name, id FROM subjects")
    subjects_list = cursor.fetchall()
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data == 'view_subject')
def view_subject_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    users[chat_id]["current_action"]="view_subject" 
    users[chat_id]["prev_message_id"]  = None
    users[chat_id]["current_page_subjects"] = 0
    bot.delete_message(chat_id,call.message.id)
    cursor.execute("SELECT name, id FROM subjects")
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        return
    send_view_subjects_page(chat_id, subjects_list)


def send_view_subjects_page(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Список предметов:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="view_subject")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1
    chat_id = call.message.chat.id
    cursor.execute("SELECT name, id FROM subjects")
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)
users_subj_list=[]

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="view_subject")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    para["subject"] = selected_subject
    users[chat_id]["current_page"] = 0
    cursor.execute("SELECT DISTINCT u.full_name FROM users u INNER JOIN newschedule n ON n.teacher_id = u.id WHERE n.subject_id = %s ORDER BY full_name ASC",(selected_subject,))
    global users_subj_list
    users_subj_list = cursor.fetchall()
    send_users_subj_page(chat_id)

def send_users_subj_page(chat_id):
    start_index = users[chat_id]["current_page"] * 20
    end_index = min((users[chat_id]["current_page"] + 1) * 20, len(users_subj_list))

    table = f""
    for user in users_subj_list[start_index:end_index]:
        table += f"{user[0]}\n"

    keyboard = types.InlineKeyboardMarkup()
    if users[chat_id]["current_page"] > 0:
        keyboard.add(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_users_subj'))
    if end_index < len(users_subj_list):
        keyboard.add(types.InlineKeyboardButton(text='▶️', callback_data='next_page_users_subj'))

    # Удаление предыдущего сообщения, если оно существует
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, f"Список преподавателей:\n```\n{table}```", parse_mode="Markdown", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data == 'prev_page_users_subj')
def prev_page_callback(call):
    if users[call.message.chat.id]["current_page"] > 0:
        users[call.message.chat.id]["current_page"] -= 1
    send_users_subj_page(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'next_page_users_subj')
def next_page_callback(call):
    users[call.message.chat.id]["current_page"] += 1
    send_users_subj_page(call.message.chat.id)
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="view_subject")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT name, id FROM subjects")
    subjects_list = cursor.fetchall()
    send_view_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data == 'add_subject')
def add_subject_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    users[chat_id]["current_action"]="add_subject"
    bot.send_message(chat_id,"Введите название предмета")

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_subject')
def add_subject(message):
    chat_id = message.chat.id
    subject = message.text
    cursor.execute("INSERT INTO subjects (name) VALUES (%s)",(subject,))
    conn.commit()
    bot.send_message(chat_id,"Предмет добавлен")
    users[chat_id]["current_action"]=None

@bot.callback_query_handler(func=lambda call: call.data == 'add_attendance')
def view_attendence_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)

    users[chat_id]["current_action"]="add_attendance"
    bot.send_message(chat_id,"Введите дату в виде YYYY-MM-DD")
para = {}

def is_valid_date(date):
    try:
        datetime.strptime(date, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def is_valid_time(time):
    try:
        datetime.strptime(time, '%H:%M:%S')
        return True
    except ValueError:
        return False
    
    
@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_attendance')
def add_attendance(message):
    chat_id = message.chat.id
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    date = message.text
    if date_pattern.match(date) and is_valid_date(date):
        cursor.execute("SELECT * FROM newschedule WHERE date = %s", (date,))
        if len(cursor.fetchall()) > 0:
            para["date"]=date
            users[chat_id]["prev_message_id"] = None
            users[chat_id]["current_page_groups"] = 0
            cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g
        INNER JOIN newschedule s ON g.id = s.group_id
        WHERE s.date = %s""", (date,))
            groups_list = cursor.fetchall()
            if not groups_list:
                bot.send_message(chat_id, "Список групп пуст.")
                users[chat_id]["current_action"]=None
                return
            send_groups_page_atten(chat_id, groups_list)
        else:
            bot.send_message(chat_id, "Пар не было в эту дату.")
            users[chat_id]["current_action"]=None
    else:
        bot.send_message(chat_id, "Неверный формат даты, попробуйде ещё раз.")
        
def send_groups_page_atten(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="add_attendance")
def select_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    para["group"]=selected_group
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN newschedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s
""", (para["date"], para["group"]))
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="add_attendance")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT g.group_number, g.id
    FROM groups g
    INNER JOIN newschedule s ON g.id = s.group_id
    WHERE s.date = %s""", (para["date"],))
    groups_list = cursor.fetchall()
    send_groups_page_atten(chat_id, groups_list)

def send_subjects_page(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="add_attendance")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    para["subject"] = selected_subject
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_students"] = 0
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id NOT IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN newschedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (para["group"], para["subject"], para["date"]))

    students_list = cursor.fetchall()  # Получите список групп из базы данных

    if not students_list:
        bot.send_message(chat_id, "Список студентов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_students_page(chat_id, students_list)

def send_students_page(chat_id, students_list):
    start_index = users[chat_id]["current_page_students"] * 10
    end_index = min((users[chat_id]["current_page_students"] + 1) * 10, len(students_list))

    keyboard = types.InlineKeyboardMarkup()
    for student in students_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{student[0]}', callback_data=f'student_{student[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_students"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_students'))
    if end_index < len(students_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_students'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите студента:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="add_attendance")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN schedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s
""", (para["date"], para["group"]))
    subjects_list = cursor.fetchall()
    send_subjects_page(chat_id, subjects_list)
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_students', 'next_page_students'] and users[call.message.chat.id]["current_action"]=="add_attendance")
def change_students_page(call):
    if call.data == 'prev_page_students':
        users[call.message.chat.id]["current_page_students"] -= 1
    elif call.data == 'next_page_students':
        users[call.message.chat.id]["current_page_students"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id NOT IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN schedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (para["group"], para["subject"], para["date"]))

    students_list = cursor.fetchall() 
    send_students_page(chat_id, students_list)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_') and users[call.message.chat.id]["current_action"]=="add_attendance")
def select_student(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_student = call.data.split('_')[1]

    cursor.execute("SELECT full_name FROM users WHERE id = %s", (selected_student,))
    student_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран студент - {student_name}")
    cursor.execute("""
    SELECT teacher_id, start_time
    FROM newschedule
    WHERE subject_id = %s AND date = %s AND group_id = %s
""", (para["subject"], para["date"], para["group"]))
    result = cursor.fetchone()
    teacher_id = result[0]
    time_start = result[1]
    # Добавление посещения студента на пару
    cursor.execute("""
        INSERT INTO attendance (student_id, teacher_id, subject_id, date, time_start)
        VALUES (%s, %s, %s, %s, %s)
    """, (selected_student, teacher_id, para["subject"], para["date"], time_start))
    conn.commit()
    users[chat_id]["current_action"]=None
    bot.send_message(chat_id, "Посещение проставлено.")


@bot.callback_query_handler(func=lambda call: call.data == 'delete_attendance')
def del_attendence_callback(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    bot.send_message(chat_id,"Введите дату в формате YYYY-MM-DD")
    users[chat_id]["current_action"]="del_attendance"


@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'del_attendance')
def del_attendance(message):
    ensure_database_connection()
    chat_id = message.chat.id
    date = message.text
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    if date_pattern.match(date) and is_valid_date(date):
        cursor.execute("SELECT * FROM newschedule WHERE date = %s", (date,))
        if len(cursor.fetchall()) > 0:
            para["date"]=date
            users[chat_id]["prev_message_id"] = None
            users[chat_id]["current_page_groups"] = 0
            cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g
        INNER JOIN newschedule s ON g.id = s.group_id
        WHERE s.date = %s""", (date,))
            groups_list = cursor.fetchall()
            if not groups_list:
                bot.send_message(chat_id, "Список групп пуст.")
                users[chat_id]["current_action"]=None
                return
            send_groups_page(chat_id, groups_list)
        else:
            bot.send_message(chat_id, "Пар не было в эту дату.")
            users[chat_id]["current_action"]=None
    else:
            bot.send_message(chat_id, "Неверный формат даты, попробуйте ещё раз")
        
def send_groups_page(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    
@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="del_attendance")
def select_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    para["group"]=selected_group
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN newschedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s
""", (para["date"], para["group"]))
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="del_attendance")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT g.group_number, g.id
    FROM groups g
    INNER JOIN newschedule s ON g.id = s.group_id
    WHERE s.date = %s""", (para["date"],))
    groups_list = cursor.fetchall()
    send_groups_page(chat_id, groups_list)

def send_subjects_page(chat_id, subjects_list):

    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="del_attendance")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    para["subject"] = selected_subject
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_students"] = 0
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN newschedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (para["group"], para["subject"], para["date"]))

    students_list = cursor.fetchall()  # Получите список групп из базы данных

    if not students_list:
        bot.send_message(chat_id, "Список студентов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_students_page(chat_id, students_list)

def send_students_page(chat_id, students_list):
    start_index = users[chat_id]["current_page_students"] * 10
    end_index = min((users[chat_id]["current_page_students"] + 1) * 10, len(students_list))

    keyboard = types.InlineKeyboardMarkup()
    for student in students_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{student[0]}', callback_data=f'student_{student[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_students"]> 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_students'))
    if end_index < len(students_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_students'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите студента:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"]= sent_message.message_id
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="del_attendance")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT DISTINCT sb.name, sb.id
    FROM subjects sb
    INNER JOIN schedule sc ON sb.id = sc.subject_id
    WHERE sc.date = %s AND sc.group_id = %s
""", (para["date"], para["group"]))
    subjects_list = cursor.fetchall()
    send_subjects_page(chat_id, subjects_list)
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_students', 'next_page_students'] and users[call.message.chat.id]["current_action"]=="del_attendance")
def change_students_page(call):
    if call.data == 'prev_page_students':
        users[call.message.chat.id]["current_page_students"] -= 1
    elif call.data == 'next_page_students':
        users[call.message.chat.id]["current_page_students"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT u.full_name, u.id
    FROM users u
    INNER JOIN groups g ON u.group_id = g.id
    WHERE g.id = %s
    AND u.id IN (
        SELECT student_id
        FROM attendance a
        INNER JOIN schedule s ON a.subject_id = s.subject_id
        WHERE a.date = s.date
        AND a.subject_id = %s
        AND a.date = %s
        AND a.time_start = s.start_time
    )
    ORDER BY u.full_name
""", (para["group"], para["subject"], para["date"]))

    students_list = cursor.fetchall() 
    send_students_page(chat_id, students_list)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_') and users[call.message.chat.id]["current_action"]=="del_attendance")
def select_student(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    select_student = call.data.split('_')[1]

    cursor.execute("SELECT full_name FROM users WHERE id = %s", (select_student,))
    student_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран студент - {student_name}")
    cursor.execute("""
    SELECT teacher_id, start_time
    FROM newschedule
    WHERE subject_id = %s AND date = %s AND group_id = %s
""", (para["subject"], para["date"], para["group"]))
    result = cursor.fetchone()
    teacher_id = result[0]
    time_start = result[1]
    cursor.execute("""
        DELETE FROM attendance WHERE student_id=%s AND teacher_id=%s AND subject_id=%s AND date=%s AND time_start=%s
    """, (select_student, teacher_id, para["subject"], para["date"], time_start))
    conn.commit()
    bot.send_message(chat_id, "Посещение удалено")
    users[chat_id]["current_action"]=None
    users[chat_id]["prev_message_id"]=None

@bot.callback_query_handler(func=lambda call: call.data == 'view_attendance')
def view_attendence_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    users[chat_id]["current_action"]="view_attendance"
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_groups"] = 0
    cursor.execute("""SELECT group_number, id FROM groups """)
    groups_list = cursor.fetchall()
    if not groups_list:
        bot.send_message(chat_id, "Список групп пуст.")
        users[chat_id]["current_action"]=None
        return
    send_agroups_page(chat_id, groups_list)
        
def send_agroups_page(chat_id, groups_list):

    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="view_attendance")
def select_group(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    para["group"]=selected_group
    cursor.execute("""SELECT DISTINCT sb.name, sb.id
        FROM subjects sb
        INNER JOIN newschedule sc ON sb.id = sc.subject_id
        WHERE sc.group_id = %s
    """, (para["group"]),)
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="view_attendance")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT group_number, id FROM groups """)
    groups_list = cursor.fetchall()
    send_agroups_page(chat_id, groups_list)

def send_subjects_page(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="view_attendance")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1
    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT sb.name, sb.id
        FROM subjects sb
        INNER JOIN newschedule sc ON sb.id = sc.subject_id
        WHERE sc.group_id = %s
    """, (para["group"]),)
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page(chat_id, subjects_list)
students = {}
dates = []
@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="view_attendance")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    para["subject"] = selected_subject
    cursor.execute("SELECT full_name, id FROM users WHERE group_id = %s ORDER BY full_name ASC", (para["group"],))
    student_list = cursor.fetchall()
    students.clear()
    for student in student_list:
        students[student[0]]=student[1]
    cursor.execute("SELECT date FROM newschedule WHERE group_id = %s and subject_id = %s  ORDER BY date", (para["group"], para["subject"]))
    date_list = cursor.fetchall()
    dates.clear()
    for date in date_list:
        dates.append(date[0])
    users[chat_id]["current_page_dates"] = 0
    users[chat_id]["current_page_students"] = 0
    show_attendance(chat_id, students, dates)
    

def show_attendance(chat_id, students, dates):
    start_indexdates = users[chat_id]["current_page_dates"] * 5
    end_indexdates = min((users[chat_id]["current_page_dates"] + 1) * 5, len(dates))
    start_indexstudents = users[chat_id]["current_page_students"] * 20
    end_indexstudents = min((users[chat_id]["current_page_students"] + 1) * 20, len(students))
    keyboard = types.InlineKeyboardMarkup()
    table = f"{"ФИО":^35}"
    for date in dates[start_indexdates:end_indexdates]:
        table+=f"|{date.strftime('%Y-%m-%d'):^10}"
    table += f"\n"
    newlist = list(students.keys())
    for student in newlist[start_indexstudents:end_indexstudents]:
        table += f"{student:^35}"
        for date in dates[start_indexdates:end_indexdates]:
            cursor.execute("SELECT * FROM attendance WHERE subject_id = %s AND student_id = %s AND date = %s", (para["subject"], students[student], date))
            res = cursor.fetchall()
            if len(res) > 0:
                table+=f"|{"✅":^12}"
            else:
                table+=f"|{"❌":^12}"
        table += f"\n"
    control_buttons = []
    if users[chat_id]["current_page_dates"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_dates'))
    if end_indexdates < len(dates):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_dates'))
    if users[chat_id]["current_page_students"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='🔼', callback_data='up_page_students'))
    if end_indexstudents < len(students):
        control_buttons.append(types.InlineKeyboardButton(text='🔽', callback_data='down_page_students'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, f"Журнал посещений:\n```\n{table}```",parse_mode="Markdown", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_dates', 'next_page_dates'] and users[call.message.chat.id]["current_action"]=="view_attendance")
def change_dates_page(call):
    if call.data == 'prev_page_dates':
        users[call.message.chat.id]["current_page_dates"] -= 1
    elif call.data == 'next_page_dates':
        users[call.message.chat.id]["current_page_dates"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT full_name, id FROM users WHERE group_id = %s ORDER BY full_name ASC", (para["group"],))
    student_list = cursor.fetchall()
    students.clear()
    for student in student_list:
        students[student[0]]=student[1]
    cursor.execute("SELECT date FROM newschedule WHERE group_id = %s and subject_id = %s  ORDER BY date", (para["group"], para["subject"]))
    date_list = cursor.fetchall()
    dates.clear()
    for date in date_list:
        dates.append(date[0])
    show_attendance(chat_id, students, dates)

@bot.callback_query_handler(func=lambda call: call.data in ['up_page_students', 'down_page_students'] and users[call.message.chat.id]["current_action"]=="view_attendance")
def change_students_page(call):
    if call.data == 'up_page_students':
        users[call.message.chat.id]["current_page_students"] -= 1
    elif call.data == 'down_page_students':
        users[call.message.chat.id]["current_page_students"] += 1

    chat_id = call.message.chat.id
    cursor.execute("SELECT full_name, id FROM users WHERE group_id = %s ORDER BY full_name ASC", (para["group"],))
    student_list = cursor.fetchall()
    students.clear()
    for student in student_list:
        students[student[0]]=student[1]
    cursor.execute("SELECT date FROM newschedule WHERE group_id = %s and subject_id = %s ORDER BY date", (para["group"], para["subject"]))
    date_list = cursor.fetchall()
    dates.clear()
    for date in date_list:
        dates.append(date[0])
    show_attendance(chat_id, students, dates)


@bot.callback_query_handler(func=lambda call: call.data == 'add_schedule')
def view_attendence_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)

    users[chat_id]["current_action"]="add_schedule"
    bot.send_message(chat_id,"Введите дату в виде YYYY-MM-DD")

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_schedule' and users[message.chat.id]['current_step'] == None)
def add_schedule(message):
    chat_id = message.chat.id
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    date = message.text
    if date_pattern.match(date) and is_valid_date(date):
        para["date"]=date
        users[chat_id]["prev_message_id"] = None
        users[chat_id]["current_page_groups"] = 0
        cursor.execute("""SELECT group_number, id
        FROM groups""",)
        groups_list = cursor.fetchall()
        if not groups_list:
            bot.send_message(chat_id, "Список групп пуст.")
            users[chat_id]["current_action"]=None
            return
        send_groups_page_sch(chat_id, groups_list)
    else:
        bot.send_message(chat_id, "Неверный формат даты, попробуйде ещё раз.")
        
def send_groups_page_sch(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="add_schedule")
def select_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s ORDER BY group_number", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    para["group"]=selected_group
    cursor.execute("""
    SELECT DISTINCT name, id
    FROM subjects ORDER BY name""")
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page_sch(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="add_schedule")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT group_number, id
        FROM groups""",)
    groups_list = cursor.fetchall()
    send_groups_page_sch(chat_id, groups_list)

def send_subjects_page_sch(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="add_schedule")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    para["subject"] = selected_subject
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_teachers"] = 0
    cursor.execute("""
    SELECT full_name, id
    FROM users WHERE role = 'Преподаватель'  ORDER BY full_name
    """)

    teachers_list = cursor.fetchall()  # Получите список групп из базы данных

    if not teachers_list:
        bot.send_message(chat_id, "Список преподавателей пуст.")
        users[chat_id]["current_action"]=None
        return
    send_teachers_page(chat_id, teachers_list)

def send_teachers_page(chat_id, teachers_list):
    start_index = users[chat_id]["current_page_teachers"] * 10
    end_index = min((users[chat_id]["current_page_teachers"] + 1) * 10, len(teachers_list))

    keyboard = types.InlineKeyboardMarkup()
    for teacher in teachers_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{teacher[0]}', callback_data=f'teacher_{teacher[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_teachers"]  > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_teachers'))
    if end_index < len(teachers_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_teachers'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите преподавателя:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="add_schedule")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT DISTINCT name, id
    FROM subjects ORDER BY name""")
    subjects_list = cursor.fetchall()
    send_subjects_page_sch(chat_id, subjects_list)
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_teachers', 'next_page_teachers'] and users[call.message.chat.id]["current_action"]=="add_schedule")
def change_teachers_page(call):
    if call.data == 'prev_page_teachers':
        users[call.message.chat.id]["current_page_teachers"] -= 1
    elif call.data == 'next_page_teachers':
        users[call.message.chat.id]["current_page_teachers"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT full_name, id
    FROM users WHERE role = 'Преподаватель' ORDER BY full_name
    """)
    teachers_list = cursor.fetchall() 
    send_teachers_page(chat_id, teachers_list)

@bot.callback_query_handler(func=lambda call: call.data.startswith('teacher_') and users[call.message.chat.id]["current_action"]=="add_schedule")
def select_student(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_teacher = call.data.split('_')[1]

    cursor.execute("SELECT full_name FROM users WHERE id = %s", (selected_teacher,))
    teacher_name = cursor.fetchone()[0]
    para["teacher"]=selected_teacher
    bot.send_message(chat_id, f"Выбран преподаватель - {teacher_name}")
    users[chat_id]["current_step"]="add_time"
    bot.send_message(chat_id, "Введите временной интервал в формате HH:MM:SS-HH:MM:SS")

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'add_schedule' and users[message.chat.id]['current_step']=="add_time")
def add_time(message):
    chat_id = message.chat.id
    usertime=message.text
    pattern = re.compile(r'^\d{2}:\d{2}:\d{2}-\d{2}:\d{2}:\d{2}$')
    if pattern.match(usertime):
        starttime = usertime.split("-")[0]
        endtime = usertime.split("-")[1]
        if starttime < endtime and is_valid_time(starttime) and is_valid_time(endtime):
            cursor.execute("""
                SELECT * FROM newschedule 
                WHERE date = %s 
                AND group_id = %s 
                AND ((start_time <= %s AND end_time >= %s) OR 
                    (start_time <= %s AND end_time >= %s) OR 
                    (start_time >= %s AND end_time <= %s))
                """, (para["date"], para["group"], starttime, starttime, endtime, endtime, starttime, endtime))
            res1 = cursor.fetchall()
            cursor.execute("""SELECT * FROM newschedule WHERE date=%s AND teacher_id=%s 
                           AND ((start_time <= %s AND end_time >= %s) OR 
                            (start_time <= %s AND end_time >= %s) OR 
                            (start_time >= %s AND end_time <= %s))
                            """,(para["date"],para["teacher"], starttime, starttime, endtime, endtime, starttime, endtime))
            res2 = cursor.fetchall()
            if (len(res1)>0 and len(res2)>0):
                bot.send_message(chat_id, "У этой группы уже идет пара в это время, попробуйте ещё раз")
            elif (len(res1)>0):
                bot.send_message(chat_id, "У этой группы уже идет пара в это время, попробуйте ещё раз")
            elif (len(res2)>0):
                bot.send_message(chat_id, "Преподаватель уже ведёт пару в это время, попробуйте ещё раз")
            else:
                cursor.execute("""
                INSERT INTO newschedule (date,group_id,subject_id,teacher_id, start_time, end_time)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (para["date"], para["group"], para["subject"], para["teacher"], starttime, endtime))
                conn.commit()
                bot.send_message(chat_id, "Пара успешно добавлена в расписание")
                users[chat_id]["current_action"]=None
                users[chat_id]["current_step"]=None
        else:
            bot.send_message(chat_id, "Неправильный формат времени, попробуйте ещё раз")
    else:
        bot.send_message(chat_id, "Неправильный ввод, попробуйте ещё раз")
 

@bot.callback_query_handler(func=lambda call: call.data == 'delete_schedule')
def del_schedule_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)

    users[chat_id]["current_action"]="del_schedule"
    bot.send_message(chat_id,"Введите дату в виде YYYY-MM-DD")

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'del_schedule' and users[message.chat.id]['current_step'] == None)
def del_schedule(message):
    chat_id = message.chat.id
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    date = message.text
    if date_pattern.match(date) and is_valid_date(date):
        para["date"]=date
        users[chat_id]["prev_message_id"] = None
        users[chat_id]["current_page_groups"] = 0
        cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g INNER JOIN newschedule ON group_id = g.id ORDER BY g.group_number""",)
        groups_list = cursor.fetchall()
        if not groups_list:
            bot.send_message(chat_id, "Список групп пуст.")
            users[chat_id]["current_action"]=None
            return
        send_groups_page_sch(chat_id, groups_list)
    else:
        bot.send_message(chat_id, "Неверный формат даты, попробуйде ещё раз.")
        
def send_groups_page_sch(chat_id, groups_list):
    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="del_schedule")
def select_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_subjects"] = 0
    cursor.execute("SELECT group_number FROM groups WHERE id = %s ORDER BY group_number", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    para["group"]=selected_group
    cursor.execute("""
    SELECT DISTINCT s.name, s.id
    FROM subjects s INNER JOIN newschedule n ON n.subject_id=s.id WHERE n.date=%s AND group_id=%s ORDER BY name""",(para["date"],para["group"]))
    subjects_list = cursor.fetchall()  # Получите список групп из базы данных

    if not subjects_list:
        bot.send_message(chat_id, "Список предметов пуст.")
        users[chat_id]["current_action"]=None
        return
    send_subjects_page_sch(chat_id, subjects_list)

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="del_schedule")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""SELECT DISTINCT g.group_number, g.id
        FROM groups g INNER JOIN newschedule ON group_id = g.id ORDER BY g.group_number""",)
    groups_list = cursor.fetchall()
    send_groups_page_sch(chat_id, groups_list)

def send_subjects_page_sch(chat_id, subjects_list):
    start_index = users[chat_id]["current_page_subjects"] * 10
    end_index = min((users[chat_id]["current_page_subjects"] + 1) * 10, len(subjects_list))

    keyboard = types.InlineKeyboardMarkup()
    for subject in subjects_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{subject[0]}', callback_data=f'subject_{subject[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_subjects"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_subjects'))
    if end_index < len(subjects_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_subjects'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите предмет:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('subject_') and users[call.message.chat.id]["current_action"]=="del_schedule")
def select_subject(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_subject = call.data.split('_')[1]

    cursor.execute("SELECT name FROM subjects WHERE id = %s", (selected_subject,))
    subject_name = cursor.fetchone()[0]

    bot.send_message(chat_id, f"Выбран предмет - {subject_name}")
    para["subject"] = selected_subject
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_step"]="del_time"
    bot.send_message(chat_id, "Введите время начала HH:MM:SS")
    
@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_subjects', 'next_page_subjects'] and users[call.message.chat.id]["current_action"]=="del_schedule")
def change_subjects_page(call):
    if call.data == 'prev_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] -= 1
    elif call.data == 'next_page_subjects':
        users[call.message.chat.id]["current_page_subjects"] += 1

    chat_id = call.message.chat.id
    cursor.execute("""
    SELECT DISTINCT s.name, s.id
    FROM subjects s INNER JOIN newschedule n ON n.subject_id=s.id WHERE n.date=%s AND group_id=%s ORDER BY name""",(para["date"],para["group"]))
    subjects_list = cursor.fetchall()
    send_subjects_page_sch(chat_id, subjects_list)

@bot.message_handler(func=lambda message: users.get(message.chat.id) and users[message.chat.id]['current_action'] == 'del_schedule' and users[message.chat.id]['current_step']=="del_time")
def del_time(message):
    chat_id = message.chat.id
    usertime=message.text
    pattern = re.compile(r'^\d{2}:\d{2}:\d{2}$')
    if pattern.match(usertime):
        starttime = usertime.split("-")[0]
        if is_valid_time(starttime):
            cursor.execute("""
                SELECT * FROM newschedule 
                WHERE date = %s 
                AND group_id = %s 
                AND subject_id = %s
                AND start_time = %s
                """, (para["date"], para["group"],para["subject"], starttime))
            res = cursor.fetchall()
            if (len(res)>0):
                cursor.execute("""
                DELETE FROM newschedule 
                WHERE date = %s 
                AND group_id = %s 
                AND subject_id = %s
                AND start_time = %s
                    """, (para["date"], para["group"],para["subject"], starttime))
                conn.commit()
                bot.send_message(chat_id, "Пара успешно удалена из расписания")
                users[chat_id]["current_action"]=None
                users[chat_id]["current_step"]=None
            else:
                bot.send_message(chat_id, "Нет пары в это время, попробуйте ещё раз")
        else:
            bot.send_message(chat_id, "Неправильный формат времени, попробуйте ещё раз")
    else:
        bot.send_message(chat_id, "Неправильный ввод, попробуйте ещё раз") 
        
        
@bot.callback_query_handler(func=lambda call: call.data == 'view_schedule')
def view_attendence_callback(call):
    ensure_database_connection()
    chat_id = call.message.chat.id
    bot.delete_message(chat_id,call.message.id)
    users[chat_id]["current_action"]="view_schedule"
    users[chat_id]["prev_message_id"] = None
    users[chat_id]["current_page_groups"] = 0
    cursor.execute("""SELECT group_number, id FROM groups """)
    groups_list = cursor.fetchall()
    if not groups_list:
        bot.send_message(chat_id, "Список групп пуст.")
        users[chat_id]["current_action"]=None
        return
    send_agroups_page(chat_id, groups_list)
        
def send_agroups_page(chat_id, groups_list):

    start_index = users[chat_id]["current_page_groups"] * 10
    end_index = min((users[chat_id]["current_page_groups"] + 1) * 10, len(groups_list))

    keyboard = types.InlineKeyboardMarkup()
    for group in groups_list[start_index:end_index]:
        keyboard.add(types.InlineKeyboardButton(text=f'{group[0]}', callback_data=f'group_{group[1]}'))

    control_buttons = []
    if users[chat_id]["current_page_groups"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_groups'))
    if end_index < len(groups_list):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_groups'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, "Выберите группу:", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data.startswith('group_') and users[call.message.chat.id]["current_action"]=="view_schedule")
def select_group(call):
    chat_id = call.message.chat.id
    bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
    selected_group = call.data.split('_')[1]
    users[chat_id]["prev_message_id"] = None
    cursor.execute("SELECT group_number FROM groups WHERE id = %s", (selected_group,))
    group_name = cursor.fetchone()[0]
    bot.send_message(chat_id, f"Выбрана группа - {group_name}")
    para["group_id"]=selected_group
    para["group_name"] = group_name
    users[chat_id]["current_page_schedule"] = 0
    cursor.execute("SELECT date,subject_id,teacher_id,start_time,end_time FROM newschedule WHERE group_id = %s ORDER BY date ASC, start_time ASC", (selected_group,))
    paralist = cursor.fetchall()
    show_schedule(chat_id, paralist)
    

def show_schedule(chat_id, paralist):
    start_index = users[chat_id]["current_page_schedule"] * 20
    end_index = min((users[chat_id]["current_page_schedule"] + 1) * 20, len(paralist))
    keyboard = types.InlineKeyboardMarkup()
    table = f"{"Дата":^10}|{"Группа":^8}|{"Предмет":^25}|{"Преподаватель":^36}|{"Время":^17}\n"
    for onepara in paralist[start_index:end_index]:
        cursor.execute("SELECT name FROM subjects WHERE id = %s", (onepara[1],))
        subject = cursor.fetchone()[0]
        cursor.execute("SELECT full_name FROM users WHERE id = %s", (onepara[2],))
        teacher = cursor.fetchone()[0]
        table+=f"{onepara[0].strftime('%Y-%m-%d'):^10}|{para['group_name']:^8}|{subject:^25}|{teacher:^36}|{onepara[3].strftime('%H:%M:%S'):^8}-{onepara[4].strftime('%H:%M:%S'):^8}\n"
    control_buttons = []
    if users[chat_id]["current_page_schedule"] > 0:
        control_buttons.append(types.InlineKeyboardButton(text='◀️', callback_data='prev_page_schedule'))
    if end_index < len(paralist):
        control_buttons.append(types.InlineKeyboardButton(text='▶️', callback_data='next_page_schedule'))

    if control_buttons:
        keyboard.add(*control_buttons)
    if users[chat_id]["prev_message_id"]:
        try:
            bot.delete_message(chat_id, users[chat_id]["prev_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
    
    sent_message = bot.send_message(chat_id, f"Расписание:\n```\n{table}```",parse_mode="Markdown", reply_markup=keyboard)
    users[chat_id]["prev_message_id"] = sent_message.message_id
    users[chat_id]["button_message"] = sent_message.message_id

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_groups', 'next_page_groups'] and users[call.message.chat.id]["current_action"]=="view_schedule")
def change_groups_page(call):
    if call.data == 'prev_page_groups':
        users[call.message.chat.id]["current_page_groups"] -= 1
    elif call.data == 'next_page_groups':
        users[call.message.chat.id]["current_page_groups"] += 1
    chat_id = call.message.chat.id
    cursor.execute("""SELECT group_number, id FROM groups """)
    groups_list = cursor.fetchall()
    send_agroups_page(chat_id, groups_list)
    

@bot.callback_query_handler(func=lambda call: call.data in ['prev_page_schedule', 'next_page_schedule'] and users[call.message.chat.id]["current_action"]=="view_schedule")
def change_schedule_page(call):
    if call.data == 'prev_page_schedule':
        users[call.message.chat.id]["current_page_schedule"] -= 1
    elif call.data == 'next_page_schedule':
        users[call.message.chat.id]["current_page_schedule"] += 1
    chat_id = call.message.chat.id
    cursor.execute("SELECT date,subject_id,teacher_id,start_time,end_time FROM newschedule WHERE group_id = %s ORDER BY date ASC, start_time ASC", (para["group_id"],))
    paralist = cursor.fetchall()
    show_schedule(chat_id, paralist)
        
bot.polling(none_stop=True, interval=0)
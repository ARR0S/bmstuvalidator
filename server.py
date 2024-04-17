from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz

app = Flask(__name__)

# Настройка подключения к PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = 'yourip'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Определение модели данных
class QRCodeEntry(db.Model):
    __tablename__ = 'qr'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)

    def __repr__(self):
        return f'<QRCodeEntry {self.student_id}>'

# Эндпоинт для вставки данных
@app.route('/insert', methods=['POST'])
def insert_entry():
    data = request.get_json()  # Используйте get_json для получения данных JSON
    if 'student_id' in data and 'subject_id' in data and 'timestamp' in data:
        try:
             # Преобразование timestamp в объект datetime
            timestamp = datetime.fromtimestamp(float(data['timestamp']), pytz.UTC)

            # Преобразование datetime в строку в формате UTC
            timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S%z')
            new_entry = QRCodeEntry(
                student_id=data['student_id'], 
                subject_id=data['subject_id'], 
                timestamp=timestamp_str  # Используйте преобразованный объект datetime
            )
            db.session.add(new_entry)
            db.session.commit()
            return jsonify({'message': 'Entry added successfully'}), 200
        except ValueError:
            return jsonify({'error': 'Invalid timestamp format'}), 400
    else:
        return jsonify({'error': 'Missing data'}), 400  # Возвращаем ошибку, если какие-либо данные отсутствуют

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Создает таблицы при первом запуске
    app.run(host='0.0.0.0',port=5000, debug=True)

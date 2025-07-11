# database.py
import sqlite3
from datetime import datetime

DB_NAME = 'attendance.db'

def get_db_connection():
    """データベースへの接続を取得する"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    """アプリケーションに必要なテーブルを作成する"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # ユーザーテーブル (created_at を追加)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        employee_id TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')

    # シフトテーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        start_datetime TEXT NOT NULL,
        end_datetime TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')

    # 勤怠記録テーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        clock_in TEXT,
        clock_out TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')

    # 休憩記録テーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS breaks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attendance_id INTEGER NOT NULL,
        break_start TEXT,
        break_end TEXT,
        FOREIGN KEY (attendance_id) REFERENCES attendance (id)
    )''')

    # メッセージテーブル
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')

    conn.commit()
    conn.close()

# 初期化時にテーブルを作成
create_tables()
import sqlite3
import re
import os

def sanitize_filename(name):
    """ファイル名として無効な文字を削除し、安全なファイル名を生成する"""
    if not isinstance(name, str):
        return ""
    # Windows/Mac/Linuxでファイル名として使用できない文字を削除
    s_name = re.sub(r'[\\/*?:"<>|]', "", name)
    # 空白をアンダースコアに置換
    s_name = s_name.replace(" ", "_")
    return s_name

def get_db_connection(company_name):
    """会社ごとのデータベース接続を取得する"""
    sanitized_name = sanitize_filename(company_name)
    if not sanitized_name:
        return None
    
    db_dir = 'company_databases'
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)

    db_filename = os.path.join(db_dir, f"{sanitized_name}.db")
    conn = sqlite3.connect(db_filename)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(company_name):
    """会社ごとのデータベースを初期化し、テーブルを作成/更新する"""
    conn = get_db_connection(company_name)
    if conn is None:
        print(f"Error: Could not create or connect to database for company '{company_name}'")
        return

    cursor = conn.cursor()

    # users テーブル (employee_idは会社内で一意)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            employee_id TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            company TEXT NOT NULL,
            position TEXT NOT NULL,
            UNIQUE(employee_id)
        )
    ''')

    # attendance テーブル (外部キーにON DELETE CASCADEを追加)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            clock_in TEXT,
            clock_out TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')

    # breaks テーブル (外部キーにON DELETE CASCADEを追加)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_id INTEGER NOT NULL,
            break_start TEXT,
            break_end TEXT,
            FOREIGN KEY (attendance_id) REFERENCES attendance (id) ON DELETE CASCADE
        )
    ''')

    # shifts テーブル (外部キーにON DELETE CASCADEを追加)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            start_datetime TEXT NOT NULL,
            end_datetime TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')

    # messages テーブル (外部キーにON DELETE CASCADEを追加)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')

    # スキーマ更新（古いDBファイルに対応するため）
    cursor.execute("PRAGMA table_info(users)")
    columns = [row['name'] for row in cursor.fetchall()]
    if 'company' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN company TEXT")
    if 'position' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN position TEXT")

    conn.commit()
    conn.close()

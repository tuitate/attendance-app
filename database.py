import sqlite3

DATABASE_NAME = 'attendance.db'

def get_db_connection():
    """データベース接続を取得する"""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def update_db_schema():
    """
    データベースのテーブルスキーマをチェックし、必要に応じて更新する。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # --- usersテーブルの更新チェック ---
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row['name'] for row in cursor.fetchall()]
    
    if 'company' not in user_columns:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN company TEXT")
            print("Added 'company' column to 'users' table.")
        except sqlite3.Error as e:
            print(f"Error adding 'company' column: {e}")

    if 'position' not in user_columns:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN position TEXT")
            print("Added 'position' column to 'users' table.")
        except sqlite3.Error as e:
            print(f"Error adding 'position' column: {e}")

    # --- messagesテーブルの更新チェック --- # 変更・追加
    cursor.execute("PRAGMA table_info(messages)")
    message_columns = [row['name'] for row in cursor.fetchall()]

    # 'image_base64'カラムが存在しない場合、追加する
    if 'image_base64' not in message_columns:
        try:
            cursor.execute("ALTER TABLE messages ADD COLUMN image_base64 TEXT")
            print("Added 'image_base64' column to 'messages' table.")
        except sqlite3.Error as e:
            print(f"Error adding 'image_base64' column: {e}")

    conn.commit()
    conn.close()


def init_db():
    """データベースを初期化し、テーブルを作成する"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # users テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            employee_id TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    # attendance テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            clock_in TEXT,
            clock_out TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # breaks テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_id INTEGER NOT NULL,
            break_start TEXT,
            break_end TEXT,
            FOREIGN KEY (attendance_id) REFERENCES attendance (id)
        )
    ''')

    # shifts テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            start_datetime TEXT NOT NULL,
            end_datetime TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # messages テーブル # 変更・追加
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT, -- NOT NULLを削除し、画像のみの送信を許可
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            image_base64 TEXT, -- 画像をBase64文字列で保存するカラム
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    conn.commit()
    conn.close()
    
    # テーブル作成後にスキーマの更新も実行する
    update_db_schema()

if __name__ == '__main__':
    # このスクリプトを直接実行したときにDBを初期化する
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")

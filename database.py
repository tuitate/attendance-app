import sqlite3

DATABASE_NAME = 'attendance.db'

def get_db_connection():
    """データベース接続を取得する"""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def update_db_schema():
    """
    データベースのテーブルスキーマをチェックし、必要に応じて列を自動で追加する。
    これにより、DBファイルを手動で削除する必要がなくなる。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # --- usersテーブルの更新チェック ---
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row['name'] for row in cursor.fetchall()]
    
    if 'company' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN company TEXT")
        print("Added 'company' column to 'users' table.")

    if 'position' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN position TEXT")
        print("Added 'position' column to 'users' table.")

    # --- shiftsテーブルの更新チェック ---
    cursor.execute("PRAGMA table_info(shifts)")
    shift_columns = [row['name'] for row in cursor.fetchall()]

    if 'work_date' not in shift_columns:
        cursor.execute("ALTER TABLE shifts ADD COLUMN work_date TEXT")
        print("Added 'work_date' column to 'shifts' table.")

    # --- messagesテーブルの更新チェック ---
    cursor.execute("PRAGMA table_info(messages)")
    message_columns = [row['name'] for row in cursor.fetchall()]

    # 新しい列定義
    new_message_columns = {
        "sender_id": "INTEGER",
        "file_base64": "TEXT",
        "file_name": "TEXT",
        "file_type": "TEXT"
    }

    for col_name, col_type in new_message_columns.items():
        if col_name not in message_columns:
            try:
                cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
                print(f"Added '{col_name}' column to 'messages' table.")
            except sqlite3.Error as e:
                print(f"Error adding '{col_name}' column: {e}")

    # 古い'image_base64'列が存在し、新しい'file_base64'列が追加された場合、
    # データを移行して古い列を削除することも可能ですが、今回はシンプルに追加のみとします。

    conn.commit()
    conn.close()


def init_db():
    """データベースを初期化し、全てのテーブルを最新の設計で作成する"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # users テーブル
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            employee_id TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            company TEXT,
            position TEXT
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

    # shifts テーブル (work_date列を追加)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            start_datetime TEXT NOT NULL,
            end_datetime TEXT NOT NULL,
            work_date TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # messages テーブル (最新の設計)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender_id INTEGER,
            content TEXT,
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            file_base64 TEXT,
            file_name TEXT,
            file_type TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (sender_id) REFERENCES users (id)
        )
    ''')

    conn.commit()
    conn.close()
    
    # テーブル作成後にスキーマの更新も実行する
    # これにより、既に存在する古いDBも新しい構造に更新される
    update_db_schema()

if __name__ == '__main__':
    # このスクリプトを直接実行したときにDBを初期化する
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")

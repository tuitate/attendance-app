import sqlite3

DATABASE_NAME = 'attendance.db'

def get_db_connection():
    """データベース接続を取得する"""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def update_db_schema():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row['name'] for row in cursor.fetchall()]
    
    if 'company' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN company TEXT")
    if 'position' not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN position TEXT")

    cursor.execute("PRAGMA table_info(shifts)")
    shift_columns = [row['name'] for row in cursor.fetchall()]
    if 'work_date' not in shift_columns:
        cursor.execute("ALTER TABLE shifts ADD COLUMN work_date TEXT")

    cursor.execute("PRAGMA table_info(messages)")
    message_columns = [row['name'] for row in cursor.fetchall()]

    new_message_columns = {
        "sender_id": "INTEGER",
        "file_base64": "TEXT",
        "file_name": "TEXT",
        "file_type": "TEXT",
        "message_type": "TEXT DEFAULT 'SYSTEM'"
    }

    for col_name, col_type in new_message_columns.items():
        if col_name not in message_columns:
            cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
            print(f"Added '{col_name}' column to 'messages' table.")

    conn.commit()
    conn.close()


def init_db():
    """データベースを初期化し、全てのテーブルを最新の設計で作成する"""
    conn = get_db_connection()
    cursor = conn.cursor()

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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attendance_id INTEGER NOT NULL,
            break_start TEXT,
            break_end TEXT,
            FOREIGN KEY (attendance_id) REFERENCES attendance (id)
        )
    ''')

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
            message_type TEXT DEFAULT 'SYSTEM',
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (sender_id) REFERENCES users (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pinned_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pinned_user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (pinned_user_id) REFERENCES users (id),
            UNIQUE(user_id, pinned_user_id)
        )
    ''')

    conn.commit()
    conn.close()
    
    update_db_schema()

if __name__ == '__main__':
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")

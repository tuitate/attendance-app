# app.py
import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timezone, timedelta
import time as py_time
import sqlite3
import hashlib
import calendar as py_calendar
from streamlit_calendar import calendar
from dateutil.relativedelta import relativedelta
from streamlit_autorefresh import st_autorefresh
import re
import requests
import os

from database import get_db_connection, init_db

# --- API Function ---
def search_japanese_company(name):
    """国税庁のAPIを使用して法人名を検索する"""
    if not name:
        return []
    # !!! 注意: このAPIを利用するには、国税庁からアプリケーションIDを取得し、以下のIDを置き換える必要があります。
    # 詳細は国税庁のWebサイトをご確認ください。
    APP_ID = "Your_Application_ID_Here" 
    api_url = f"https://api.houjin-bangou.nta.go.jp/4/name?id={APP_ID}&name={requests.utils.quote(name)}&type=12&mode=2"
    try:
        response = requests.get(api_url, headers={"Accept": "application/json"})
        if response.status_code == 200:
            data = response.json()
            if 'corporations' in data and isinstance(data['corporations'], list):
                return [corp.get('name', 'N/A') for corp in data['corporations']]
            else:
                st.warning("APIから予期しない形式のデータが返されました。")
                return []
        else:
            st.error(f"法人情報の検索に失敗しました。ステータスコード: {response.status_code}")
            return []
    except requests.exceptions.RequestException as e:
        st.error(f"APIへの接続中にエラーが発生しました: {e}")
        return []

# --- Helper Functions ---
def hash_password(password):
    """パスワードをSHA-256でハッシュ化する"""
    return hashlib.sha256(password.encode()).hexdigest()

JST = timezone(timedelta(hours=9))

def get_jst_now():
    """タイムゾーンをJSTとして現在の時刻を取得する"""
    return datetime.now(JST)

def add_message(company_name, user_id, content):
    """メッセージをデータベースに追加する"""
    conn = get_db_connection(company_name)
    if not conn: return
    now = get_jst_now().isoformat()
    conn.execute('INSERT INTO messages (user_id, content, created_at) VALUES (?, ?, ?)',
                 (user_id, content, now))
    conn.commit()
    conn.close()

def add_broadcast_message(company_name, content):
    """メッセージをすべてのユーザーに一斉送信する"""
    conn = get_db_connection(company_name)
    if not conn: return
    try:
        all_user_ids = conn.execute('SELECT id FROM users').fetchall()
        now = get_jst_now().isoformat()
        for user_row in all_user_ids:
            conn.execute('INSERT INTO messages (user_id, content, created_at) VALUES (?, ?, ?)',
                         (user_row['id'], content, now))
        conn.commit()
    except sqlite3.Error as e:
        print(f"一斉送信メッセージの送信に失敗しました: {e}")
    finally:
        conn.close()

def validate_password(password):
    """パスワードが要件を満たしているか検証する"""
    errors = []
    if len(password) < 8:
        errors.append("・8文字以上である必要があります。")
    if not re.search(r"[a-z]", password):
        errors.append("・小文字を1文字以上含める必要があります。")
    if not re.search(r"[A-Z]", password):
        errors.append("・大文字を1文字以上含める必要があります。")
    if not re.search(r"[0-9]", password):
        errors.append("・数字を1文字以上含める必要があります。")
    return errors

# --- Session State Initialization ---
def init_session_state():
    """セッションステートを初期化する"""
    defaults = {
        'logged_in': False, 'user_id': None, 'user_name': None,
        'user_company': None, 'user_position': None, 'work_status': "not_started",
        'attendance_id': None, 'break_id': None, 'confirmation_action': None,
        'page': "タイムカード", 'last_break_reminder_date': None, 'calendar_date': date.today(),
        'clicked_date_str': None, 'last_shift_start_time': time(9, 0),
        'last_shift_end_time': time(17, 0),
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# --- Database Functions ---
def get_user(company_name, employee_id):
    """従業員IDでユーザー情報を取得"""
    conn = get_db_connection(company_name)
    if not conn: return None
    user = conn.execute('SELECT * FROM users WHERE employee_id = ?', (employee_id,)).fetchone()
    conn.close()
    return user

def register_user(company_name, name, employee_id, password, position):
    """新規ユーザーを登録"""
    conn = get_db_connection(company_name)
    if not conn: return False
    hashed_password = hash_password(password)
    now = get_jst_now().isoformat()
    try:
        conn.execute('INSERT INTO users (name, employee_id, password_hash, created_at, company, position) VALUES (?, ?, ?, ?, ?, ?)',
                     (name, employee_id, hashed_password, now, company_name, position))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        if conn: conn.close()

def update_user_password(company_name, user_id, new_password):
    """ユーザーのパスワードを更新する"""
    conn = get_db_connection(company_name)
    if not conn: return False
    new_hashed_password = hash_password(new_password)
    try:
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hashed_password, user_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"データベースエラー: {e}")
        return False
    finally:
        if conn: conn.close()

def get_today_attendance_status(company_name, user_id):
    """その日の勤怠状況をDBから取得し、セッションステートを更新"""
    today_str = date.today().isoformat()
    conn = get_db_connection(company_name)
    if not conn: return
    att = conn.execute('SELECT * FROM attendance WHERE user_id = ? AND work_date = ?', (user_id, today_str)).fetchone()
    if att:
        st.session_state.attendance_id = att['id']
        if att['clock_out']:
            st.session_state.work_status = "finished"
        elif att['clock_in']:
            last_break = conn.execute('SELECT * FROM breaks WHERE attendance_id = ? ORDER BY id DESC LIMIT 1', (att['id'],)).fetchone()
            if last_break and last_break['break_end'] is None:
                st.session_state.work_status = "on_break"
                st.session_state.break_id = last_break['id']
            else:
                st.session_state.work_status = "working"
    else:
        st.session_state.work_status = "not_started"
        st.session_state.attendance_id = None
    conn.close()

def get_user_employee_id(company_name, user_id):
    """ユーザーIDから従業員IDを取得"""
    conn = get_db_connection(company_name)
    if not conn: return "N/A"
    employee_id_row = conn.execute('SELECT employee_id FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return employee_id_row['employee_id'] if employee_id_row else "N/A"

@st.dialog("シフト登録・編集")
def shift_edit_dialog(company_name, target_date):
    st.write(f"**{target_date.strftime('%Y年%m月%d日')}** のシフト")
    conn = get_db_connection(company_name)
    if not conn: return
    existing_shift = conn.execute(
        "SELECT id, start_datetime, end_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) = ?",
        (st.session_state.user_id, target_date.isoformat())
    ).fetchone()
    conn.close()

    if existing_shift:
        default_start = datetime.fromisoformat(existing_shift['start_datetime'])
        default_end = datetime.fromisoformat(existing_shift['end_datetime'])
    else:
        is_overnight = st.session_state.last_shift_start_time > st.session_state.last_shift_end_time
        default_end_date = target_date + timedelta(days=1) if is_overnight else target_date
        default_start = datetime.combine(target_date, st.session_state.last_shift_start_time)
        default_end = datetime.combine(default_end_date, st.session_state.last_shift_end_time)

    col1, col2 = st.columns(2)
    with col1:
        start_date_input = st.date_input("出勤日", value=default_start.date())
        end_date_input = st.date_input("退勤日", value=default_end.date())
    with col2:
        start_time_input = st.time_input("出勤時刻", value=default_start.time())
        end_time_input = st.time_input("退勤時刻", value=default_end.time())
    
    start_datetime = datetime.combine(start_date_input, start_time_input)
    end_datetime = datetime.combine(end_date_input, end_time_input)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("登録・更新", use_container_width=True, type="primary"):
            if start_datetime >= end_datetime:
                st.error("出勤日時は退勤日時より前に設定してください。")
            else:
                conn = get_db_connection(company_name)
                if existing_shift:
                    conn.execute('UPDATE shifts SET start_datetime = ?, end_datetime = ? WHERE id = ?', 
                                 (start_datetime.isoformat(), end_datetime.isoformat(), existing_shift['id']))
                else:
                    conn.execute('INSERT INTO shifts (user_id, start_datetime, end_datetime) VALUES (?, ?, ?)', 
                                 (st.session_state.user_id, start_datetime.isoformat(), end_datetime.isoformat()))
                conn.commit()
                conn.close()
                st.session_state.last_shift_start_time = start_datetime.time()
                st.session_state.last_shift_end_time = end_datetime.time()
                st.toast("シフトを保存しました！", icon="✅")
                py_time.sleep(1.5)
                st.rerun()
    with col2:
        if st.button("削除", use_container_width=True):
            if existing_shift:
                conn = get_db_connection(company_name)
                conn.execute('DELETE FROM shifts WHERE id = ?', (existing_shift['id'],))
                conn.commit()
                conn.close()
                st.toast("シフトを削除しました。", icon="🗑️")
                py_time.sleep(1.5)
                st.rerun()

# --- UI Components ---
def show_login_register_page():
    st.header("ログインまたは新規登録")
    menu = ["ログイン", "新規登録"]
    choice = st.selectbox("メニューを選択", menu)

    if choice == "ログイン":
        with st.form("login_form"):
            company_name = st.text_input("会社名")
            employee_id = st.text_input("従業員ID")
            password = st.text_input("パスワード", type="password")
            submitted = st.form_submit_button("ログイン")
            if submitted:
                if not all([company_name, employee_id, password]):
                    st.error("すべての項目を入力してください。")
                elif not employee_id.isdigit():
                    st.error("従業員IDは数字で入力してください。")
                else:
                    init_db(company_name)
                    user = get_user(company_name, employee_id)
                    if user and user['password_hash'] == hash_password(password):
                        st.session_state.logged_in = True
                        st.session_state.user_id = user['id']
                        st.session_state.user_name = user['name']
                        st.session_state.user_company = user['company']
                        st.session_state.user_position = user['position']
                        get_today_attendance_status(st.session_state.user_company, user['id'])
                        st.rerun()
                    else:
                        st.error("会社名、従業員ID、またはパスワードが正しくありません。")

    elif choice == "新規登録":
        st.subheader("会社の新規登録")
        st.info("最初に会社情報を登録します。国税庁の法人番号システムから会社名を検索・選択してください。")
        
        with st.form("register_form"):
            search_term = st.text_input("会社名で検索")
            company_list = []
            if search_term:
                with st.spinner("法人情報を検索中..."):
                    company_list = search_japanese_company(search_term)
            
            if company_list:
                selected_company = st.selectbox("会社を選択してください", options=company_list)
            else:
                if search_term:
                    st.warning("検索結果が見つかりませんでした。会社名を手動で入力してください。")
                selected_company = st.text_input("会社名（手動入力）")

            st.markdown("---")
            st.markdown("管理者情報を登録してください。")
            new_name = st.text_input("管理者名")
            new_position = st.radio("役職", ("社長", "役職者"), horizontal=True)
            new_employee_id = st.text_input("従業員ID")
            st.markdown("---")
            st.markdown("パスワードは、大文字、小文字、数字を含む8文字以上で設定してください。")
            new_password = st.text_input("パスワード", type="password")
            confirm_password = st.text_input("パスワード（確認用）", type="password")
            submitted = st.form_submit_button("会社と管理者を登録してログイン")
            
            if submitted:
                company_to_register = selected_company
                password_errors = validate_password(new_password)
                if not (company_to_register and new_name and new_employee_id and new_password):
                    st.warning("すべての項目を入力してください。")
                elif not new_employee_id.isdigit():
                    st.error("従業員IDは数字で入力してください。")
                elif new_password != confirm_password:
                    st.error("パスワードが一致しません。")
                elif password_errors:
                    st.error("パスワードは以下の要件を満たす必要があります：\n" + "\n".join(password_errors))
                else:
                    init_db(company_to_register)
                    if register_user(company_to_register, new_name, new_employee_id, new_password, new_position):
                        st.success(f"会社「{company_to_register}」と管理者「{new_name}」を登録しました。")
                        py_time.sleep(2)
                        user = get_user(company_to_register, new_employee_id)
                        if user:
                            st.session_state.logged_in = True
                            st.session_state.user_id = user['id']
                            st.session_state.user_name = user['name']
                            st.session_state.user_company = user['company']
                            st.session_state.user_position = user['position']
                            get_today_attendance_status(st.session_state.user_company, user['id'])
                            st.rerun()
                    else:
                        st.error(f"会社「{company_to_register}」にその従業員IDは既に使用されています。")

def show_timecard_page():
    st_autorefresh(interval=1000, key="clock_refresh")
    st.title(f"ようこそ、{st.session_state.user_name}さん")
    st.header(get_jst_now().strftime("%Y-%m-%d %H:%M:%S"))

    action_map = {
        'clock_in': {'message': '出勤しますか？', 'func': record_clock_in},
        'clock_out': {'message': '退勤しますか？', 'func': record_clock_out},
        'break_start': {'message': '休憩を開始しますか？', 'func': record_break_start},
        'break_end': {'message': '休憩を終了しますか？', 'func': record_break_end},
        'cancel_clock_in': {'message': '本当に出勤を取り消しますか？\n\nこの操作は元に戻せません。', 'func': record_clock_in_cancellation}
    }

    button_placeholder = st.empty()
    with button_placeholder.container():
        if st.session_state.confirmation_action:
            action_details = action_map.get(st.session_state.confirmation_action)
            if action_details:
                st.warning(action_details['message'])
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("はい", use_container_width=True, type="primary"):
                        action_details['func']()
                        st.session_state.confirmation_action = None
                        st.rerun()
                with col2:
                    if st.button("いいえ", use_container_width=True):
                        st.session_state.confirmation_action = None
                        st.rerun()
        else:
            # Button logic remains the same, confirmation action will trigger the right function
            if st.session_state.work_status == "not_started":
                if st.button("出勤", key="clock_in", use_container_width=True):
                    st.session_state.confirmation_action = 'clock_in'
                    st.rerun()
            elif st.session_state.work_status == "working":
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("退勤", key="clock_out", use_container_width=True, type="primary"):
                        st.session_state.confirmation_action = 'clock_out'
                        st.rerun()
                with col2:
                    if st.button("休憩開始", key="break_start", use_container_width=True):
                        st.session_state.confirmation_action = 'break_start'
                        st.rerun()
                with col3:
                    if st.button("出勤取り消し", key="cancel_clock_in", use_container_width=True):
                        st.session_state.confirmation_action = 'cancel_clock_in'
                        st.rerun()
            elif st.session_state.work_status == "on_break":
                if st.button("休憩終了", key="break_end", use_container_width=True):
                    st.session_state.confirmation_action = 'break_end'
                    st.rerun()
    display_work_summary()

def show_shift_management_page():
    st.header("シフト管理")
    st.info("カレンダーの日付または登録済みのシフトをクリックして編集できます。")
    conn = get_db_connection(st.session_state.user_company)
    if not conn: return
    shifts = conn.execute('SELECT id, start_datetime, end_datetime FROM shifts WHERE user_id = ?', (st.session_state.user_id,)).fetchall()
    conn.close()

    events = [{"title": f"{datetime.fromisoformat(s['start_datetime']).strftime('%H:%M')}~{datetime.fromisoformat(s['end_datetime']).strftime('%H:%M')}", 
               "start": s['start_datetime'], "end": s['end_datetime'], "id": s['id']} for s in shifts]
    
    calendar_result = calendar(events=events, options={"initialView": "dayGridMonth", "locale": "ja", "selectable": True, "height": "auto"})
    if isinstance(calendar_result, dict) and ('dateClick' in calendar_result or 'eventClick' in calendar_result):
        clicked_date = None
        if 'dateClick' in calendar_result:
            clicked_date = date.fromisoformat(calendar_result['dateClick']['date'].split('T')[0])
        elif 'eventClick' in calendar_result:
            clicked_date = date.fromisoformat(calendar_result['eventClick']['event']['start'].split('T')[0])
        
        if clicked_date and clicked_date >= date.today():
            shift_edit_dialog(st.session_state.user_company, clicked_date)
        elif clicked_date:
            st.warning("過去の日付のシフトは変更できません。")

def show_shift_table_page():
    st.header("月間シフト表")
    company_name = st.session_state.user_company
    # Month navigation
    col1, col2, col3 = st.columns([1, 6, 1])
    with col1:
        if st.button("先月"): st.session_state.calendar_date -= relativedelta(months=1); st.rerun()
    with col2:
        st.subheader(st.session_state.calendar_date.strftime('%Y年 %m月'), anchor=False)
    with col3:
        if st.button("来月"): st.session_state.calendar_date += relativedelta(months=1); st.rerun()
    
    selected_date = st.session_state.calendar_date
    first_day = selected_date.replace(day=1)
    last_day = first_day.replace(day=py_calendar.monthrange(first_day.year, first_day.month)[1])
    
    conn = get_db_connection(company_name)
    if not conn: return
    # Get all users from the same company
    users = pd.read_sql_query('SELECT id, name FROM users ORDER BY id', conn)
    shifts_query = "SELECT user_id, start_datetime, end_datetime FROM shifts WHERE date(start_datetime) BETWEEN ? AND ?"
    shifts = pd.read_sql_query(shifts_query, conn, params=(first_day.isoformat(), last_day.isoformat()))
    conn.close()

    if users.empty:
        st.info("登録されている従業員がいません。")
        return

    df = pd.DataFrame(index=users['name'])
    df.index.name = "従業員名"
    date_range = pd.date_range(start=first_day, end=last_day)
    for d in date_range:
        col_name = f"{d.day} ({['月','火','水','木','金','土','日'][d.weekday()]})"
        df[col_name] = ""
    
    user_id_to_name = pd.Series(users.name.values, index=users.id).to_dict()
    for _, row in shifts.iterrows():
        employee_name = user_id_to_name.get(row['user_id'])
        if employee_name in df.index:
            start_dt = datetime.fromisoformat(row['start_datetime'])
            end_dt = datetime.fromisoformat(row['end_datetime'])
            col_name = f"{start_dt.day} ({['月','火','水','木','金','土','日'][start_dt.weekday()]})"
            df.at[employee_name, col_name] = f"{start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')}"
    st.dataframe(df)

def show_messages_page():
    st.header("メッセージ")
    conn = get_db_connection(st.session_state.user_company)
    if not conn: return
    messages = conn.execute('SELECT content, created_at FROM messages WHERE user_id = ? ORDER BY created_at DESC', (st.session_state.user_id,)).fetchall()
    conn.execute('UPDATE messages SET is_read = 1 WHERE user_id = ?', (st.session_state.user_id,))
    conn.commit()
    conn.close()
    if not messages:
        st.info("新しいメッセージはありません。")
    else:
        for msg in messages:
            st.container(border=True).markdown(f"**{datetime.fromisoformat(msg['created_at']).strftime('%Y-%m-%d %H:%M')}**\n\n{msg['content']}")

def show_user_info_page():
    st.header("ユーザー情報")
    conn = get_db_connection(st.session_state.user_company)
    if not conn: return
    user_data = conn.execute('SELECT * FROM users WHERE id = ?', (st.session_state.user_id,)).fetchone()
    conn.close()
    if user_data:
        st.text_input("名前", value=user_data['name'], disabled=True)
        st.text_input("会社名", value=user_data['company'], disabled=True)
        st.text_input("役職", value=user_data['position'], disabled=True)
        st.text_input("従業員ID", value=user_data['employee_id'], disabled=True)
        st.divider()
        st.subheader("パスワードの変更")
        with st.form("password_change_form"):
            current_password = st.text_input("現在のパスワード", type="password")
            new_password = st.text_input("新しいパスワード", type="password")
            confirm_new_password = st.text_input("新しいパスワード（確認用）", type="password")
            submitted = st.form_submit_button("パスワードを変更")
            if submitted:
                if user_data['password_hash'] == hash_password(current_password) and new_password == confirm_new_password:
                    if update_user_password(st.session_state.user_company, st.session_state.user_id, new_password):
                        st.success("パスワードが正常に変更されました。")
                        add_message(st.session_state.user_company, st.session_state.user_id, "🔒 パスワードが変更されました。")
                    else: st.error("パスワードの変更中にエラーが発生しました。")
                else: st.error("入力情報が正しくありません。")

def show_user_registration_page():
    st.header("従業員登録")
    st.info(f"「{st.session_state.user_company}」に新しい従業員を登録します。")
    with st.form("user_registration_form"):
        company_name = st.text_input("会社名", value=st.session_state.user_company, disabled=True)
        new_name = st.text_input("名前")
        new_position = st.radio("役職", ("役職者", "社員", "バイト"), horizontal=True)
        new_employee_id = st.text_input("従業員ID")
        new_password = st.text_input("初期パスワード", type="password")
        confirm_password = st.text_input("初期パスワード（確認用）", type="password")
        submitted = st.form_submit_button("この内容で登録する")
        if submitted:
            if not all([new_name, new_employee_id, new_password]):
                st.warning("名前、従業員ID、パスワードは必須です。")
            elif new_password != confirm_password:
                st.error("パスワードが一致しません。")
            else:
                if register_user(company_name, new_name, new_employee_id, new_password, new_position):
                    st.success(f"従業員「{new_name}」さんを登録しました。")
                else:
                    st.error("その従業員IDは既に使用されています。")

def show_work_status_page():
    st.header("月間勤務状況")
    # Similar to shift table, needs company context
    # ... Implementation would be similar to show_shift_table_page, calculating work hours ...
    st.info("このページは現在開発中です。")

# --- Stamping Logic ---
def record_clock_in():
    company_name = st.session_state.user_company
    conn = get_db_connection(company_name)
    if not conn: return
    now = get_jst_now()
    att_id = conn.execute('INSERT INTO attendance (user_id, work_date, clock_in) VALUES (?, ?, ?)', 
                          (st.session_state.user_id, now.date().isoformat(), now.isoformat())).lastrowid
    conn.commit()
    conn.close()
    st.session_state.attendance_id = att_id
    st.session_state.work_status = "working"
    add_broadcast_message(company_name, f"✅ {st.session_state.user_name}さん、出勤しました。")

def record_clock_out():
    company_name = st.session_state.user_company
    conn = get_db_connection(company_name)
    if not conn: return
    conn.execute('UPDATE attendance SET clock_out = ? WHERE id = ?', (get_jst_now().isoformat(), st.session_state.attendance_id))
    conn.commit()
    conn.close()
    st.session_state.work_status = "finished"
    add_broadcast_message(company_name, f"🌙 {st.session_state.user_name}さん、退勤しました。")

def record_break_start():
    company_name = st.session_state.user_company
    conn = get_db_connection(company_name)
    if not conn: return
    break_id = conn.execute('INSERT INTO breaks (attendance_id, break_start) VALUES (?, ?)', 
                            (st.session_state.attendance_id, get_jst_now().isoformat())).lastrowid
    conn.commit()
    conn.close()
    st.session_state.break_id = break_id
    st.session_state.work_status = "on_break"

def record_break_end():
    conn = get_db_connection(st.session_state.user_company)
    if not conn: return
    conn.execute('UPDATE breaks SET break_end = ? WHERE id = ?', (get_jst_now().isoformat(), st.session_state.break_id))
    conn.commit()
    conn.close()
    st.session_state.work_status = "working"
    st.session_state.break_id = None

def record_clock_in_cancellation():
    conn = get_db_connection(st.session_state.user_company)
    if not conn or not st.session_state.attendance_id: return
    conn.execute('DELETE FROM attendance WHERE id = ?', (st.session_state.attendance_id,))
    conn.commit()
    conn.close()
    add_message(st.session_state.user_company, st.session_state.user_id, "🗑️ 出勤記録を取り消しました。")
    st.session_state.work_status = "not_started"
    st.session_state.attendance_id = None
    st.session_state.break_id = None

def display_work_summary():
    if not st.session_state.get('attendance_id'): return
    conn = get_db_connection(st.session_state.user_company)
    if not conn: return
    att = conn.execute('SELECT * FROM attendance WHERE id = ?', (st.session_state.attendance_id,)).fetchone()
    breaks = conn.execute('SELECT * FROM breaks WHERE attendance_id = ?', (st.session_state.attendance_id,)).fetchall()
    conn.close()
    if not att or not att['clock_in']: return
    
    clock_in_time = datetime.fromisoformat(att['clock_in'])
    st.metric("出勤時刻", clock_in_time.strftime('%H:%M:%S'))
    
    total_break_seconds = 0
    for br in breaks:
        if br['break_start'] and br['break_end']:
            total_break_seconds += (datetime.fromisoformat(br['break_end']) - datetime.fromisoformat(br['break_start'])).total_seconds()
        elif br['break_start']: # 休憩中の場合
            total_break_seconds += (get_jst_now() - datetime.fromisoformat(br['break_start'])).total_seconds()
    
    break_hours, rem = divmod(total_break_seconds, 3600)
    st.metric("現在の休憩時間", f"{int(break_hours):02}:{int(rem/60):02}")

    end_time = datetime.fromisoformat(att['clock_out']) if att['clock_out'] else get_jst_now()
    net_work_seconds = (end_time - clock_in_time).total_seconds() - total_break_seconds
    work_hours, rem = divmod(net_work_seconds, 3600)
    st.metric("総勤務時間", f"{int(work_hours):02}:{int(rem/60):02}")

def main():
    st.set_page_config(layout="wide")
    init_session_state()
    
    if not st.session_state.get('logged_in'):
        show_login_register_page()
    else:
        company_name = st.session_state.user_company
        st.sidebar.title(f"🏢 {company_name}")
        st.sidebar.markdown(f"**名前:** {st.session_state.user_name}")
        st.sidebar.markdown(f"**役職:** {st.session_state.user_position}")
        
        conn = get_db_connection(company_name)
        if conn:
            unread_count = conn.execute('SELECT COUNT(*) FROM messages WHERE user_id = ? AND is_read = 0', (st.session_state.user_id,)).fetchone()[0]
            conn.close()
        else:
            unread_count = 0
        
        message_label = f"メッセージ{' 🔴' if unread_count > 0 else ''}"
            
        page_options = ["タイムカード", "シフト管理", "シフト表", "出勤状況", message_label, "ユーザー情報"]
        if st.session_state.user_position in ["社長", "役職者"]:
            page_options.insert(1, "従業員登録")

        if st.session_state.page not in page_options:
            st.session_state.page = "タイムカード"
        page = st.sidebar.radio("メニュー", page_options, key="page_selection")

        if st.sidebar.button("ログアウト"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        page_map = {
            "タイムカード": show_timecard_page,
            "従業員登録": show_user_registration_page,
            "シフト管理": show_shift_management_page,
            "シフト表": show_shift_table_page,
            "出勤状況": show_work_status_page,
            message_label: show_messages_page,
            "ユーザー情報": show_user_info_page,
        }
        page_map[page]()

if __name__ == "__main__":
    main()

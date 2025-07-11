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

from database import get_db_connection

# --- Helper Functions ---
def hash_password(password):
    """パスワードをSHA-256でハッシュ化する"""
    return hashlib.sha256(password.encode()).hexdigest()

def add_message(user_id, content):
    """メッセージをデータベースに追加する"""
    conn = get_db_connection()
    now = datetime.now().isoformat()
    conn.execute('INSERT INTO messages (user_id, content, created_at) VALUES (?, ?, ?)',
                 (user_id, content, now))
    conn.commit()
    conn.close()

def add_broadcast_message(content):
    """メッセージをすべてのユーザーに一斉送信する"""
    conn = get_db_connection()
    try:
        all_user_ids = conn.execute('SELECT id FROM users').fetchall()
        now = datetime.now().isoformat()
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
        'logged_in': False,
        'user_id': None,
        'user_name': None,
        'work_status': "not_started",
        'attendance_id': None,
        'break_id': None,
        'confirmation_action': None,
        'page': "タイムカード",
        'last_break_reminder_date': None,
        'calendar_date': date.today(),
        'clicked_date_str': None,
        'last_shift_start_time': time(9, 0),
        'last_shift_end_time': time(17, 0),
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# --- Database Functions ---
def get_user(employee_id):
    """従業員IDでユーザー情報を取得"""
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE employee_id = ?', (employee_id,)).fetchone()
    conn.close()
    return user

def register_user(name, employee_id, password):
    """新規ユーザーを登録"""
    conn = get_db_connection()
    hashed_password = hash_password(password)
    now = datetime.now().isoformat()
    try:
        conn.execute('INSERT INTO users (name, employee_id, password_hash, created_at) VALUES (?, ?, ?, ?)',
                     (name, employee_id, hashed_password, now))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_user_password(user_id, new_password):
    """ユーザーのパスワードを更新する"""
    conn = get_db_connection()
    new_hashed_password = hash_password(new_password)
    try:
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hashed_password, user_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"データベースエラー: {e}")
        return False
    finally:
        conn.close()

def get_today_attendance_status(user_id):
    """その日の勤怠状況をDBから取得し、セッションステートを更新"""
    today_str = date.today().isoformat()
    conn = get_db_connection()
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

def get_user_employee_id(user_id):
    """ユーザーIDから従業員IDを取得"""
    conn = get_db_connection()
    employee_id_row = conn.execute('SELECT employee_id FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return employee_id_row['employee_id'] if employee_id_row else "N/A"

# ★★★ ここからが今回の主要な修正箇所です ★★★
@st.dialog("シフト登録・編集")
def shift_edit_dialog(target_date):
    """シフトを編集するためのポップアップダイアログ"""
    st.write(f"**{target_date.strftime('%Y年%m月%d日')}** のシフト")
    
    conn = get_db_connection()
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
                conn = get_db_connection()
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
                py_time.sleep(1.5) # 1秒待ってから画面を更新
                st.session_state.clicked_date_str = None
                st.rerun()

    with col2:
        if st.button("削除", use_container_width=True):
            if existing_shift:
                conn = get_db_connection()
                conn.execute('DELETE FROM shifts WHERE id = ?', (existing_shift['id'],))
                conn.commit()
                conn.close()
                st.toast("シフトを削除しました。", icon="🗑️")
                py_time.sleep(1.5) # 1秒待ってから画面を更新
                st.session_state.clicked_date_str = None
            st.rerun()

# --- UI Components ---
def show_login_register_page():
    st.header("ログインまたは新規登録")
    menu = ["ログイン", "新規登録"]
    choice = st.selectbox("メニューを選択", menu)
    if choice == "ログイン":
        with st.form("login_form"):
            employee_id = st.text_input("従業員ID")
            password = st.text_input("パスワード", type="password")
            submitted = st.form_submit_button("ログイン")
            if submitted:
                if not employee_id.isdigit():
                    st.error("従業員IDは数字で入力してください。")
                else:
                    user = get_user(employee_id)
                    if user and user['password_hash'] == hash_password(password):
                        st.session_state.logged_in = True
                        st.session_state.user_id = user['id']
                        st.session_state.user_name = user['name']
                        get_today_attendance_status(user['id'])
                        st.rerun()
                    else:
                        st.error("従業員IDまたはパスワードが正しくありません。")
    elif choice == "新規登録":
        with st.form("register_form"):
            st.markdown("パスワードは、大文字、小文字、数字を含む8文字以上で設定してください。")
            new_name = st.text_input("名前")
            new_employee_id = st.text_input("従業員ID")
            new_password = st.text_input("パスワード", type="password")
            confirm_password = st.text_input("パスワード（確認用）", type="password")
            submitted = st.form_submit_button("登録してログイン")
            if submitted:
                password_errors = validate_password(new_password)
                if not (new_name and new_employee_id and new_password):
                    st.warning("すべての項目を入力してください。")
                elif not new_employee_id.isdigit():
                    st.error("従業員IDは数字で入力してください。")
                elif new_password != confirm_password:
                    st.error("パスワードが一致しません。")
                elif password_errors:
                    error_message = "パスワードは以下の要件を満たす必要があります：\n" + "\n".join(password_errors)
                    st.error(error_message)
                else:
                    if register_user(new_name, new_employee_id, new_password):
                        st.success("登録が完了しました。")
                        user = get_user(new_employee_id)
                        if user:
                            st.session_state.logged_in = True
                            st.session_state.user_id = user['id']
                            st.session_state.user_name = user['name']
                            get_today_attendance_status(user['id'])
                            st.rerun()
                    else:
                        st.error("その従業員IDは既に使用されています。")

def show_timecard_page():
    st_autorefresh(interval=1000, key="clock_refresh")
    st.title(f"ようこそ、{st.session_state.user_name}さん")
    st.header(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

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
            if st.session_state.work_status == "not_started":
                if st.button("出勤", key="clock_in", use_container_width=True):
                    conn = get_db_connection()
                    today_str = date.today().isoformat()
                    shift = conn.execute("SELECT start_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) = ?", (st.session_state.user_id, today_str)).fetchone()
                    conn.close()
                    can_clock_in = True
                    if shift:
                        start_dt = datetime.fromisoformat(shift['start_datetime'])
                        earliest_clock_in = start_dt - timedelta(minutes=5)
                        if datetime.now() < earliest_clock_in:
                            st.toast(f"出勤時刻の5分前（{earliest_clock_in.strftime('%H:%M')}）から打刻できます。", icon="⚠️")
                            can_clock_in = False
                    if can_clock_in:
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
    st.info("カレンダーの日付または登録済みのシフトをクリックして編集できます。シフトの反映はページを変更するか、月を変更することで反映されます。")

    conn = get_db_connection()
    shifts = conn.execute('SELECT id, start_datetime, end_datetime FROM shifts WHERE user_id = ?', (st.session_state.user_id,)).fetchall()
    conn.close()

    events = []
    for shift in shifts:
        start_dt = datetime.fromisoformat(shift['start_datetime'])
        end_dt = datetime.fromisoformat(shift['end_datetime'])
        
        title = f"{start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')}"
        if start_dt.time() >= time(22, 0) or end_dt.time() <= time(5, 0):
            title += " (夜)"

        events.append({"title": title, "start": start_dt.isoformat(), "end": end_dt.isoformat(), "color": "#FF6347" if (start_dt.time() >= time(22, 0) or end_dt.time() <= time(5, 0)) else "#1E90FF", "id": shift['id'], "allDay": False})
        
    col1, col2, col3 = st.columns([1, 6, 1])
    with col1:
        if st.button("先月"):
            st.session_state.calendar_date -= relativedelta(months=1)
            st.rerun()
    with col2:
        st.subheader(st.session_state.calendar_date.strftime('%Y年 %m月'), anchor=False, divider='blue')
    with col3:
        if st.button("来月"):
            st.session_state.calendar_date += relativedelta(months=1)
            st.rerun()

    calendar_result = calendar(events=events, options={"headerToolbar": False, "initialDate": st.session_state.calendar_date.isoformat(), "initialView": "dayGridMonth", "locale": "ja", "selectable": True, "height": "auto"}, custom_css=".fc-event-title { font-weight: 700; }\n.fc-toolbar-title { font-size: 1.5rem; }\n.fc-view-harness { height: 650px !important; }", key=f"calendar_{st.session_state.calendar_date}")

    if isinstance(calendar_result, dict):
        clicked_date = None
        if 'dateClick' in calendar_result:
            utc_dt = datetime.fromisoformat(calendar_result['dateClick']['date'].replace('Z', '+00:00'))
            clicked_date = utc_dt.astimezone(timezone(timedelta(hours=9))).date()
        elif 'eventClick' in calendar_result:
            start_str = calendar_result['eventClick']['event']['start'].split('T')[0]
            clicked_date = date.fromisoformat(start_str)

        if clicked_date:
            if clicked_date < date.today():
                st.warning("過去の日付のシフトは変更できません。")
            else:
                shift_edit_dialog(clicked_date)
    
    if st.session_state.clicked_date_str:
        edit_date = date.fromisoformat(st.session_state.clicked_date_str)
        if edit_date < date.today():
            st.warning("過去の日付のシフトは変更できません。")
        else:
            with st.container(border=True):
                st.subheader(f"🗓️ {edit_date.strftime('%Y年%m月%d日')} のシフト登録・編集")
                
                conn = get_db_connection()
                existing_shift = conn.execute("SELECT id, start_datetime, end_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) = ?", (st.session_state.user_id, edit_date.isoformat())).fetchone()
                conn.close()

                default_start = datetime.combine(edit_date, st.session_state.last_shift_start_time)
                default_end = datetime.combine(edit_date, st.session_state.last_shift_end_time)
                if existing_shift:
                    default_start = datetime.fromisoformat(existing_shift['start_datetime'])
                    default_end = datetime.fromisoformat(existing_shift['end_datetime'])
                    
                with st.form(key=f"shift_form_{edit_date.isoformat()}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        start_date_input = st.date_input("出勤日", value=default_start.date())
                        end_date_input = st.date_input("退勤日", value=default_end.date())
                    with c2:
                        start_time_input = st.time_input("出勤時刻", value=default_start.time())
                        end_time_input = st.time_input("退勤時刻", value=default_end.time())
                    start_datetime = datetime.combine(start_date_input, start_time_input)
                    end_datetime = datetime.combine(end_date_input, end_time_input)
                    
                    # ★★★ 修正点: 「閉じる」ボタンを削除し、2列レイアウトに変更 ★★★
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.form_submit_button("登録・更新", use_container_width=True, type="primary"):
                            if start_datetime >= end_datetime:
                                st.error("出勤日時は退勤日時より前に設定してください。")
                            else:
                                # モーダル表示のための情報をセット
                                st.session_state.shift_confirmation_action = 'save'
                                st.session_state.shift_confirmation_details = {
                                    'start_datetime': start_datetime,
                                    'end_datetime': end_datetime,
                                    'existing_shift_id': existing_shift['id'] if existing_shift else None
                                }
                                st.rerun()
                    with c2:
                        if st.form_submit_button("削除", use_container_width=True):
                            if existing_shift:
                                # モーダル表示のための情報をセット
                                st.session_state.shift_confirmation_action = 'delete'
                                st.session_state.shift_confirmation_details = {
                                    'existing_shift_id': existing_shift['id']
                                }
                                st.rerun()
                            else:
                                st.toast("削除するシフトがありません。", icon="🤷")

def show_shift_table_page():
    st.header("月間シフト表")
    col1, col2, col3 = st.columns([1, 6, 1])
    with col1:
        if st.button("先月", key="table_prev"):
            st.session_state.calendar_date -= relativedelta(months=1)
            st.rerun()
    with col2:
        st.subheader(st.session_state.calendar_date.strftime('%Y年 %m月'), anchor=False, divider='blue')
    with col3:
        if st.button("来月", key="table_next"):
            st.session_state.calendar_date += relativedelta(months=1)
            st.rerun()
    selected_date = st.session_state.calendar_date
    desired_width_pixels = 100
    css = f"""
    <style>
        .stDataFrame th[data-testid="stDataFrameColumnHeader"], .stDataFrame td {{
            min-width: {desired_width_pixels}px !important;
            max-width: {desired_width_pixels}px !important;
        }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
    first_day = selected_date.replace(day=1)
    last_day = first_day.replace(day=py_calendar.monthrange(first_day.year, first_day.month)[1])
    conn = get_db_connection()
    users = pd.read_sql_query('SELECT id, name, employee_id FROM users ORDER BY id', conn)
    shifts_query = "SELECT user_id, start_datetime, end_datetime FROM shifts WHERE date(start_datetime) BETWEEN ? AND ?"
    shifts = pd.read_sql_query(shifts_query, conn, params=(first_day.isoformat(), last_day.isoformat()))
    conn.close()
    if users.empty:
        st.info("登録されている従業員がいません。")
        return
    users_for_table = users.drop_duplicates(subset=['name'], keep='first')
    df = pd.DataFrame(index=users_for_table['name'])
    df.index.name = "従業員名"
    date_range = pd.to_datetime(pd.date_range(start=first_day, end=last_day))
    for d in date_range:
        day_str = d.strftime('%d')
        weekday_str = ['月', '火', '水', '木', '金', '土', '日'][d.weekday()]
        col_name = f"{day_str} ({weekday_str})"
        df[col_name] = ""
    user_id_to_name = pd.Series(users.name.values, index=users.id).to_dict()
    for _, row in shifts.iterrows():
        employee_name = user_id_to_name.get(row['user_id'])
        if employee_name and employee_name in df.index:
            start_dt = datetime.fromisoformat(row['start_datetime'])
            end_dt = datetime.fromisoformat(row['end_datetime'])
            day_str = start_dt.strftime('%d')
            weekday_str = ['月', '火', '水', '木', '金', '土', '日'][start_dt.weekday()]
            col_name = f"{day_str} ({weekday_str})"
            start_t = start_dt.strftime('%H:%M')
            end_t = end_dt.strftime('%m/%d %H:%M') if start_dt.date() != end_dt.date() else end_dt.strftime('%H:%M')
            df.at[employee_name, col_name] = f"{start_t}～{end_t}"
    st.dataframe(df, use_container_width=True)

def show_messages_page():
    st.header("メッセージ")
    conn = get_db_connection()
    messages = conn.execute('SELECT content, created_at FROM messages WHERE user_id = ? ORDER BY created_at DESC', (st.session_state.user_id,)).fetchall()
    if not messages:
        st.info("新しいメッセージはありません。")
    else:
        for msg in messages:
            content = msg['content']
            created_at = datetime.fromisoformat(msg['created_at']).strftime('%Y年%m月%d日 %H:%M')
            st.container(border=True).markdown(f"**{created_at}**\n\n{content}")
    conn.execute('UPDATE messages SET is_read = 1 WHERE user_id = ?', (st.session_state.user_id,))
    conn.commit()
    conn.close()

def show_user_info_page():
    st.header("ユーザー情報")
    conn = get_db_connection()
    user_data = conn.execute('SELECT name, employee_id, created_at, password_hash FROM users WHERE id = ?', (st.session_state.user_id,)).fetchone()
    conn.close()
    if user_data:
        st.text_input("名前", value=user_data['name'], disabled=True)
        st.text_input("従業員ID", value=user_data['employee_id'], disabled=True)
        created_dt = datetime.fromisoformat(user_data['created_at'])
        st.text_input("登録日時", value=created_dt.strftime('%Y年%m月%d日 %H:%M:%S'), disabled=True)
        st.divider()
        st.subheader("パスワードの変更")
        with st.form("password_change_form"):
            current_password = st.text_input("現在のパスワード", type="password")
            new_password = st.text_input("新しいパスワード", type="password")
            confirm_new_password = st.text_input("新しいパスワード（確認用）", type="password")
            submitted = st.form_submit_button("パスワードを変更")
            if submitted:
                if not all([current_password, new_password, confirm_new_password]):
                    st.error("すべてのパスワード欄を入力してください。")
                elif user_data['password_hash'] != hash_password(current_password):
                    st.error("現在のパスワードが正しくありません。")
                elif new_password != confirm_new_password:
                    st.error("新しいパスワードが一致しません。")
                else:
                    password_errors = validate_password(new_password)
                    if password_errors:
                        error_message = "新しいパスワードは以下の要件を満たす必要があります：\n" + "\n".join(password_errors)
                        st.error(error_message)
                    else:
                        if update_user_password(st.session_state.user_id, new_password):
                            st.success("パスワードが正常に変更されました。")
                            add_message(st.session_state.user_id, "🔒 パスワードが変更されました。")
                        else:
                            st.error("パスワードの変更中にエラーが発生しました。")

def show_work_status_page():
    st.header("出勤状況")
    col1, col2, col3 = st.columns([1, 6, 1])
    with col1:
        if st.button("先月", key="status_prev"):
            st.session_state.calendar_date -= relativedelta(months=1)
            st.rerun()
    with col2:
        st.subheader(st.session_state.calendar_date.strftime('%Y年 %m月'), anchor=False, divider='blue')
    with col3:
        if st.button("来月", key="status_next"):
            st.session_state.calendar_date += relativedelta(months=1)
            st.rerun()
    selected_month = st.session_state.calendar_date
    first_day = selected_month.replace(day=1)
    last_day = (first_day + relativedelta(months=1)) - timedelta(days=1)
    conn = get_db_connection()
    shifts = conn.execute("SELECT start_datetime, end_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) BETWEEN ? AND ?", (st.session_state.user_id, first_day.isoformat(), last_day.isoformat())).fetchall()
    total_scheduled_seconds = 0
    for shift in shifts:
        start_dt = datetime.fromisoformat(shift['start_datetime'])
        end_dt = datetime.fromisoformat(shift['end_datetime'])
        total_scheduled_seconds += (end_dt - start_dt).total_seconds()
    attendances = conn.execute("SELECT id, clock_in, clock_out FROM attendance WHERE user_id = ? AND work_date BETWEEN ? AND ?", (st.session_state.user_id, first_day.isoformat(), last_day.isoformat())).fetchall()
    total_actual_work_seconds = 0
    total_break_seconds = 0
    for att in attendances:
        if att['clock_in'] and att['clock_out']:
            clock_in_dt = datetime.fromisoformat(att['clock_in'])
            clock_out_dt = datetime.fromisoformat(att['clock_out'])
            total_actual_work_seconds += (clock_out_dt - clock_in_dt).total_seconds()
            breaks = conn.execute("SELECT break_start, break_end FROM breaks WHERE attendance_id = ?", (att['id'],)).fetchall()
            for br in breaks:
                if br['break_start'] and br['break_end']:
                    break_start_dt = datetime.fromisoformat(br['break_start'])
                    break_end_dt = datetime.fromisoformat(br['break_end'])
                    total_break_seconds += (break_end_dt - break_start_dt).total_seconds()
    conn.close()
    net_actual_work_seconds = total_actual_work_seconds - total_break_seconds
    def format_seconds_to_hours_minutes(seconds):
        hours, remainder = divmod(int(seconds), 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}時間 {minutes:02}分"
    scheduled_str = format_seconds_to_hours_minutes(total_scheduled_seconds)
    actual_str = format_seconds_to_hours_minutes(net_actual_work_seconds)
    break_str = format_seconds_to_hours_minutes(total_break_seconds)
    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric("出勤予定時間", scheduled_str)
    col2.metric("実働時間", actual_str)
    col3.metric("合計休憩時間", break_str)
    st.divider()

# --- Stamping Logic ---
def record_clock_in():
    conn = get_db_connection()
    now = datetime.now()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO attendance (user_id, work_date, clock_in) VALUES (?, ?, ?)', (st.session_state.user_id, now.date().isoformat(), now.isoformat()))
    conn.commit()
    st.session_state.attendance_id = cursor.lastrowid
    st.session_state.work_status = "working"
    conn.close()
    add_broadcast_message(f"✅ {st.session_state.user_name}さん、出勤しました。（{now.strftime('%H:%M')}）")

def record_clock_out():
    conn = get_db_connection()
    now = datetime.now()
    conn.execute('UPDATE attendance SET clock_out = ? WHERE id = ?', (now.isoformat(), st.session_state.attendance_id))
    conn.commit()
    att = conn.execute('SELECT * FROM attendance WHERE id = ?', (st.session_state.attendance_id,)).fetchone()
    breaks = conn.execute('SELECT * FROM breaks WHERE attendance_id = ?', (st.session_state.attendance_id,)).fetchall()
    conn.close()
    clock_in_time = datetime.fromisoformat(att['clock_in'])
    total_work_seconds = (now - clock_in_time).total_seconds()
    total_break_seconds = 0
    for br in breaks:
        if br['break_start'] and br['break_end']:
            total_break_seconds += (datetime.fromisoformat(br['break_end']) - datetime.fromisoformat(br['break_start'])).total_seconds()
    add_broadcast_message(f"🌙 {st.session_state.user_name}さん、退勤しました。（{now.strftime('%H:%M')}）")
    if total_work_seconds > 8 * 3600 and total_break_seconds < 60 * 60:
        add_message(st.session_state.user_id, "⚠️ **警告:** 8時間以上の勤務に対し、休憩が60分未満です。法律に基づき、適切な休憩時間を確保してください。")
    elif total_work_seconds > 6 * 3600 and total_break_seconds < 45 * 60:
        add_message(st.session_state.user_id, "⚠️ **警告:** 6時間以上の勤務に対し、休憩が45分未満です。法律に基づき、適切な休憩時間を確保してください。")
    st.session_state.work_status = "finished"

def record_break_start():
    conn = get_db_connection()
    now = datetime.now()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO breaks (attendance_id, break_start) VALUES (?, ?)', (st.session_state.attendance_id, now.isoformat()))
    conn.commit()
    st.session_state.break_id = cursor.lastrowid
    st.session_state.work_status = "on_break"
    conn.close()

def record_break_end():
    conn = get_db_connection()
    now = datetime.now()
    conn.execute('UPDATE breaks SET break_end = ? WHERE id = ?', (now.isoformat(), st.session_state.break_id))
    conn.commit()
    st.session_state.work_status = "working"
    st.session_state.break_id = None
    conn.close()

def record_clock_in_cancellation():
    if st.session_state.attendance_id:
        conn = get_db_connection()
        conn.execute('DELETE FROM breaks WHERE attendance_id = ?', (st.session_state.attendance_id,))
        conn.execute('DELETE FROM attendance WHERE id = ?', (st.session_state.attendance_id,))
        conn.commit()
        conn.close()
        add_message(st.session_state.user_id, f"🗑️ 出勤記録を取り消しました。")
        st.session_state.work_status = "not_started"
        st.session_state.attendance_id = None
        st.session_state.break_id = None

def display_work_summary():
    if st.session_state.get('attendance_id'):
        conn = get_db_connection()
        att = conn.execute('SELECT * FROM attendance WHERE id = ?', (st.session_state.attendance_id,)).fetchone()
        breaks = conn.execute('SELECT * FROM breaks WHERE attendance_id = ?', (st.session_state.attendance_id,)).fetchall()
        today_str = date.today().isoformat()
        shift = conn.execute("SELECT start_datetime, end_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) = ?", (st.session_state.user_id, today_str)).fetchone()
        conn.close()
        scheduled_end_time_str = "---"
        scheduled_break_str = "---"
        if shift:
            start_dt = datetime.fromisoformat(shift['start_datetime'])
            end_dt = datetime.fromisoformat(shift['end_datetime'])
            scheduled_end_time_str = end_dt.strftime('%H:%M')
            shift_duration = end_dt - start_dt
            scheduled_work_hours = shift_duration.total_seconds() / 3600
            scheduled_break_minutes = 0
            if scheduled_work_hours > 8:
                scheduled_break_minutes = 60
            elif scheduled_work_hours > 6:
                scheduled_break_minutes = 45
            if scheduled_break_minutes > 0:
                break_start_estimate_dt = start_dt + (shift_duration / 2) - timedelta(minutes=scheduled_break_minutes / 2)
                scheduled_break_start_time_str = break_start_estimate_dt.strftime('%H:%M')
                scheduled_break_str = f"{scheduled_break_start_time_str} に {scheduled_break_minutes}分"
                reminder_time = break_start_estimate_dt - timedelta(minutes=10)
                now = datetime.now()
                if st.session_state.last_break_reminder_date != today_str:
                    if now >= reminder_time and now < break_start_estimate_dt:
                        add_message(st.session_state.user_id, "⏰ まもなく休憩の時間です。準備をしてください。")
                        st.session_state.last_break_reminder_date = today_str
                        st.toast("休憩10分前のお知らせをメッセージに送信しました。")
        st.divider()
        row1_col1, row1_col2 = st.columns(2)
        row2_col1, row2_col2 = st.columns(2)
        with row1_col1:
            st.metric("出勤時刻", datetime.fromisoformat(att['clock_in']).strftime('%H:%M:%S') if att['clock_in'] else "---")
        with row1_col2:
            st.metric("退勤予定時刻", scheduled_end_time_str)
        with row2_col1:
            st.metric("休憩予定", scheduled_break_str)
        with row2_col2:
            total_break_seconds = 0
            for br in breaks:
                if br['break_start'] and br['break_end']:
                    total_break_seconds += (datetime.fromisoformat(br['break_end']) - datetime.fromisoformat(br['break_start'])).total_seconds()
                elif br['break_start']:
                    total_break_seconds += (datetime.now() - datetime.fromisoformat(br['break_start'])).total_seconds()
            break_hours, rem = divmod(total_break_seconds, 3600)
            break_minutes, _ = divmod(rem, 60)
            st.metric("現在の休憩時間", f"{int(break_hours):02}:{int(break_minutes):02}")
        st.divider()
        if att['clock_in']:
            if att['clock_out']:
                clock_out_time = datetime.fromisoformat(att['clock_out'])
                total_work_seconds = (clock_out_time - datetime.fromisoformat(att['clock_in'])).total_seconds()
            else:
                total_work_seconds = (datetime.now() - datetime.fromisoformat(att['clock_in'])).total_seconds()
            net_work_seconds = total_work_seconds - total_break_seconds
            work_hours, rem = divmod(net_work_seconds, 3600)
            work_minutes, _ = divmod(rem, 60)
            st.metric("総勤務時間", f"{int(work_hours):02}:{int(work_minutes):02}")
        else:
            st.metric("総勤務時間", "00:00")
        st.divider()

def main():
    """メインのアプリケーションロジック"""
    st.set_page_config(layout="wide")
    init_session_state()
    
    if not st.session_state.get('logged_in'):
        show_login_register_page()
    else:
        st.sidebar.title("メニュー")
        st.sidebar.markdown(f"**名前:** {st.session_state.user_name}")
        st.sidebar.markdown(f"**従業員ID:** {get_user_employee_id(st.session_state.user_id)}")
        
        conn = get_db_connection()
        unread_count = conn.execute('SELECT COUNT(*) FROM messages WHERE user_id = ? AND is_read = 0', (st.session_state.user_id,)).fetchone()[0]
        conn.close()
        
        message_label = "メッセージ"
        if unread_count > 0:
            message_label = f"メッセージ 🔴 ({unread_count})"
            
        page_options = ["タイムカード", "シフト管理", "シフト表", "出勤状況", message_label, "ユーザー情報"]
        
        try:
            current_page_index = page_options.index(st.session_state.page)
        except ValueError:
            current_page_index = 0

        page = st.sidebar.radio("ページを選択", page_options, index=current_page_index)

        if st.session_state.page != page:
             st.session_state.page = page
             st.rerun()

        if st.sidebar.button("ログアウト"):
            st.session_state.clear()
            st.rerun()

        page_to_show = st.session_state.get('page', "タイムカード")
        
        if page_to_show == "タイムカード":
            show_timecard_page()
        elif page_to_show == "シフト管理":
            show_shift_management_page()
        elif page_to_show == "シフト表":
            show_shift_table_page()
        elif page_to_show == "出勤状況":
            show_work_status_page()
        elif page_to_show.startswith("メッセージ"):
            show_messages_page()
        elif page_to_show == "ユーザー情報":
            show_user_info_page()

if __name__ == "__main__":
    main()

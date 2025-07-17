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
import base64
import japanize_matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from database import get_db_connection, init_db

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

JST = timezone(timedelta(hours=9))

def get_jst_now():
    return datetime.now(JST)

def add_message(user_id, content):
    conn = get_db_connection()
    now = get_jst_now().isoformat()
    conn.execute('INSERT INTO messages (user_id, sender_id, content, created_at, message_type) VALUES (?, ?, ?, ?, ?)',
                 (user_id, user_id, content, now, 'SYSTEM'))
    conn.commit()
    conn.close()

def add_broadcast_message(sender_id, content, company_name, file_base64=None, file_name=None, file_type=None):
    conn = get_db_connection()
    try:
        users_in_company = conn.execute('SELECT id FROM users WHERE company = ?', (company_name,)).fetchall()
        now = get_jst_now().isoformat()
        for user_row in users_in_company:
            conn.execute('INSERT INTO messages (user_id, sender_id, content, created_at, file_base64, file_name, file_type, message_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         (user_row['id'], sender_id, content, now, file_base64, file_name, file_type, 'BROADCAST'))
        conn.commit()
    except sqlite3.Error as e:
        print(f"一斉送信メッセージの送信に失敗しました: {e}")
    finally:
        conn.close()

def add_direct_message(sender_id, recipient_id, content, file_base64=None, file_name=None, file_type=None):
    conn = get_db_connection()
    now = get_jst_now().isoformat()
    try:
        conn.execute('INSERT INTO messages (user_id, sender_id, content, created_at, file_base64, file_name, file_type, message_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                     (recipient_id, sender_id, content, now, file_base64, file_name, file_type, 'DIRECT'))
        conn.commit()
    except sqlite3.Error as e:
        print(f"ダイレクトメッセージの送信に失敗しました: {e}")
    finally:
        conn.close()

def render_dm_chat_window(recipient_id, recipient_name):
    st.subheader(f"💬 {recipient_name}さんとのメッセージ")
    
    current_user_id = st.session_state.user_id
    conn = get_db_connection()
    try:
        conn.execute("""
            UPDATE messages
            SET is_read = 1
            WHERE user_id = ? AND sender_id = ? AND is_read = 0 AND message_type = 'DIRECT'
        """, (current_user_id, recipient_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"DMの既読処理中にエラー: {e}")
    finally:
        conn.close()

    chat_container = st.container(height=500)
    with chat_container:
        conn = get_db_connection()
        messages = conn.execute("""
            SELECT * FROM messages
            WHERE message_type = 'DIRECT' AND
                  ((user_id = ? AND sender_id = ?) OR (user_id = ? AND sender_id = ?))
            ORDER BY created_at ASC
        """, (current_user_id, recipient_id, recipient_id, current_user_id)).fetchall()
        conn.close()

        for msg in messages:
            role = "user" if msg['sender_id'] == current_user_id else "assistant"

            created_at_dt = datetime.fromisoformat(msg['created_at'])

            with st.chat_message(role):
                if msg['content']:
                    st.markdown(msg['content'])
                if msg['file_base64']:
                    file_bytes = base64.b64decode(msg['file_base64'])
                    if msg['file_type'] and msg['file_type'].startswith("image/"):
                        st.image(file_bytes)
                    else:
                        st.download_button(
                            label=f"📎 {msg['file_name']}",
                            data=file_bytes,
                            file_name=msg['file_name'],
                            mime=msg['file_type']
                        )

                st.caption(created_at_dt.strftime('%H:%M'))

    with st.container():
        message_input = st.text_area("メッセージを入力...", key=f"dm_input_{recipient_id}", label_visibility="collapsed", height=100)
        file_input = st.file_uploader("ファイルを添付", key=f"dm_file_{recipient_id}", label_visibility="collapsed")
        
        if st.button("送信", key=f"dm_send_{recipient_id}"):
            if message_input or file_input:
                file_base64, file_name, file_type = None, None, None
                if file_input:
                    file_bytes = file_input.getvalue()
                    file_base64 = base64.b64encode(file_bytes).decode()
                    file_name = file_input.name
                    file_type = file_input.type
                
                add_direct_message(current_user_id, recipient_id, message_input, file_base64, file_name, file_type)
                st.rerun()

def delete_broadcast_message(created_at_iso):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM messages WHERE created_at = ?', (created_at_iso,))
        conn.commit()
    except sqlite3.Error as e:
        st.error(f"メッセージの削除中にエラーが発生しました: {e}")
    finally:
        conn.close()

def validate_password(password):
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

def init_session_state():
    defaults = {
        'logged_in': False,
        'user_id': None,
        'user_name': None,
        'user_company': None,
        'user_position': None,
        'work_status': "not_started",
        'attendance_id': None,
        'break_id': None,
        'confirmation_action': None,
        'page': "タイムカード",
        'last_break_reminder_date': None,
        'last_clock_out_reminder_date': None,
        'calendar_date': date.today(),
        'clicked_date_str': None,
        'last_shift_start_time': time(9, 0),
        'last_shift_end_time': time(17, 0),
        'confirming_delete_message_created_at': None,
        'clock_in_error': None,
        'confirming_delete_user_id': None,
        'dm_selected_user_id': None,
        'editing_date': None,
        'show_broadcast_dialog': False,
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def get_user(employee_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE employee_id = ?', (employee_id,)).fetchone()
    conn.close()
    return user

def register_user(name, employee_id, password, company, position):
    conn = get_db_connection()
    hashed_password = hash_password(password)
    now = get_jst_now().isoformat()
    try:
        conn.execute('INSERT INTO users (name, employee_id, password_hash, created_at, company, position) VALUES (?, ?, ?, ?, ?, ?)',
                     (name, employee_id, hashed_password, now, company, position))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_user_password(user_id, new_password):
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

def delete_user(user_id_to_delete):
    conn = get_db_connection()
    try:
        attendance_ids_tuples = conn.execute('SELECT id FROM attendance WHERE user_id = ?', (user_id_to_delete,)).fetchall()
        attendance_ids = [item['id'] for item in attendance_ids_tuples]

        if attendance_ids:
            placeholders = ','.join('?' for _ in attendance_ids)
            conn.execute(f'DELETE FROM breaks WHERE attendance_id IN ({placeholders})', attendance_ids)

        conn.execute('DELETE FROM attendance WHERE user_id = ?', (user_id_to_delete,))
        conn.execute('DELETE FROM shifts WHERE user_id = ?', (user_id_to_delete,))
        conn.execute('DELETE FROM messages WHERE user_id = ?', (user_id_to_delete,))
        conn.execute('DELETE FROM users WHERE id = ?', (user_id_to_delete,))
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"ユーザー削除中にエラーが発生しました: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_today_attendance_status(user_id):
    today_str = get_jst_now().date().isoformat()
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
    conn = get_db_connection()
    employee_id_row = conn.execute('SELECT employee_id FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return employee_id_row['employee_id'] if employee_id_row else "N/A"

@st.dialog("全体メッセージを送信")
def broadcast_message_dialog():
    st.subheader("全従業員へのメッセージ送信")
    with st.form(key='broadcast_dialog_form'):
        message_content = st.text_area("メッセージ内容を入力してください。", height=150)
        uploaded_file = st.file_uploader("ファイルを添付 (任意)", type=None)

        submitted = st.form_submit_button("この内容で送信する")
        if submitted:
            if message_content or uploaded_file:
                sender_name = st.session_state.user_name
                message_body = f"**【お知らせ】{sender_name}さんより**\n\n{message_content}"

                file_base64, file_name, file_type = None, None, None
                if uploaded_file is not None:
                    file_bytes = uploaded_file.getvalue()
                    file_base64 = base64.b64encode(file_bytes).decode()
                    file_name = uploaded_file.name
                    file_type = uploaded_file.type
                
                add_broadcast_message(st.session_state.user_id, message_body, st.session_state.user_company, file_base64, file_name, file_type)
                st.toast("メッセージを送信しました！", icon="✅")
                st.rerun()
                
            else:
                st.warning("メッセージ内容を入力するか、ファイルを添付してください。")

@st.dialog("シフト登録・編集")
def shift_edit_dialog(target_date):
    pass
    
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
                        st.session_state.user_company = user['company']
                        st.session_state.user_position = user['position']
                        get_today_attendance_status(user['id'])
                        st.rerun()
                    else:
                        st.error("従業員IDまたはパスワードが正しくありません。")
                        
    elif choice == "新規登録":
        with st.form("register_form"):
            st.markdown("パスワードは、大文字、小文字、数字を含む8文字以上で設定してください。")
            new_name = st.text_input("名前")
            new_company = st.text_input("会社名")
            new_position = st.radio("役職", ("社長", "役職者"), horizontal=True)
            new_employee_id = st.text_input("従業員ID")
            new_password = st.text_input("パスワード", type="password")
            confirm_password = st.text_input("パスワード（確認用）", type="password")
            submitted = st.form_submit_button("登録してログイン")
            if submitted:
                password_errors = validate_password(new_password)
                if not (new_name and new_company and new_employee_id and new_password):
                    st.warning("名前、会社名、従業員ID、パスワードは必須項目です。")
                elif not new_employee_id.isdigit():
                    st.error("従業員IDは数字で入力してください。")
                elif new_password != confirm_password:
                    st.error("パスワードが一致しません。")
                elif password_errors:
                    error_message = "パスワードは以下の要件を満たす必要があります：\n" + "\n".join(password_errors)
                    st.error(error_message)
                else:
                    if register_user(new_name, new_employee_id, new_password, new_company, new_position):
                        st.success("登録が完了しました。")
                        user = get_user(new_employee_id)
                        if user:
                            st.session_state.logged_in = True
                            st.session_state.user_id = user['id']
                            st.session_state.user_name = user['name']
                            st.session_state.user_company = user['company']
                            st.session_state.user_position = user['position']
                            get_today_attendance_status(user['id'])
                            st.rerun()
                    else:
                        st.error("その従業員IDは既に使用されています。")

def show_timecard_page():
    if not st.session_state.get('show_broadcast_dialog', False):
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
        if st.session_state.get('clock_in_error'):
            st.warning(st.session_state.clock_in_error)

        if st.session_state.get('confirmation_action'):
            action_details = action_map.get(st.session_state.confirmation_action)
            if action_details:
                st.warning(action_details['message'])
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("はい", use_container_width=True, type="primary"):
                        action_details['func']()
                        st.session_state.confirmation_action = None
                        st.session_state.clock_in_error = None
                        st.rerun()
                with col2:
                    if st.button("いいえ", use_container_width=True):
                        st.session_state.confirmation_action = None
                        st.rerun()
        else:
            if st.session_state.work_status == "not_started":
                if st.button("出勤", key="clock_in", use_container_width=True):
                    conn = get_db_connection()
                    today_str = get_jst_now().date().isoformat()
                    shift = conn.execute("SELECT start_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) = ?", (st.session_state.user_id, today_str)).fetchone()
                    conn.close()
                    
                    error_msg = None
                    if shift is None:
                        error_msg = "本日のシフトが登録されていません。先にシフトを登録してください。"
                    else:
                        naive_start_dt = datetime.fromisoformat(shift[0]) # インデックスでアクセス
                        start_dt = naive_start_dt.replace(tzinfo=JST)
                        earliest_clock_in = start_dt - timedelta(minutes=5)
                        now = get_jst_now()
                        if now < earliest_clock_in:
                            error_msg = f"出勤できません。出勤時刻の5分前（{earliest_clock_in.strftime('%H:%M')}）から打刻できます。"
                    
                    if error_msg:
                        st.session_state.clock_in_error = error_msg
                    else:
                        st.session_state.clock_in_error = None
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

def render_shift_edit_form(target_date):
    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.subheader(f"🗓️ {target_date.strftime('%Y年%m月%d日')} のシフト登録・編集")
        with col2:
            if st.button("✖️ 閉じる", help="フォームを閉じてカレンダーに戻ります"):
                st.session_state.editing_date = None
                st.rerun()

        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
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

        with st.form(key=f"shift_form_{target_date}"):
            c1, c2 = st.columns(2)
            with c1:
                start_date_input = st.date_input("出勤日", value=default_start.date())
                end_date_input = st.date_input("退勤日", value=default_end.date())
            with c2:
                start_time_input = st.time_input("出勤時刻", value=default_start.time())
                end_time_input = st.time_input("退勤時刻", value=default_end.time())

            start_datetime = datetime.combine(start_date_input, start_time_input)
            end_datetime = datetime.combine(end_date_input, end_time_input)

            btn_col1, btn_col2, _ = st.columns([1, 1, 3])
            with btn_col1:
                save_button = st.form_submit_button("登録・更新", use_container_width=True, type="primary")
            with btn_col2:
                delete_button = st.form_submit_button("削除", use_container_width=True)

        if save_button:
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
                st.session_state.editing_date = None

        if delete_button:
            if existing_shift:
                conn = get_db_connection()
                conn.execute('DELETE FROM shifts WHERE id = ?', (existing_shift['id'],))
                conn.commit()
                conn.close()
                st.toast("シフトを削除しました。", icon="🗑️")
                st.session_state.editing_date = None
            else:
                st.warning("削除するシフトが登録されていません。")
                
def show_shift_management_page():
    st.header("シフト管理")

    if st.session_state.get('editing_date'):
        render_shift_edit_form(st.session_state.editing_date)
        return

    st.info("カレンダーの日付または登録済みのシフトをクリックして編集フォームを開きます。")

    col1, col2 = st.columns([3, 2])
    with col1:
        st.subheader(st.session_state.calendar_date.strftime('%Y年 %m月'), anchor=False, divider='blue')
    with col2:
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("先月", use_container_width=True):
                st.session_state.calendar_date -= relativedelta(months=1)
                st.rerun()
        with btn_col2:
            if st.button("来月", use_container_width=True):
                st.session_state.calendar_date += relativedelta(months=1)
                st.rerun()

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    shifts = conn.execute('SELECT id, start_datetime, end_datetime FROM shifts WHERE user_id = ?', (st.session_state.user_id,)).fetchall()
    conn.close()

    events = []
    for shift in shifts:
        start_dt = datetime.fromisoformat(shift['start_datetime'])
        end_dt = datetime.fromisoformat(shift['end_datetime'])
        title = f"{start_dt.strftime('%H:%M')}~{end_dt.strftime('%H:%M')}"
        if start_dt.time() >= time(22, 0) or end_dt.time() <= time(5, 0):
            title += " (夜)"
        color = "#FF6347" if (start_dt.time() >= time(22, 0) or end_dt.time() <= time(5, 0)) else "#1E90FF"
        events.append({
            "title": title, "start": start_dt.isoformat(), "end": end_dt.isoformat(),
            "color": color, "id": shift['id'], "allDay": False
        })

    # --- ★★★ ここから修正 ★★★ ---
    # CSSでカレンダーの「最低限の高さ」を指定する
    st.markdown("""
        <style>
        .fc-view-harness {
            min-height: 700px !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # st.container(height=...) を削除し、直接カレンダーを呼び出す
    calendar_result = calendar(
        events=events,
        options={
            "headerToolbar": False,
            "initialDate": st.session_state.calendar_date.isoformat(),
            "initialView": "dayGridMonth",
            "locale": "ja",
            "selectable": True,
            "height": "auto" # 高さは自動調整に任せる
        },
        custom_css=".fc-event-title { font-weight: 700; }",
        key=f"calendar_{st.session_state.calendar_date.year}_{st.session_state.calendar_date.month}"
    )
    # --- ★★★ ここまで修正 ★★★ ---

    if isinstance(calendar_result, dict):
        clicked_date = None
        if 'dateClick' in calendar_result:
            utc_dt = datetime.fromisoformat(calendar_result['dateClick']['date'].replace('Z', '+00:00'))
            clicked_date = utc_dt.astimezone(JST).date()
        elif 'eventClick' in calendar_result:
            start_str = calendar_result['eventClick']['event']['start'].split('T')[0]
            clicked_date = date.fromisoformat(start_str)
        
        if clicked_date:
            if clicked_date < date.today():
                st.warning("過去の日付のシフトは変更できません。")
            else:
                st.session_state.editing_date = clicked_date
                st.rerun()
                
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

    first_day = st.session_state.calendar_date.replace(day=1)
    last_day = first_day.replace(day=py_calendar.monthrange(first_day.year, first_day.month)[1])

    conn = get_db_connection()
    company_name = st.session_state.user_company
    users_query = "SELECT id, name, position FROM users WHERE company = ? ORDER BY CASE position WHEN '社長' THEN 1 WHEN '役職者' THEN 2 ELSE 3 END, id"
    users = pd.read_sql_query(users_query, conn, params=(company_name,))

    if users.empty:
        st.info("あなたの会社には、まだ従業員が登録されていません。")
        conn.close()
        return

    user_ids_in_company = tuple(users['id'].tolist())
    placeholders = ','.join('?' for _ in user_ids_in_company)
    shifts_query = f"SELECT user_id, start_datetime, end_datetime FROM shifts WHERE user_id IN ({placeholders}) AND date(start_datetime) BETWEEN ? AND ?"
    params = user_ids_in_company + (first_day.isoformat(), last_day.isoformat())
    shifts = pd.read_sql_query(shifts_query, conn, params=params)
    conn.close()

    position_icons = {"社長": "👑", "役職者": "🥈", "社員": "🥉", "バイト": "👦🏿"}
    current_user_display_name = f"{position_icons.get(st.session_state.user_position, '')} {st.session_state.user_name}"
    users['display_name'] = users.apply(lambda row: f"{position_icons.get(row['position'], '')} {row['name']}", axis=1)

    df = pd.DataFrame()
    df['従業員名'] = users['display_name']
    date_range = pd.to_datetime(pd.date_range(start=first_day, end=last_day))
    for d in date_range:
        day_str = d.strftime('%d')
        weekday_str = ['月', '火', '水', '木', '金', '土', '日'][d.weekday()]
        col_name = f"{day_str} ({weekday_str})"
        df[col_name] = ""

    df.set_index(users['id'], inplace=True)
    for _, row in shifts.iterrows():
        user_id = row['user_id']
        if user_id in df.index:
            start_dt = datetime.fromisoformat(row['start_datetime'])
            end_dt = datetime.fromisoformat(row['end_datetime'])
            day_str = start_dt.strftime('%d')
            weekday_str = ['月', '火', '水', '木', '金', '土', '日'][start_dt.weekday()]
            col_name = f"{day_str} ({weekday_str})"
            start_t = start_dt.strftime('%H:%M')
            end_t = end_dt.strftime('%m/%d %H:%M') if start_dt.date() != end_dt.date() else end_dt.strftime('%H:%M')
            df.loc[user_id, col_name] = f"{start_t}～{end_t}"

    df.reset_index(drop=True, inplace=True)
    df.fillna('', inplace=True)

    def highlight_user(column, name_to_highlight):
        styles = [''] * len(column)
        try:
            idx_pos = column[column == name_to_highlight].index[0]
            styles[idx_pos] = 'background-color: rgba(230, 243, 255, 0.6)'
        except IndexError:
            pass
        return styles

    styled_df = df.style.apply(highlight_user, name_to_highlight=current_user_display_name, subset=['従業員名'])

    column_config = {
        "従業員名": st.column_config.Column(width="medium")
    }

    for col in df.columns:
        if col != "従業員名":
            column_config[col] = st.column_config.Column(width="medium")
    
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=True,
        column_config=column_config
    )
    
def show_direct_message_page():
    selected_user_id = st.session_state.get('dm_selected_user_id')

    if selected_user_id:
        conn = get_db_connection()
        recipient_info = conn.execute("SELECT name FROM users WHERE id = ?", (selected_user_id,)).fetchone()
        conn.close()

        if recipient_info:
            if st.button("＜ 宛先リストに戻る"):
                st.session_state.dm_selected_user_id = None
                st.rerun()
            render_dm_chat_window(selected_user_id, recipient_info['name'])
        else:
            st.error("ユーザーが見つかりませんでした。")
            st.session_state.dm_selected_user_id = None
            st.rerun()

    else:
        st.header("ダイレクトメッセージ")
        st.subheader("宛先リスト")

        conn = get_db_connection()
        current_user_id = st.session_state.user_id
        all_users = conn.execute("SELECT id, name FROM users WHERE company = ? AND id != ?", 
                                 (st.session_state.user_company, current_user_id)).fetchall()

        unread_senders_rows = conn.execute("SELECT DISTINCT sender_id FROM messages WHERE user_id = ? AND is_read = 0 AND message_type = 'DIRECT'", (current_user_id,)).fetchall()
        unread_sender_ids = {row['sender_id'] for row in unread_senders_rows}
        
        last_message_times_rows = conn.execute("""
            SELECT CASE WHEN sender_id = :uid THEN user_id ELSE sender_id END as partner, MAX(created_at) as last_time
            FROM messages WHERE (sender_id = :uid OR user_id = :uid) AND message_type = 'DIRECT' GROUP BY partner
        """, {"uid": current_user_id}).fetchall()
        last_message_times = {row['partner']: row['last_time'] for row in last_message_times_rows}
        conn.close()

        if not all_users:
            st.info("メッセージを送る相手がいません。")
            return

        user_info_list = []
        for user in all_users:
            user_id = user['id']
            user_info_list.append({
                "id": user_id, "name": user['name'],
                "has_unread": user_id in unread_sender_ids,
                "last_message_time": datetime.fromisoformat(last_message_times.get(user_id, "1970-01-01T00:00:00+00:00"))
            })
        
        sorted_users = sorted(user_info_list, key=lambda u: (u['has_unread'], u['last_message_time']), reverse=True)

        with st.container(height=600):
            for user in sorted_users:
                label = user['name']
                if user['has_unread']:
                    label = f"🔴 {label}"
                if st.button(label, key=f"select_dm_{user['id']}", use_container_width=True):
                    st.session_state.dm_selected_user_id = user['id']
                    st.rerun()
            
def show_messages_page():
    st.header("全体メッセージ")
    col1, col2 = st.columns([2, 1])
    with col1:
        pass
    with col2:
        if st.button("📝 全社へメッセージを送信する", use_container_width=True, type="primary"):
            st.session_state.show_broadcast_dialog = True
            st.rerun()

    if st.session_state.get('show_broadcast_dialog'):
        st.session_state.show_broadcast_dialog = False
        broadcast_message_dialog()

    st.divider()

    conn = get_db_connection()
    messages = conn.execute("""
        SELECT id, content, created_at, file_base64, file_name, file_type, sender_id FROM messages
        WHERE user_id = ? AND message_type IN ('BROADCAST', 'SYSTEM')
        ORDER BY created_at DESC
    """, (st.session_state.user_id,)).fetchall()
    
    if not messages:
        st.info("新しいメッセージはありません。")
    else:
        for msg in messages:
            with st.container(border=True):
                created_at_str = msg[2]
                is_confirming_this_message = st.session_state.get('confirming_delete_message_created_at') == created_at_str

                if is_confirming_this_message:
                    st.warning("このメッセージを全ユーザーから削除します。よろしいですか？")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("はい、削除します", key=f"confirm_delete_{msg[0]}", type="primary", use_container_width=True):
                            delete_broadcast_message(created_at_str)
                            st.session_state.confirming_delete_message_created_at = None
                            st.toast("メッセージを削除しました。")
                            st.rerun()
                    with c2:
                        if st.button("いいえ", key=f"cancel_delete_{msg[0]}", use_container_width=True):
                            st.session_state.confirming_delete_message_created_at = None
                            st.rerun()
                else:
                    msg_col1, msg_col2 = st.columns([4, 1])
                    with msg_col1:
                        created_at_dt = datetime.fromisoformat(created_at_str)
                        st.markdown(f"**{created_at_dt.strftime('%Y年%m月%d日 %H:%M')}**")
                    with msg_col2:
                        content_str = msg[1]
                        is_broadcast = content_str and content_str.startswith("**【お知らせ】")
                        if is_broadcast and msg[6] == st.session_state.user_id:
                            if st.button("🗑️ 削除", key=f"delete_{msg[0]}", use_container_width=True):
                                st.session_state.confirming_delete_message_created_at = created_at_str
                                st.rerun()
                    
                    if msg[1]:
                        st.markdown(msg[1])
                    if msg[3]:
                        file_bytes = base64.b64decode(msg[3])
                        file_type = msg[5]
                        file_name = msg[4] or "downloaded_file"

                        if file_type and file_type.startswith("image/"):
                            st.image(file_bytes)
                        else:
                            st.download_button(
                                label=f"📎 ダウンロード: {file_name}",
                                data=file_bytes,
                                file_name=file_name,
                                mime=file_type
                            )
    
    conn.execute('UPDATE messages SET is_read = 1 WHERE user_id = ? AND message_type IN ("BROADCAST", "SYSTEM")', (st.session_state.user_id,))
    conn.commit()
    conn.close()

def show_user_info_page():
    st.header("ユーザー情報")
    conn = get_db_connection()
    user_data = conn.execute('SELECT name, employee_id, created_at, password_hash, company, position FROM users WHERE id = ?', (st.session_state.user_id,)).fetchone()
    conn.close()
    if user_data:
        st.text_input("名前", value=user_data['name'], disabled=True)
        st.text_input("会社名", value=user_data['company'] or '未登録', disabled=True)
        st.text_input("役職", value=user_data['position'] or '未登録', disabled=True)
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

def confirm_delete_user_dialog(user_id, user_name):
    st.warning(f"本当に従業員「{user_name}」さんを削除しますか？\n\nこの操作は元に戻せません。関連するすべての勤怠記録やシフト情報も削除されます。")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("はい、削除します", key=f"confirm_del_{user_id}", use_container_width=True, type="primary"):
            if delete_user(user_id):
                st.toast(f"「{user_name}」さんを削除しました。", icon="✅")
            else:
                st.error("削除中にエラーが発生しました。")
            st.session_state.confirming_delete_user_id = None
            st.rerun()
    with col2:
        if st.button("いいえ", key=f"cancel_del_{user_id}", use_container_width=True):
            st.session_state.confirming_delete_user_id = None
            st.rerun()

def show_employee_information_page():
    st.header("従業員情報")
    st.info("あなたの会社の全従業員の情報を表示しています。")

    if st.session_state.user_position not in ["社長", "役職者"]:
        st.error("このページへのアクセス権限がありません。")
        return

    conn = get_db_connection()
    company_name = st.session_state.user_company
    query = """
    SELECT id, name, position, employee_id, created_at FROM users WHERE company = ?
    ORDER BY CASE position WHEN '社長' THEN 1 WHEN '役職者' THEN 2 ELSE 3 END, id
    """
    try:
        all_users = conn.execute(query, (company_name,)).fetchall()

        if not all_users:
            st.warning("まだ従業員が登録されていません。")
        else:
            for user in all_users:
                with st.container(border=True):
                    st.write(f"**名前:** {user['name']}")
                    st.write(f"**役職:** {user['position']}")
                    st.write(f"**従業員ID:** {user['employee_id']}")
                    st.write(f"**登録日時:** {datetime.fromisoformat(user['created_at']).strftime('%Y年%m月%d日 %H:%M')}")

                    if user['id'] != st.session_state.user_id:
                        st.divider()
                        
                        if st.button("この従業員を削除", key=f"delete_{user['id']}", use_container_width=True, type="primary"):
                            st.session_state.confirming_delete_user_id = user['id']
                            st.rerun()

                        if st.session_state.get('confirming_delete_user_id') == user['id']:
                            confirm_delete_user_dialog(user['id'], user['name'])
                
                st.write("")

    except Exception as e:
        st.error(f"従業員情報の読み込み中にエラーが発生しました: {e}")
    finally:
        conn.close()
        
def show_user_registration_page():
    st.header("ユーザー登録")
    st.info("あなたの会社に新しいユーザーを登録します。")

    with st.form("user_registration_form"):
        st.text_input("会社名", value=st.session_state.user_company, disabled=True)

        new_name = st.text_input("名前")
        new_position = st.radio("役職", ("役職者", "社員", "バイト"), horizontal=True)
        new_employee_id = st.text_input("従業員ID")

        st.markdown("---")
        st.markdown("パスワードは、大文字、小文字、数字を含む8文字以上で設定してください。")
        new_password = st.text_input("初期パスワード", type="password")
        confirm_password = st.text_input("初期パスワード（確認用）", type="password")

        submitted = st.form_submit_button("この内容で登録する")

        if submitted:
            password_errors = validate_password(new_password)
            if not (new_name and new_employee_id and new_password):
                st.warning("名前、従業員ID、パスワードは必須項目です。")
            elif not new_employee_id.isdigit():
                st.error("従業員IDは数字で入力してください。")
            elif new_password != confirm_password:
                st.error("パスワードが一致しません。")
            elif password_errors:
                error_message = "パスワードは以下の要件を満たす必要があります：\n" + "\n".join(password_errors)
                st.error(error_message)
            else:
                company_name_from_session = st.session_state.user_company
                if register_user(new_name, new_employee_id, new_password, company_name_from_session, new_position):
                    st.success(f"ユーザー「{new_name}」さんを登録しました。")
                    py_time.sleep(2)
                    st.rerun()
                else:
                    st.error("その従業員IDは既に使用されています。")

def get_work_hours_data(start_date, end_date):
    """指定された期間の実働時間データを取得する"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    work_data = {}
    current_date = start_date
    while current_date <= end_date:
        work_data[current_date] = 0
        current_date += timedelta(days=1)

    query = "SELECT work_date, clock_in, clock_out, id FROM attendance WHERE user_id = ? AND work_date BETWEEN ? AND ?"
    attendances = conn.execute(query, (st.session_state.user_id, start_date.isoformat(), end_date.isoformat())).fetchall()

    for att in attendances:
        if att['clock_in'] and att['clock_out']:
            clock_in_dt = datetime.fromisoformat(att['clock_in'])
            clock_out_dt = datetime.fromisoformat(att['clock_out'])
            total_seconds = (clock_out_dt - clock_in_dt).total_seconds()
            
            breaks_query = "SELECT break_start, break_end FROM breaks WHERE attendance_id = ?"
            breaks = conn.execute(breaks_query, (att['id'],)).fetchall()
            break_seconds = 0
            for br in breaks:
                if br['break_start'] and br['break_end']:
                    break_seconds += (datetime.fromisoformat(br['break_end']) - datetime.fromisoformat(br['break_start'])).total_seconds()
            
            # ★★★ 修正点: 計算を「分」単位で行う ★★★
            actual_work_minutes = round((total_seconds - break_seconds) / 60)
            
            work_date = date.fromisoformat(att['work_date'])
            if actual_work_minutes > 0:
                work_data[work_date] = actual_work_minutes
    conn.close()
    return work_data

def show_work_status_page():
    st.header("出勤状況")
    
    # --- 上部の月間サマリー表示 ---
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
    first_day_month = selected_month.replace(day=1)
    last_day_month = (first_day_month + relativedelta(months=1)) - timedelta(days=1)

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    shifts_records = conn.execute("SELECT date(start_datetime) as work_date, start_datetime, end_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) BETWEEN ? AND ?", (st.session_state.user_id, first_day_month.isoformat(), last_day_month.isoformat())).fetchall()
    shifts_dict = {row['work_date']: dict(row) for row in shifts_records}
    attendances = conn.execute("SELECT id, work_date, clock_in, clock_out FROM attendance WHERE user_id = ? AND work_date BETWEEN ? AND ?", (st.session_state.user_id, first_day_month.isoformat(), last_day_month.isoformat())).fetchall()

    total_scheduled_seconds, total_actual_work_seconds, total_break_seconds, total_overtime_seconds = 0, 0, 0, 0
    for att in attendances:
        if att['clock_in'] and att['clock_out']:
            clock_in_dt, clock_out_dt = datetime.fromisoformat(att['clock_in']), datetime.fromisoformat(att['clock_out'])
            daily_break_seconds = 0
            breaks = conn.execute("SELECT break_start, break_end FROM breaks WHERE attendance_id = ?", (att['id'],)).fetchall()
            for br in breaks:
                if br['break_start'] and br['break_end']:
                    daily_break_seconds += (datetime.fromisoformat(br['break_end']) - datetime.fromisoformat(br['break_start'])).total_seconds()
            net_daily_work_seconds = (clock_out_dt - clock_in_dt).total_seconds() - daily_break_seconds
            total_actual_work_seconds += net_daily_work_seconds
            total_break_seconds += daily_break_seconds
            daily_shift = shifts_dict.get(att['work_date'])
            if daily_shift:
                scheduled_end_dt = datetime.fromisoformat(daily_shift['end_datetime']).replace(tzinfo=JST)
                if clock_out_dt > scheduled_end_dt:
                    total_overtime_seconds += (clock_out_dt - scheduled_end_dt).total_seconds()
    for shift in shifts_dict.values():
        total_scheduled_seconds += (datetime.fromisoformat(shift['end_datetime']) - datetime.fromisoformat(shift['start_datetime'])).total_seconds()
    conn.close()

    def format_seconds_to_hours_minutes(seconds):
        hours, remainder = divmod(int(seconds), 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}時間 {minutes:02}分"

    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("出勤予定時間", format_seconds_to_hours_minutes(total_scheduled_seconds))
    m_col2.metric("実働時間", format_seconds_to_hours_minutes(total_actual_work_seconds))
    m_col3.metric("合計休憩時間", format_seconds_to_hours_minutes(total_break_seconds))
    m_col4.metric("時間外労働時間", format_seconds_to_hours_minutes(total_overtime_seconds))
    st.divider()

    st.subheader("📊 実働時間グラフ")
    tab7, tab30, tab_year = st.tabs(["過去7日間", "当月", "当年"])

    with tab7:
        today = date.today()
        start_of_week = today - timedelta(days=(today.weekday() + 1) % 7)
        end_of_week = start_of_week + timedelta(days=6)
        weekly_data = get_work_hours_data(start_of_week, end_of_week)
        if any(v > 0 for v in weekly_data.values()):
            weekday_jp = ["月", "火", "水", "木", "金", "土", "日"]
            labels = [f"{d.day}日({weekday_jp[d.weekday()]})" for d in weekly_data.keys()]
            values = list(weekly_data.values())
            fig, ax = plt.subplots()
            ax.bar(labels, values)
            ax.set_ylabel('実働時間 (分)')
            ax.tick_params(axis='x', rotation=90)
            max_val = max(values) if values else 0
            if max_val < 60: interval = 5
            elif max_val < 600: interval = 60
            elif max_val < 6000: interval = 300
            else: interval = 1500
            ax.yaxis.set_major_locator(plt.MultipleLocator(interval))
            plt.tight_layout()
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        else:
            st.info("この期間のデータはありません。")

    with tab30:
        today = date.today()
        start_of_month = today.replace(day=1)
        end_of_month = (start_of_month + relativedelta(months=1)) - timedelta(days=1)
        monthly_data = get_work_hours_data(start_of_month, end_of_month)
        if any(v > 0 for v in monthly_data.values()):
            labels = [f"{d.day}日" for d in monthly_data.keys()]
            values = list(monthly_data.values())
            fig, ax = plt.subplots()
            ax.bar(labels, values)
            ax.set_ylabel('実働時間 (分)')
            ax.tick_params(axis='x', rotation=90)
            max_val = max(values) if values else 0
            if max_val < 60: interval = 5
            elif max_val < 600: interval = 60
            elif max_val < 6000: interval = 300
            else: interval = 1500
            ax.yaxis.set_major_locator(plt.MultipleLocator(interval))
            plt.tight_layout()
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        else:
            st.info("この期間のデータはありません。")

    with tab_year:
        today = date.today()
        start_of_year = today.replace(month=1, day=1)
        end_of_year = today.replace(month=12, day=31)
        yearly_data = get_work_hours_data(start_of_year, end_of_year)
        
        if any(v > 0 for v in yearly_data.values()):
            monthly_totals_dict = {i: 0 for i in range(1, 13)}
            for day, minutes in yearly_data.items():
                if minutes > 0:
                    monthly_totals_dict[day.month] += minutes
            
            labels = [f"{m}月" for m in monthly_totals_dict.keys()]
            values = list(monthly_totals_dict.values())

            fig, ax = plt.subplots()
            ax.bar(labels, values)
            ax.set_ylabel('実働時間 (分)')
            ax.tick_params(axis='x', rotation=90)
            
            max_val = max(values) if values else 0
            if max_val < 60: interval = 5
            elif max_val < 600: interval = 60
            elif max_val < 6000: interval = 300
            else: interval = 1500
            ax.yaxis.set_major_locator(plt.MultipleLocator(interval))
            
            plt.tight_layout()
            st.pyplot(fig, use_container_width=True)
            plt.close(fig)
        else:
            st.info("この期間のデータはありません。")
            
def record_clock_in():
    conn = get_db_connection()
    now = get_jst_now()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO attendance (user_id, work_date, clock_in) VALUES (?, ?, ?)', (st.session_state.user_id, now.date().isoformat(), now.isoformat()))
    conn.commit()
    st.session_state.attendance_id = cursor.lastrowid
    st.session_state.work_status = "working"
    conn.close()
    add_broadcast_message(f"✅ {st.session_state.user_name}さん、出勤しました。（{now.strftime('%H:%M')}）", st.session_state.user_company)

def record_clock_out():
    conn = get_db_connection()
    now = get_jst_now()
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
    add_broadcast_message(f"🌙 {st.session_state.user_name}さん、退勤しました。（{now.strftime('%H:%M')}）", st.session_state.user_company)
    if total_work_seconds > 8 * 3600 and total_break_seconds < 60 * 60:
        add_message(st.session_state.user_id, "⚠️ **警告:** 8時間以上の勤務に対し、休憩が60分未満です。法律に基づき、適切な休憩時間を確保してください。")
    elif total_work_seconds > 6 * 3600 and total_break_seconds < 45 * 60:
        add_message(st.session_state.user_id, "⚠️ **警告:** 6時間以上の勤務に対し、休憩が45分未満です。法律に基づき、適切な休憩時間を確保してください。")
    st.session_state.work_status = "finished"

def record_break_start():
    conn = get_db_connection()
    now = get_jst_now()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO breaks (attendance_id, break_start) VALUES (?, ?)', (st.session_state.attendance_id, now.isoformat()))
    conn.commit()
    st.session_state.break_id = cursor.lastrowid
    st.session_state.work_status = "on_break"
    conn.close()

def record_break_end():
    conn = get_db_connection()
    now = get_jst_now()
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

        if att is None:
            st.toast("勤怠記録が見つかりませんでした。状態をリセットします。")
            st.session_state.work_status = "not_started"
            st.session_state.attendance_id = None
            conn.close()
            py_time.sleep(1)
            st.rerun()
            return

        breaks = conn.execute('SELECT * FROM breaks WHERE attendance_id = ?', (st.session_state.attendance_id,)).fetchall()
        today_str = get_jst_now().date().isoformat()
        shift = conn.execute(
            "SELECT start_datetime, end_datetime FROM shifts WHERE user_id = ? AND date(start_datetime) = ?",
            (st.session_state.user_id, today_str)
        ).fetchone()
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
                now = get_jst_now()

                if st.session_state.last_break_reminder_date != today_str:
                    if now.astimezone(JST) >= reminder_time.astimezone(JST) and now.astimezone(JST) < break_start_estimate_dt.astimezone(JST):
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
                    total_break_seconds += (get_jst_now() - datetime.fromisoformat(br['break_start'])).total_seconds()
            break_hours, rem = divmod(total_break_seconds, 3600)
            break_minutes, _ = divmod(rem, 60)
            st.metric("現在の休憩時間", f"{int(break_hours):02}:{int(break_minutes):02}")

        st.divider()
        if att['clock_in']:
            if att['clock_out']:
                clock_out_time = datetime.fromisoformat(att['clock_out'])
                total_work_seconds = (clock_out_time - datetime.fromisoformat(att['clock_in'])).total_seconds()
            else:
                total_work_seconds = (get_jst_now() - datetime.fromisoformat(att['clock_in'])).total_seconds()

            net_work_seconds = total_work_seconds - total_break_seconds
            work_hours, rem = divmod(net_work_seconds, 3600)
            work_minutes, _ = divmod(rem, 60)
            st.metric("総勤務時間", f"{int(work_hours):02}:{int(work_minutes):02}")
        else:
            st.metric("総勤務時間", "00:00")

        st.divider()

        if shift and not att['clock_out']:

            naive_end_dt = datetime.fromisoformat(shift['end_datetime'])
            end_dt = naive_end_dt.replace(tzinfo=JST)

            reminder_time = end_dt + timedelta(minutes=15)
            now = get_jst_now()

            if now > reminder_time and st.session_state.get('last_clock_out_reminder_date') != today_str:
                add_message(st.session_state.user_id, "⏰ 退勤予定時刻を15分過ぎています。速やかに退勤してください。")
                st.session_state.last_clock_out_reminder_date = today_str

def handle_page_change():
    if st.session_state.navigation_choice != 'ダイレクトメッセージ':
        st.session_state.dm_selected_user_id = None
                
def main():
    st.set_page_config(layout="wide")

    init_db()
    init_session_state()

    if not st.session_state.get('logged_in'):
        show_login_register_page()
    
    else:
        if st.session_state.get('user_id'):
            get_today_attendance_status(st.session_state.user_id)

        conn = get_db_connection()
        current_user_id = st.session_state.user_id
        broadcast_unread_count = conn.execute("SELECT COUNT(*) FROM messages WHERE user_id = ? AND is_read = 0 AND message_type IN ('BROADCAST', 'SYSTEM')", (current_user_id,)).fetchone()[0]
        dm_unread_count_row = conn.execute("SELECT COUNT(*) FROM messages WHERE user_id = ? AND is_read = 0 AND message_type = 'DIRECT'", (current_user_id,)).fetchone()
        dm_unread_count = dm_unread_count_row[0] if dm_unread_count_row else 0
        unread_dm_senders = conn.execute("SELECT DISTINCT u.id, u.name FROM messages m JOIN users u ON m.sender_id = u.id WHERE m.user_id = ? AND m.is_read = 0 AND m.message_type = 'DIRECT'", (current_user_id,)).fetchall()
        conn.close()
    
        if unread_dm_senders:
            with st.container(border=True):
                st.info("🔔 新着メッセージがあります！")
                for sender in unread_dm_senders:
                    if st.button(f"📩 **{sender['name']}さん**から新しいメッセージが届いています。", key=f"dm_notification_{sender['id']}", use_container_width=True):
                        st.session_state.dm_selected_user_id = sender['id']
                        st.info("下の「DM」タブを開いてください。")

        ordered_page_keys = ["タイムカード", "シフト管理", "シフト表", "出勤状況", "全体メッセージ", "ダイレクトメッセージ", "ユーザー情報"]
        if st.session_state.user_position in ["社長", "役職者"]:
            ordered_page_keys.insert(1, "従業員情報")
            ordered_page_keys.insert(1, "ユーザー登録")

        page_definitions = {
            "タイムカード": {"icon": "⏰", "func": show_timecard_page},
            "シフト管理": {"icon": "🗓️", "func": show_shift_management_page},
            "シフト表": {"icon": "📊", "func": show_shift_table_page},
            "出勤状況": {"icon": "📈", "func": show_work_status_page},
            "全体メッセージ": {"icon": "📢", "unread": broadcast_unread_count, "func": show_messages_page},
            "ダイレクトメッセージ": {"icon": "💬", "unread": dm_unread_count, "func": show_direct_message_page},
            "ユーザー情報": {"icon": "👤", "func": show_user_info_page},
            "従業員情報": {"icon": "👥", "func": show_employee_information_page},
            "ユーザー登録": {"icon": "📝", "func": show_user_registration_page}
        }

        tab_titles = []
        for key in ordered_page_keys:
            info = page_definitions.get(key)
            if info:
                label = f"{info['icon']} {key}"
                if info.get('unread', 0) > 0:
                    label += " 🔴"
                tab_titles.append(label)

        tabs = st.tabs(tab_titles)

        for i, tab in enumerate(tabs):
            with tab:
                page_key_to_render = ordered_page_keys[i]
                render_function = page_definitions[page_key_to_render]["func"]
                render_function()

        with st.sidebar:
            st.title(" ")
            st.info(f"**名前:** {st.session_state.user_name}\n\n**従業員ID:** {get_user_employee_id(st.session_state.user_id)}")
            if st.button("ログアウト", use_container_width=True):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()

if __name__ == "__main__":
    main()

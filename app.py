"""
UsChats - Simple WeChat Chat Exporter
Created by RTB Ruhan
A clean, simple tool to export your WeChat chats
"""

import os
import sys
import json
import sqlite3
import subprocess
import threading
import webbrowser
import time
import re
import signal
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file

# Import our decryption module
try:
    from wx_decrypt import (
        get_wechat_info, is_wechat_running, verify_key,
        find_databases, get_wechat_data_dir, auto_decrypt,
        decrypt_database, merge_databases, find_wxid_folders
    )
    DECRYPT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Decryption module not available: {e}")
    DECRYPT_AVAILABLE = False

# Heartbeat tracking
last_heartbeat = time.time()
HEARTBEAT_TIMEOUT = 10  # Seconds without heartbeat before shutdown

# Paths
SCRIPT_DIR = Path(__file__).parent.absolute()
PARENT_DIR = SCRIPT_DIR.parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
EXPORTS_DIR = SCRIPT_DIR / "exports"
MEDIA_DIR = None  # Will be set based on database location

# Known database locations to search (generic patterns)
KNOWN_DB_LOCATIONS = [
    # These are searched dynamically - no hardcoded user paths
]

app = Flask(__name__, static_folder='static', template_folder='templates')

# Ensure directories exist
EXPORTS_DIR.mkdir(exist_ok=True)
(EXPORTS_DIR / "txt").mkdir(exist_ok=True)
(EXPORTS_DIR / "json").mkdir(exist_ok=True)
(EXPORTS_DIR / "html").mkdir(exist_ok=True)


def load_config():
    """Load configuration from file"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        "setup_complete": False,
        "db_path": "",
        "wechat_exe_path": "",
    }


def save_config(config):
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def find_existing_database():
    """Search for existing database files"""
    for path in KNOWN_DB_LOCATIONS:
        if path.exists():
            return str(path)
    
    # Search common wxdump_work locations relative to this tool
    wxdump_dirs = [
        SCRIPT_DIR / "data",  # UsChats/data/
        PARENT_DIR / "wxdump_work",  # Sibling folder
        Path.home() / "Documents" / "WeChat Files",  # Common WeChat data location
    ]
    
    for base_dir in wxdump_dirs:
        if base_dir.exists():
            for item in base_dir.rglob("merge_all.db"):
                return str(item)
    
    return None


def find_media_for_message(contact_id, msg_time, msg_type):
    """Find media file for a message based on timestamp"""
    media_dir = get_media_dir()
    if not media_dir or not msg_time:
        return None
    
    # Format: 2025-03-07_18-17-09_0_2793697400614402810.wav
    # Match just the date and hour-minute part
    date_prefix = msg_time.strftime('%Y-%m-%d_%H-%M')
    
    if msg_type == 34:  # Audio
        audio_dir = media_dir / 'audio' / contact_id
        if audio_dir.exists():
            for f in audio_dir.iterdir():
                if f.name.startswith(date_prefix) and f.suffix.lower() in ['.wav', '.mp3']:
                    return f'audio/{contact_id}/{f.name}'
    
    elif msg_type == 43:  # Video
        # Videos are in video/FileStorage/Video/YYYY-MM/
        month_folder = msg_time.strftime('%Y-%m')
        video_month_dir = media_dir / 'video' / 'FileStorage' / 'Video' / month_folder
        
        if video_month_dir.exists():
            for f in video_month_dir.iterdir():
                if f.suffix.lower() == '.mp4':
                    return f'video/FileStorage/Video/{month_folder}/{f.name}'
    
    elif msg_type == 3:  # Image
        # Images are in img/FileStorage/MsgAttach/<hash>/Image/
        img_base = media_dir / 'img' / 'FileStorage' / 'MsgAttach'
        if img_base.exists():
            for hash_dir in img_base.iterdir():
                if hash_dir.is_dir():
                    img_dir = hash_dir / 'Image'
                    if img_dir.exists():
                        for f in img_dir.iterdir():
                            if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif']:
                                # Can't easily match by timestamp, return path
                                rel = f'img/FileStorage/MsgAttach/{hash_dir.name}/Image/{f.name}'
                                return rel
    
    return None


def get_media_dir():
    """Get the media directory based on database location"""
    config = load_config()
    db_path = config.get('db_path', '')
    
    if not db_path:
        return None
    
    db_dir = Path(db_path).parent
    
    if (db_dir / 'audio').exists():
        return db_dir
    
    if (db_dir.parent / 'audio').exists():
        return db_dir.parent
    
    return db_dir


def get_my_wxid():
    """Get the user's wxid from various sources"""
    config = load_config()
    
    # From our config
    if config.get('wxid'):
        return config['wxid']
    
    # From database path
    db_path = config.get('db_path', '')
    if db_path:
        wxid = extract_wxid_from_path(db_path)
        if wxid:
            return wxid
    
    # Try to find wxid from conf_auto.json near the database
    db_path = config.get('db_path', '')
    if db_path:
        db_dir = Path(db_path).parent
        old_config_path = db_dir.parent / "conf_auto.json"  # wxdump_work/conf_auto.json
        if not old_config_path.exists():
            old_config_path = db_dir / "conf_auto.json"  # Same folder as db
    else:
        old_config_path = None
    
    if old_config_path and old_config_path.exists():
        try:
            with open(old_config_path, 'r', encoding='utf-8') as f:
                old_config = json.load(f)
                # Get from auto_setting
                last = old_config.get('auto_setting', {}).get('last', '')
                if last and last.startswith('wxid_'):
                    return last
                # Or from keys
                for key in old_config.keys():
                    if key.startswith('wxid_'):
                        return key
        except:
            pass
    
    return ''


def get_db_path():
    """Get current database path"""
    config = load_config()
    db_path = config.get('db_path', '')
    
    if db_path and Path(db_path).exists():
        # Try to extract wxid from path if not set
        if not config.get('wxid'):
            wxid = extract_wxid_from_path(db_path)
            if wxid:
                config['wxid'] = wxid
                save_config(config)
        return db_path
    
    # Try to find existing database
    existing = find_existing_database()
    if existing:
        config['db_path'] = existing
        # Extract wxid from path
        wxid = extract_wxid_from_path(existing)
        if wxid:
            config['wxid'] = wxid
        save_config(config)
        return existing
    
    return None


def extract_wxid_from_path(path):
    """Extract wxid from database path"""
    path_str = str(path)
    match = re.search(r'(wxid_[a-zA-Z0-9_]+)', path_str)
    if match:
        return match.group(1)
    return None


def get_contacts(db_path):
    """Get contacts from database"""
    contacts = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get unique talkers with message counts
        cursor.execute("""
            SELECT StrTalker, COUNT(*) as msg_count
            FROM MSG 
            GROUP BY StrTalker
            ORDER BY msg_count DESC
        """)
        
        rows = cursor.fetchall()
        
        # Try to get nicknames from Contact table if it exists
        nicknames = {}
        try:
            cursor.execute("SELECT UserName, NickName FROM Contact WHERE NickName != ''")
            for row in cursor.fetchall():
                nicknames[row[0]] = row[1]
        except:
            pass
        
        for row in rows:
            talker = row[0]
            if not talker:
                continue
                
            contacts.append({
                'id': talker,
                'nickname': nicknames.get(talker, talker),
                'type': 'group' if '@chatroom' in talker else 'user',
                'message_count': row[1]
            })
        
        conn.close()
    except Exception as e:
        print(f"Error getting contacts: {e}")
    
    return contacts


def get_messages(db_path, contact_id, limit=500, offset=0):
    """Get messages for a contact with sender info for groups"""
    messages = []
    senders = {}  # wxid -> nickname mapping
    
    # Get user's own wxid
    my_wxid = get_my_wxid()
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        is_group = '@chatroom' in contact_id
        
        # Get messages with BytesExtra for group sender info
        cursor.execute("""
            SELECT StrTalker, StrContent, Type, IsSender, CreateTime, BytesExtra
            FROM MSG
            WHERE StrTalker = ?
            ORDER BY CreateTime DESC
            LIMIT ? OFFSET ?
        """, (contact_id, limit, offset))
        
        rows = cursor.fetchall()
        sender_wxids = set()
        temp_messages = []
        
        for row in rows:
            msg_time = datetime.fromtimestamp(row[4]) if row[4] else None
            content = row[1] or ''
            msg_type = row[2]
            is_sender = row[3] == 1
            sender_wxid = None
            
            # Extract sender for group chats from BytesExtra
            if is_group:
                if row[5]:
                    try:
                        extra = row[5]
                        if isinstance(extra, bytes):
                            # Look for wxid pattern in bytes
                            match = re.search(b'(wxid_[a-zA-Z0-9_]+)', extra)
                            if match:
                                sender_wxid = match.group(1).decode('utf-8', errors='ignore')
                                
                                # Check if this is the user's own message
                                if sender_wxid == my_wxid:
                                    is_sender = True
                                    sender_wxid = None  # Don't show name for own messages
                                else:
                                    sender_wxids.add(sender_wxid)
                    except:
                        pass
                
                # Also try other ID patterns if no wxid found
                if not sender_wxid and not is_sender and row[5]:
                    try:
                        extra = row[5]
                        if isinstance(extra, bytes):
                            # Look for username patterns
                            matches = re.findall(b'[\x00-\x1f]([a-zA-Z][a-zA-Z0-9_]{5,19})[\x00-\x1f]', extra)
                            for m in matches:
                                try:
                                    potential = m.decode('utf-8')
                                    if potential != contact_id and '@' not in potential and potential != my_wxid:
                                        sender_wxid = potential
                                        sender_wxids.add(sender_wxid)
                                        break
                                except:
                                    pass
                    except:
                        pass
            
            # Look for media file path
            media_path = None
            if msg_type in [3, 34, 43]:  # Image, Voice or Video
                media_path = find_media_for_message(contact_id, msg_time, msg_type)
            
            temp_messages.append({
                'talker': row[0],
                'content': content,
                'type': msg_type,
                'is_sender': is_sender,
                'time': msg_time.strftime('%Y-%m-%d %H:%M:%S') if msg_time else '',
                'sender': sender_wxid,
                'media_path': media_path,
            })
        
        # Get nicknames for all sender wxids
        if sender_wxids:
            try:
                placeholders = ','.join('?' * len(sender_wxids))
                cursor.execute(f"""
                    SELECT UserName, NickName FROM Contact 
                    WHERE UserName IN ({placeholders})
                """, list(sender_wxids))
                for r in cursor.fetchall():
                    if r[1]:  # Has nickname
                        senders[r[0]] = r[1]
            except Exception as e:
                print(f"Error getting sender names: {e}")
        
        messages = temp_messages
        conn.close()
        messages.reverse()
    except Exception as e:
        print(f"Error getting messages: {e}")
    
    return messages, senders


def get_type_name(type_code):
    """Get message type name"""
    types = {
        1: 'text', 3: 'image', 34: 'voice', 43: 'video',
        47: 'emoji', 49: 'link/file', 10000: 'system', 10002: 'revoked'
    }
    return types.get(type_code, 'other')


def format_message_for_export(content, msg_type):
    """Format message content for export, handling media placeholders"""
    if not content:
        return None
    
    # Voice message
    if msg_type == 34:
        if '翻译结果：' in content:
            match = re.search(r'翻译结果：(.+)', content)
            if match:
                return f"[Voice message: {match.group(1).strip()}]"
        return "[Here was a voice message]"
    
    # Image
    if msg_type == 3:
        return "[Here was an image]"
    
    # Video
    if msg_type == 43:
        return "[Here was a video]"
    
    # Sticker/Emoji
    if msg_type == 47:
        return "[Sticker/Emoji]"
    
    # System message
    if msg_type == 10000:
        clean = re.sub(r'<[^>]+>', '', content).strip()
        return f"[System: {clean}]" if clean else None
    
    # Revoked
    if msg_type == 10002:
        return "[Message was recalled]"
    
    # VOIP/Call
    if '<voipmsg' in content or 'VoIPBubbleMsg' in content:
        if 'Line busy' in content or 'not received' in content:
            return "[Missed call]"
        return "[Voice/Video call]"
    
    # Link/File (type 49)
    if msg_type == 49:
        # Try to extract title
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
        if title_match:
            title = title_match.group(1)
            # Check for URL
            url_match = re.search(r'<url>([^<]+)</url>', content, re.IGNORECASE)
            if url_match:
                return f"[Link: {title}] {url_match.group(1)}"
            return f"[Link/File: {title}]"
        return "[Here was a link or file]"
    
    # Location
    if msg_type == 48:
        return "[Location shared]"
    
    # Business card
    if msg_type == 42:
        return "[Contact card]"
    
    # XML content we couldn't parse
    if content.startswith('<') and '</' in content:
        title_match = re.search(r'<title>([^<]+)</title>', content)
        if title_match:
            return f"[{title_match.group(1)}]"
        return "[Special message]"
    
    return content.strip() if content.strip() else None


def generate_export_content(db_path, contact_id, contact_name, format_type):
    """Generate export content for different formats"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    my_wxid = get_my_wxid()
    is_group = '@chatroom' in contact_id
    
    # Get all messages
    cursor.execute("""
        SELECT StrContent, Type, IsSender, CreateTime, BytesExtra
        FROM MSG
        WHERE StrTalker = ?
        ORDER BY CreateTime ASC
    """, (contact_id,))
    
    rows = cursor.fetchall()
    
    # Get sender nicknames for groups
    senders = {}
    if is_group:
        sender_wxids = set()
        for row in rows:
            if row[4]:  # BytesExtra
                try:
                    match = re.search(b'(wxid_[a-zA-Z0-9_]+)', row[4])
                    if match:
                        wxid = match.group(1).decode('utf-8', errors='ignore')
                        if wxid != my_wxid:
                            sender_wxids.add(wxid)
                except:
                    pass
        
        if sender_wxids:
            placeholders = ','.join('?' * len(sender_wxids))
            cursor.execute(f"SELECT UserName, NickName FROM Contact WHERE UserName IN ({placeholders})", list(sender_wxids))
            for r in cursor.fetchall():
                if r[1]:
                    senders[r[0]] = r[1]
    
    conn.close()
    
    # Process messages
    messages = []
    for row in rows:
        content = row[0] or ''
        msg_type = row[1]
        is_sender = row[2] == 1
        msg_time = datetime.fromtimestamp(row[3]) if row[3] else None
        sender_name = None
        
        # Check if it's our message in group
        if is_group and row[4]:
            try:
                match = re.search(b'(wxid_[a-zA-Z0-9_]+)', row[4])
                if match:
                    wxid = match.group(1).decode('utf-8', errors='ignore')
                    if wxid == my_wxid:
                        is_sender = True
                        sender_name = "You"
                    else:
                        sender_name = senders.get(wxid, wxid)
            except:
                pass
        
        if is_sender:
            sender_name = "You"
        elif not is_group:
            sender_name = contact_name
        
        formatted = format_message_for_export(content, msg_type)
        if formatted:
            messages.append({
                'time': msg_time.strftime('%Y-%m-%d %H:%M:%S') if msg_time else '',
                'sender': sender_name or 'Unknown',
                'content': formatted,
                'type': get_type_name(msg_type)
            })
    
    # Generate output based on format
    if format_type == 'json':
        return json.dumps(messages, ensure_ascii=False, indent=2)
    
    elif format_type == 'csv':
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Time', 'Sender', 'Message', 'Type'])
        for msg in messages:
            writer.writerow([msg['time'], msg['sender'], msg['content'], msg['type']])
        return output.getvalue()
    
    elif format_type == 'html':
        return generate_html_export(messages, contact_name)
    
    else:  # txt
        lines = [f"Chat Export: {contact_name}", f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "=" * 50, ""]
        for msg in messages:
            lines.append(f"{msg['sender']} [{msg['time']}]")
            lines.append(f"  {msg['content']}")
            lines.append("")
        return '\n'.join(lines)


def generate_html_export(messages, contact_name):
    """Generate HTML export with WhatsApp style"""
    msgs_html = []
    current_date = None
    
    for msg in messages:
        # Date separator
        if msg['time']:
            date = msg['time'].split(' ')[0]
            if date != current_date:
                current_date = date
                msgs_html.append(f'<div class="date-sep">{date}</div>')
        
        side = 'sent' if msg['sender'] == 'You' else 'received'
        sender_html = f'<div class="sender">{msg["sender"]}</div>' if msg['sender'] != 'You' else ''
        content = msg['content'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        time = msg['time'].split(' ')[1] if msg['time'] else ''
        
        msgs_html.append(f'''
        <div class="msg {side}">
            <div class="bubble">
                {sender_html}
                <div class="text">{content}</div>
                <div class="time">{time}</div>
            </div>
        </div>''')
    
    return f'''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Chat: {contact_name}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', sans-serif; background: #0b141a; min-height: 100vh; }}
.header {{ background: #1f2c34; padding: 16px 24px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
.header h1 {{ color: #e9edef; font-size: 1.2rem; }}
.header p {{ color: #8696a0; font-size: 0.85rem; margin-top: 4px; }}
.chat {{ max-width: 900px; margin: 0 auto; padding: 20px; }}
.date-sep {{ text-align: center; margin: 20px 0; }}
.date-sep {{ background: #182229; color: #8696a0; padding: 6px 16px; border-radius: 8px; font-size: 0.8rem; display: inline-block; }}
.msg {{ display: flex; margin-bottom: 4px; }}
.msg.sent {{ justify-content: flex-end; }}
.msg.received {{ justify-content: flex-start; }}
.bubble {{ max-width: 65%; padding: 8px 12px; border-radius: 8px; }}
.sent .bubble {{ background: #005c4b; border-top-right-radius: 0; }}
.received .bubble {{ background: #1f2c34; border-top-left-radius: 0; }}
.sender {{ color: #00a884; font-size: 0.75rem; font-weight: 500; margin-bottom: 2px; }}
.text {{ color: #e9edef; font-size: 0.9rem; line-height: 1.4; white-space: pre-wrap; }}
.time {{ color: rgba(255,255,255,0.5); font-size: 0.65rem; text-align: right; margin-top: 4px; }}
.footer {{ text-align: center; padding: 40px; color: #667781; }}
</style>
</head><body>
<div class="header">
<h1>💬 {contact_name}</h1>
<p>Exported on {datetime.now().strftime('%Y-%m-%d %H:%M')} • {len(messages)} messages</p>
</div>
<div class="chat">{''.join(msgs_html)}</div>
<div class="footer">Exported with UsChats by RTB Ruhan</div>
</body></html>'''


def export_chat_txt(db_path, contact_id, contact_name):
    """Export chat to TXT"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT StrContent, Type, IsSender, CreateTime
        FROM MSG
        WHERE StrTalker = ? AND Type IN (1, 49, 34)
        ORDER BY CreateTime ASC
    """, (contact_id,))
    
    lines = []
    lines.append(f"Chat Export: {contact_name}")
    lines.append(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 50)
    lines.append("")
    
    for row in cursor.fetchall():
        content = row[0] or ''
        msg_type = row[1]
        is_sender = row[2] == 1
        msg_time = datetime.fromtimestamp(row[3]) if row[3] else None
        
        sender = "You" if is_sender else contact_name
        
        # Voice transcription
        if msg_type == 34 and '翻译结果：' in content:
            match = re.search(r'翻译结果：(.+)', content)
            if match:
                content = f"[Voice] {match.group(1).strip()}"
        
        if content.strip():
            time_str = msg_time.strftime('%Y-%m-%d %H:%M') if msg_time else ''
            lines.append(f"{sender} [{time_str}]")
            lines.append(f"> {content}")
            lines.append("")
    
    conn.close()
    
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', contact_name)
    filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    filepath = EXPORTS_DIR / "txt" / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return str(filepath), filename


def export_chat_json(db_path, contact_id, contact_name):
    """Export chat to JSON"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT StrTalker, StrContent, Type, IsSender, CreateTime
        FROM MSG
        WHERE StrTalker = ?
        ORDER BY CreateTime ASC
    """, (contact_id,))
    
    messages = []
    for row in cursor.fetchall():
        msg_time = datetime.fromtimestamp(row[4]) if row[4] else None
        messages.append({
            'talker': row[0],
            'content': row[1] or '',
            'type': row[2],
            'type_name': get_type_name(row[2]),
            'is_sender': row[3] == 1,
            'time': msg_time.strftime('%Y-%m-%d %H:%M:%S') if msg_time else '',
        })
    
    conn.close()
    
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', contact_name)
    filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = EXPORTS_DIR / "json" / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    
    return str(filepath), filename


def export_chat_html(db_path, contact_id, contact_name):
    """Export chat to HTML with WhatsApp-style design"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    is_group = '@chatroom' in contact_id
    
    cursor.execute("""
        SELECT StrContent, Type, IsSender, CreateTime, BytesExtra
        FROM MSG
        WHERE StrTalker = ? AND Type IN (1, 49, 34, 3, 43)
        ORDER BY CreateTime ASC
    """, (contact_id,))
    
    messages_html = []
    current_date = None
    senders = {}
    sender_wxids = set()
    
    rows = cursor.fetchall()
    
    # First pass: collect sender wxids for group chats
    if is_group:
        for row in rows:
            content = row[0] or ''
            if not row[2] and ':\n' in content:  # Not sent by me
                parts = content.split(':\n', 1)
                if len(parts) == 2 and len(parts[0]) < 50:
                    sender_wxids.add(parts[0])
        
        # Get nicknames
        if sender_wxids:
            try:
                placeholders = ','.join('?' * len(sender_wxids))
                cursor.execute(f"SELECT UserName, NickName FROM Contact WHERE UserName IN ({placeholders})", list(sender_wxids))
                for r in cursor.fetchall():
                    senders[r[0]] = r[1]
            except:
                pass
    
    for row in rows:
        content = row[0] or ''
        msg_type = row[1]
        is_sender = row[2] == 1
        msg_time = datetime.fromtimestamp(row[3]) if row[3] else None
        sender_name = None
        
        # Extract sender for group chats
        if is_group and not is_sender and ':\n' in content:
            parts = content.split(':\n', 1)
            if len(parts) == 2 and len(parts[0]) < 50:
                sender_wxid = parts[0]
                sender_name = senders.get(sender_wxid, sender_wxid)
                content = parts[1]
        
        # Date separator
        if msg_time:
            msg_date = msg_time.strftime('%B %d, %Y')
            if msg_date != current_date:
                current_date = msg_date
                messages_html.append(f'<div class="date-separator">{msg_date}</div>')
        
        # Format content
        if msg_type == 34:
            if '翻译结果：' in content:
                match = re.search(r'翻译结果：(.+)', content)
                if match:
                    content = f"🎤 {match.group(1).strip()}"
                else:
                    content = "🎤 [Voice]"
            else:
                content = "🎤 [Voice]"
        elif msg_type == 3:
            content = "🖼️ [Image]"
        elif msg_type == 43:
            content = "🎬 [Video]"
        elif msg_type == 49:
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.IGNORECASE)
            if title_match:
                content = f"📎 {title_match.group(1)}"
            else:
                content = "📎 [Link/File]"
        elif content.startswith('<voipmsg') or 'VoIPBubbleMsg' in content:
            content = "📞 [Call]"
        
        if content.strip() and not content.startswith('<'):
            time_str = msg_time.strftime('%I:%M %p') if msg_time else ''
            side = 'sent' if is_sender else 'received'
            
            # Escape HTML
            content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            sender_html = ''
            if sender_name and not is_sender:
                safe_sender = sender_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                sender_html = f'<div class="sender">{safe_sender}</div>'
            
            messages_html.append(f'''
            <div class="message {side}">
                <div class="bubble">
                    {sender_html}
                    <div class="text">{content}</div>
                    <div class="time">{time_str}</div>
                </div>
            </div>
            ''')
    
    conn.close()
    
    # WhatsApp-style HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat: {contact_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #0b141a;
            min-height: 100vh;
        }}
        
        .header {{
            background: #1f2c34;
            padding: 16px 24px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        
        .header h1 {{
            color: #e9edef;
            font-size: 1.2rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        
        .header p {{
            color: #8696a0;
            font-size: 0.85rem;
            margin-top: 4px;
        }}
        
        .chat {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23182229' fill-opacity='0.4'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
        }}
        
        .date-separator {{
            text-align: center;
            margin: 20px 0;
        }}
        
        .date-separator {{
            display: inline-block;
            background: #182229;
            color: #8696a0;
            padding: 6px 16px;
            border-radius: 8px;
            font-size: 0.8rem;
            margin: 16px auto;
            display: block;
            width: fit-content;
        }}
        
        .message {{
            display: flex;
            margin-bottom: 4px;
        }}
        
        .message.sent {{
            justify-content: flex-end;
        }}
        
        .message.received {{
            justify-content: flex-start;
        }}
        
        .bubble {{
            max-width: 65%;
            padding: 8px 12px;
            border-radius: 8px;
            position: relative;
        }}
        
        .sent .bubble {{
            background: #005c4b;
            border-top-right-radius: 0;
        }}
        
        .received .bubble {{
            background: #1f2c34;
            border-top-left-radius: 0;
        }}
        
        .sender {{
            color: #00a884;
            font-size: 0.75rem;
            font-weight: 500;
            margin-bottom: 2px;
        }}
        
        .text {{
            color: #e9edef;
            font-size: 0.9rem;
            line-height: 1.4;
            word-break: break-word;
        }}
        
        .time {{
            color: rgba(255,255,255,0.5);
            font-size: 0.65rem;
            text-align: right;
            margin-top: 4px;
        }}
        
        .footer {{
            text-align: center;
            padding: 40px;
            color: #667781;
            font-size: 0.85rem;
        }}
        
        .footer a {{
            color: #00a884;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>💬 {contact_name}</h1>
        <p>Exported on {datetime.now().strftime('%B %d, %Y at %I:%M %p')} • {len(messages_html)} messages</p>
    </div>
    <div class="chat">
        {''.join(messages_html)}
    </div>
    <div class="footer">
        Exported with <strong>UsChats</strong> by RTB Ruhan
    </div>
</body>
</html>'''
    
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', contact_name)
    filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    filepath = EXPORTS_DIR / "html" / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return str(filepath), filename


# ============= FLASK ROUTES =============

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    config = load_config()
    existing_db = find_existing_database()
    db_path = config.get('db_path', '') or existing_db
    my_wxid = get_my_wxid()
    
    return jsonify({
        'setup_complete': config.get('setup_complete', False),
        'db_path': db_path,
        'db_ready': db_path and Path(db_path).exists() if db_path else False,
        'existing_db_path': existing_db,
        'wechat_exe_path': config.get('wechat_exe_path', ''),
        'export_path': str(EXPORTS_DIR),
        'my_wxid': my_wxid,
        'decrypt_available': DECRYPT_AVAILABLE,
    })


@app.route('/api/wechat-info')
def api_wechat_info():
    """Get WeChat status and information"""
    if not DECRYPT_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Decryption module not available. Install pycryptodome and psutil.'
        })
    
    try:
        info = get_wechat_info()
        return jsonify({
            'success': True,
            'running': info.get('running', False),
            'version': info.get('version'),
            'supported_version': info.get('supported_version', False),
            'data_dir': info.get('data_dir'),
            'wxids': info.get('wxids', []),
            'pids': info.get('pids', [])
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/auto-decrypt', methods=['POST'])
def api_auto_decrypt():
    """Fully automatic decryption - one click to do everything"""
    if not DECRYPT_AVAILABLE:
        return jsonify({
            'success': False,
            'error': 'Decryption module not available. Run: pip install pycryptodome psutil'
        })
    
    try:
        result = auto_decrypt()
        
        if result['success']:
            # Update config with new database
            config = load_config()
            config['db_path'] = result['db_path']
            config['wxid'] = result['wxid']
            config['key'] = result['key']
            config['setup_complete'] = True
            save_config(config)
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e),
            'step': 'error'
        })


@app.route('/api/verify-key', methods=['POST'])
def api_verify_key():
    """Verify if a key can decrypt a database"""
    if not DECRYPT_AVAILABLE:
        return jsonify({'success': False, 'error': 'Decryption not available'})
    
    data = request.json
    key = data.get('key', '')
    wxid_path = data.get('wxid_path', '')
    
    if not key or len(key) != 64:
        return jsonify({'success': False, 'error': 'Invalid key (must be 64 hex characters)'})
    
    if not wxid_path or not Path(wxid_path).exists():
        return jsonify({'success': False, 'error': 'Invalid wxid path'})
    
    # Find a database to test with
    databases = find_databases(wxid_path)
    if not databases:
        return jsonify({'success': False, 'error': 'No databases found in wxid folder'})
    
    # Try to verify with first database
    test_db = databases[0]['db_path']
    is_valid = verify_key(key, test_db)
    
    return jsonify({
        'success': True,
        'valid': is_valid,
        'tested_db': test_db
    })


@app.route('/api/decrypt', methods=['POST'])
def api_decrypt():
    """Decrypt and merge WeChat databases"""
    if not DECRYPT_AVAILABLE:
        return jsonify({'success': False, 'error': 'Decryption not available'})
    
    data = request.json
    key = data.get('key', '')
    wxid_path = data.get('wxid_path', '')
    
    if not key or len(key) != 64:
        return jsonify({'success': False, 'error': 'Invalid key'})
    
    if not wxid_path or not Path(wxid_path).exists():
        return jsonify({'success': False, 'error': 'Invalid wxid path'})
    
    # Output directory
    output_dir = SCRIPT_DIR / "data" / Path(wxid_path).name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        success, result = decrypt_and_merge(wxid_path, key, str(output_dir))
        
        if success:
            # Update config with new database path
            config = load_config()
            config['db_path'] = result
            config['key'] = key
            config['wxid'] = Path(wxid_path).name
            config['setup_complete'] = True
            save_config(config)
            
            return jsonify({
                'success': True,
                'db_path': result,
                'message': 'Decryption complete!'
            })
        else:
            return jsonify({'success': False, 'error': result})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/find-databases', methods=['POST'])
def api_find_databases():
    """Find databases in a wxid folder"""
    if not DECRYPT_AVAILABLE:
        return jsonify({'success': False, 'error': 'Decryption not available'})
    
    data = request.json
    wxid_path = data.get('wxid_path', '')
    
    if not wxid_path or not Path(wxid_path).exists():
        return jsonify({'success': False, 'error': 'Invalid path'})
    
    databases = find_databases(wxid_path)
    return jsonify({
        'success': True,
        'count': len(databases),
        'databases': databases
    })


@app.route('/api/use-existing-db', methods=['POST'])
def api_use_existing_db():
    existing_db = find_existing_database()
    
    if not existing_db:
        return jsonify({'success': False, 'error': 'No existing database found'})
    
    config = load_config()
    config['db_path'] = existing_db
    config['setup_complete'] = True
    save_config(config)
    
    # Count contacts
    contact_count = 0
    try:
        conn = sqlite3.connect(existing_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT StrTalker) FROM Message")
        contact_count = cursor.fetchone()[0]
        conn.close()
    except:
        pass
    
    return jsonify({
        'success': True, 
        'db_path': existing_db,
        'contact_count': contact_count
    })


@app.route('/api/set-database', methods=['POST'])
def api_set_database():
    data = request.json
    db_path = data.get('db_path', '')
    
    if not db_path or not Path(db_path).exists():
        return jsonify({'success': False, 'error': 'Database file not found'})
    
    config = load_config()
    config['db_path'] = db_path
    config['setup_complete'] = True
    save_config(config)
    
    # Count contacts
    contact_count = 0
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT StrTalker) FROM Message")
        contact_count = cursor.fetchone()[0]
        conn.close()
    except:
        pass
    
    return jsonify({
        'success': True, 
        'db_path': db_path,
        'contact_count': contact_count
    })


@app.route('/api/complete-setup', methods=['POST'])
def api_complete_setup():
    data = request.json
    config = load_config()
    
    db_path = config.get('db_path', '')
    if not db_path or not Path(db_path).exists():
        return jsonify({'success': False, 'error': 'Database not configured'})
    
    config['wechat_exe_path'] = data.get('wechat_exe_path', '')
    config['setup_complete'] = True
    save_config(config)
    
    return jsonify({'success': True, 'db_path': db_path})


@app.route('/api/reset-setup', methods=['POST'])
def api_reset_setup():
    """Reset setup to allow reconfiguration"""
    config = load_config()
    config['setup_complete'] = False
    save_config(config)
    return jsonify({'success': True})


@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """Heartbeat endpoint - browser pings this to keep server alive"""
    global last_heartbeat
    last_heartbeat = time.time()
    return jsonify({'success': True})


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    """Shutdown endpoint - now disabled, using heartbeat timeout instead"""
    # Don't shutdown immediately - let heartbeat timeout handle it
    # This prevents accidental shutdowns from page navigation
    return jsonify({'success': True, 'status': 'ignored - using heartbeat timeout'})


@app.route('/api/contacts')
def api_contacts():
    db_path = get_db_path()
    
    if not db_path:
        return jsonify({'success': False, 'error': 'Database not found. Please run setup.'})
    
    contacts = get_contacts(db_path)
    return jsonify({'success': True, 'contacts': contacts})


@app.route('/api/messages/<path:contact_id>')
def api_messages(contact_id):
    db_path = get_db_path()
    
    if not db_path:
        return jsonify({'success': False, 'error': 'Database not found'})
    
    limit = request.args.get('limit', 500, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    messages, senders = get_messages(db_path, contact_id, limit, offset)
    
    return jsonify({'success': True, 'messages': messages, 'senders': senders})


@app.route('/api/export', methods=['POST'])
def api_export():
    data = request.json
    contact_id = data.get('contact_id')
    contact_name = data.get('contact_name', contact_id)
    format_type = data.get('format', 'txt')
    
    db_path = get_db_path()
    
    if not db_path:
        return jsonify({'success': False, 'error': 'Database not found'})
    
    try:
        if format_type == 'json':
            filepath, filename = export_chat_json(db_path, contact_id, contact_name)
        elif format_type == 'html':
            filepath, filename = export_chat_html(db_path, contact_id, contact_name)
        else:
            filepath, filename = export_chat_txt(db_path, contact_id, contact_name)
        
        return jsonify({'success': True, 'filepath': filepath, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/export-data', methods=['POST'])
def api_export_data():
    """Export chat and return content directly for browser download"""
    data = request.json
    contact_id = data.get('contact_id')
    contact_name = data.get('contact_name', contact_id)
    format_type = data.get('format', 'txt')
    
    db_path = get_db_path()
    
    if not db_path:
        return jsonify({'success': False, 'error': 'Database not found'})
    
    try:
        content = generate_export_content(db_path, contact_id, contact_name, format_type)
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/exports')
def api_exports():
    exports = []
    for format_dir in ['txt', 'json', 'html']:
        format_path = EXPORTS_DIR / format_dir
        if format_path.exists():
            for f in format_path.iterdir():
                if f.is_file():
                    exports.append({
                        'name': f.name,
                        'format': format_dir,
                        'path': str(f),
                        'size': f.stat().st_size,
                        'created': datetime.fromtimestamp(f.stat().st_ctime).strftime('%Y-%m-%d %H:%M')
                    })
    
    exports.sort(key=lambda x: x['created'], reverse=True)
    return jsonify({'success': True, 'exports': exports})


@app.route('/api/launch-wechat', methods=['POST'])
def api_launch_wechat():
    config = load_config()
    exe_path = config.get('wechat_exe_path', '')
    
    if not exe_path or not Path(exe_path).exists():
        return jsonify({'success': False, 'error': 'WeChat path not configured or file not found'})
    
    try:
        subprocess.Popen([exe_path], shell=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/open-folder', methods=['POST'])
def api_open_folder():
    data = request.json
    folder = data.get('folder', 'exports')
    
    path = EXPORTS_DIR / folder if folder != 'exports' else EXPORTS_DIR
    path.mkdir(exist_ok=True)
    
    os.startfile(str(path))
    return jsonify({'success': True})


@app.route('/api/open-file', methods=['POST'])
def api_open_file():
    data = request.json
    filepath = data.get('filepath', '')
    
    if filepath and Path(filepath).exists():
        os.startfile(filepath)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'File not found'})


@app.route('/api/save-settings', methods=['POST'])
def api_save_settings():
    """Save settings without running setup wizard again"""
    data = request.json
    config = load_config()
    
    old_db_path = config.get('db_path', '')
    db_changed = False
    
    # Update settings
    if 'db_path' in data and data['db_path']:
        new_db_path = data['db_path'].strip()
        if new_db_path != old_db_path:
            # Validate new database path
            if not Path(new_db_path).exists():
                return jsonify({'success': False, 'error': f'Database not found: {new_db_path}'})
            config['db_path'] = new_db_path
            config['setup_complete'] = True
            db_changed = True
    
    if 'wechat_exe_path' in data:
        config['wechat_exe_path'] = data['wechat_exe_path'].strip()
    
    if 'export_path' in data:
        export_path = data['export_path'].strip()
        if export_path:
            # Create export directory if it doesn't exist
            try:
                Path(export_path).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return jsonify({'success': False, 'error': f'Cannot create export folder: {e}'})
        config['export_path'] = export_path
    
    if 'wxid' in data:
        config['wxid'] = data['wxid'].strip()
    
    save_config(config)
    
    return jsonify({
        'success': True,
        'db_changed': db_changed,
        'message': 'Settings saved successfully'
    })


@app.route('/api/media/<path:filepath>')
def api_media(filepath):
    """Serve media files (audio, video, images)"""
    media_dir = get_media_dir()
    if not media_dir:
        return jsonify({'error': 'Media directory not found'}), 404
    
    full_path = media_dir / filepath
    
    if not full_path.exists():
        return jsonify({'error': 'File not found'}), 404
    
    # Determine mime type
    ext = full_path.suffix.lower()
    mimes = {
        '.wav': 'audio/wav',
        '.mp3': 'audio/mpeg',
        '.amr': 'audio/amr',
        '.mp4': 'video/mp4',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
    }
    
    return send_file(str(full_path), mimetype=mimes.get(ext, 'application/octet-stream'))


@app.route('/api/media-info/<contact_id>')
def api_media_info(contact_id):
    """Get list of media files for a contact"""
    media_dir = get_media_dir()
    if not media_dir:
        return jsonify({'success': False, 'error': 'No media directory'})
    
    media = {'audio': [], 'video': [], 'images': []}
    
    # Look for audio files
    audio_dir = media_dir / 'audio' / contact_id
    if audio_dir.exists():
        for f in audio_dir.iterdir():
            if f.suffix.lower() in ['.wav', '.mp3', '.amr']:
                media['audio'].append({
                    'name': f.name,
                    'path': f'audio/{contact_id}/{f.name}'
                })
    
    return jsonify({'success': True, 'media': media})


def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5555')


def heartbeat_monitor():
    """Monitor heartbeat and shutdown if no heartbeat received"""
    global last_heartbeat
    # Wait for initial connection
    time.sleep(15)
    
    while True:
        time.sleep(3)
        elapsed = time.time() - last_heartbeat
        if elapsed > HEARTBEAT_TIMEOUT:
            print(f"\n[!] No heartbeat for {int(elapsed)}s - browser closed, shutting down...")
            os._exit(0)


if __name__ == '__main__':
    print("")
    print("==============================================")
    print("         UsChats by RTB Ruhan")
    print("       Simple WeChat Chat Exporter")
    print("==============================================")
    print("Starting server at http://127.0.0.1:5555")
    print("Browser will open automatically...")
    print("(Server will auto-close when browser tab is closed)")
    print()
    
    # Start heartbeat monitor
    threading.Thread(target=heartbeat_monitor, daemon=True).start()
    
    # Open browser
    threading.Thread(target=open_browser, daemon=True).start()
    
    app.run(host='127.0.0.1', port=5555, debug=False, threaded=True)

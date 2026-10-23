# -*- coding: utf-8 -*-
"""
Prints how WeChat stores image and video paths for your account, so the media
export can be fixed. The output only has masked path shapes and counts: no
message text, contact names, wxids or file names.

Usage:  python diagnose_media.py
"""

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import media_export

SCRIPT_DIR = Path(__file__).parent.absolute()
SAMPLE = 300


def mask(text):
    """Keep folder structure and extensions, hide ids and names"""
    text = text.replace('\\', '/')
    text = re.sub(r'wxid_[A-Za-z0-9_]+', '<wxid>', text)
    parts = text.split('/')
    out = []
    for i, part in enumerate(parts):
        if re.fullmatch(r'[0-9a-fA-F]{16,}', part):
            out.append('<hash>')
        elif re.fullmatch(r'\d{4}-\d{2}', part):
            out.append('YYYY-MM')
        elif i == len(parts) - 1 and '.' in part:
            stem, _, ext = part.rpartition('.')
            suffix = re.search(r'(_[a-zA-Z]{1,5})$', stem)
            out.append('<name>' + (suffix.group(1) if suffix else '') + '.' + ext.lower())
        else:
            out.append(part if len(part) < 25 else '<long>')
    return '/'.join(out)


def describe_entry(text):
    if '/' in text or '\\' in text:
        return mask(text)
    return f'<text len={len(text)}>'


def load_paths():
    config_file = SCRIPT_DIR / 'config.json'
    if not config_file.exists():
        sys.exit('config.json not found. Run the app and decrypt first.')
    config = json.loads(config_file.read_text(encoding='utf-8'))
    db_path = config.get('db_path', '')
    wx_dir = config.get('wx_dir', '')
    if not db_path or not Path(db_path).exists():
        sys.exit('Decrypted database not found in config.json')
    return db_path, Path(wx_dir) if wx_dir else None


def report_type(cursor, msg_type, label, wx_dir):
    cursor.execute(
        "SELECT StrContent, BytesExtra FROM MSG WHERE Type = ? ORDER BY CreateTime DESC LIMIT ?",
        (msg_type, SAMPLE))
    rows = cursor.fetchall()
    print(f'\n=== {label} messages (latest {len(rows)}) ===')
    if not rows:
        print('none found')
        return rows

    shapes = Counter()
    no_blob = 0
    no_entries = 0
    for content, blob in rows:
        if not blob:
            no_blob += 1
            continue
        entries = media_export.parse_bytes_extra(blob)
        if not entries:
            no_entries += 1
            continue
        for entry_type, text in entries:
            exists = False
            if wx_dir and ('/' in text or '\\' in text):
                exists = media_export._resolve_existing(text, wx_dir) is not None
            shapes[(entry_type, describe_entry(text), exists)] += 1

    print(f'no BytesExtra: {no_blob}, BytesExtra without readable entries: {no_entries}')
    print('BytesExtra entries: (entry type, shape, file exists on disk) -> count')
    for (entry_type, shape, exists), count in shapes.most_common(25):
        print(f'  type={entry_type} exists={exists!s:5} {shape}  x{count}')
    return rows


def report_video_md5(rows, wx_dir):
    """Does the md5 in the video XML match a file name under FileStorage/Video?"""
    names = set()
    video_root = wx_dir / 'FileStorage' / 'Video' if wx_dir else None
    if video_root and video_root.is_dir():
        for f in video_root.rglob('*'):
            if f.is_file():
                names.add(f.stem.lower())
    with_md5 = 0
    matched = 0
    for content, _ in rows:
        match = re.search(r'md5="([0-9a-fA-F]{32})"', content or '')
        if match:
            with_md5 += 1
            if match.group(1).lower() in names:
                matched += 1
    print(f'\nvideo messages with an md5 in the XML: {with_md5}')
    print(f'of those, md5 matches a file name in FileStorage/Video: {matched}')


def report_folder(wx_dir, sub, label):
    root = wx_dir / 'FileStorage' / sub if wx_dir else None
    print(f'\n=== FileStorage/{sub} ({label}) ===')
    if not root or not root.is_dir():
        print('folder not found')
        return
    shapes = Counter()
    for i, f in enumerate(root.rglob('*')):
        if i > 20000:
            break
        if f.is_file():
            shapes[mask(str(f.relative_to(root)))] += 1
    for shape, count in shapes.most_common(15):
        print(f'  {shape}  x{count}')
    if not shapes:
        print('no files')


def main():
    db_path, wx_dir = load_paths()
    print('wx_dir in config:', 'set' if wx_dir else 'NOT SET')
    print('wx_dir exists   :', bool(wx_dir and wx_dir.is_dir()))
    print('pilk installed  :', media_export.PILK_AVAILABLE)

    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    cursor = conn.cursor()

    report_type(cursor, 3, 'Image', wx_dir)
    video_rows = report_type(cursor, 43, 'Video', wx_dir)
    if video_rows:
        report_video_md5(video_rows, wx_dir)

    report_folder(wx_dir, 'Video', 'video files on disk')
    report_folder(wx_dir, 'MsgAttach', 'image files on disk')
    conn.close()
    print('\nDone. Check the output for anything private before sharing it.')


if __name__ == '__main__':
    main()

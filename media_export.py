# -*- coding: utf-8 -*-
"""
Media helpers for UsChats HTML export.

Resolves the image / video / voice files that belong to a message, decodes
them into browser-friendly formats and copies them next to the exported HTML.

Formats handled (WeChat for Windows 3.x):
  - image: .dat files XOR-encoded with a single byte key
  - video: plain .mp4
  - voice: SILK blobs stored in the MediaMSG database (Media table)
"""

import re
import shutil
import wave
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import pilk  # optional, only needed to turn voice notes into WAV
    PILK_AVAILABLE = True
except ImportError:
    PILK_AVAILABLE = False

# (magic bytes, extension)
IMAGE_MAGICS = [
    (b'\xff\xd8\xff', '.jpg'),
    (b'\x89PNG', '.png'),
    (b'GIF8', '.gif'),
    (b'BM', '.bmp'),
]

SILK_SAMPLE_RATE = 24000


# ---------- BytesExtra parsing ----------

def _read_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
    raise ValueError("truncated varint")


def _iter_fields(buf: bytes):
    """Yield (field_number, wire_type, value) for a protobuf message"""
    pos = 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 2:
            length, pos = _read_varint(buf, pos)
            value = buf[pos:pos + length]
            pos += length
        elif wire == 1:
            value = buf[pos:pos + 8]
            pos += 8
        elif wire == 5:
            value = buf[pos:pos + 4]
            pos += 4
        else:
            raise ValueError("unsupported wire type")
        yield field, wire, value


def parse_bytes_extra(blob) -> List[Tuple[int, str]]:
    """
    Parse MSG.BytesExtra into (entry_type, string) pairs.
    The blob is a protobuf; field 3 repeats {1: int type, 2: string value}.
    Returns [] if it can't be parsed.
    """
    entries = []
    if not blob or not isinstance(blob, (bytes, bytearray)):
        return entries
    try:
        for field, wire, value in _iter_fields(bytes(blob)):
            if field != 3 or wire != 2:
                continue
            entry_type = None
            text = None
            for f2, w2, v2 in _iter_fields(value):
                if f2 == 1 and w2 == 0:
                    entry_type = v2
                elif f2 == 2 and w2 == 2:
                    text = v2.decode('utf-8', errors='ignore')
            if text:
                entries.append((entry_type, text))
    except Exception:
        pass
    return entries


def find_sender_wxid(entries: List[Tuple[int, str]]) -> Optional[str]:
    """Sender id of a group message, from the non-path BytesExtra entries"""
    for entry_type, text in entries:
        if entry_type == 1 and re.fullmatch(r'[A-Za-z0-9_\-@.]{3,64}', text):
            return text
    for _, text in entries:
        if re.fullmatch(r'wxid_[A-Za-z0-9_]+', text):
            return text
    return None


# ---------- path resolution ----------

def _inside(base: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _resolve_existing(rel: str, wx_dir: Path) -> Optional[Path]:
    """Resolve a path from BytesExtra to a real file below the WeChat data dir"""
    rel = rel.replace('\\', '/').strip()
    if not rel or rel.startswith('/') or ':' in rel or '..' in rel.split('/'):
        return None
    data_dir = wx_dir.parent
    for base in (data_dir, wx_dir):
        candidate = base / rel
        if candidate.is_file() and _inside(data_dir, candidate):
            return candidate
    return None


def find_image_file(entries: List[Tuple[int, str]], wx_dir: Path) -> Optional[Path]:
    """Prefer the full size image over the thumbnail"""
    paths = [t for _, t in entries if t.lower().endswith('.dat') or t.lower().endswith(('.jpg', '.png', '.gif'))]
    candidates = []
    for p in paths:
        norm = p.replace('\\', '/')
        original = re.sub(r'_t\.dat$', '.dat', norm, flags=re.IGNORECASE)
        original = original.replace('/Thumb/', '/Image/')
        hd = re.sub(r'\.dat$', '_h.dat', original, flags=re.IGNORECASE)
        candidates.extend([hd, original, norm])
    for c in candidates:
        found = _resolve_existing(c, wx_dir)
        if found:
            return found
    return None


def find_video_file(entries: List[Tuple[int, str]], wx_dir: Path) -> Optional[Path]:
    for _, text in entries:
        if text.lower().endswith('.mp4'):
            found = _resolve_existing(text, wx_dir)
            if found:
                return found
    return None


# ---------- decoding ----------

def decode_dat_image(data: bytes) -> Optional[Tuple[str, bytes]]:
    """
    Decode a WeChat .dat image (single byte XOR). Returns (extension, bytes)
    or None if the header matches nothing known, for example the newer
    encrypted .dat variants.
    """
    if len(data) < 4:
        return None
    for magic, ext in IMAGE_MAGICS:
        key = data[0] ^ magic[0]
        if all((data[i] ^ key) == magic[i] for i in range(len(magic))):
            if key == 0:
                return ext, data
            return ext, bytes(b ^ key for b in data)
    return None


def silk_to_wav(silk: bytes, out_path: Path) -> bool:
    """Convert a SILK voice note to WAV. Needs the optional pilk package."""
    if not PILK_AVAILABLE or not silk:
        return False
    if silk[:1] == b'\x02':
        silk = silk[1:]
    silk_path = out_path.with_suffix('.silk')
    pcm_path = out_path.with_suffix('.pcm')
    try:
        silk_path.write_bytes(silk)
        pilk.decode(str(silk_path), str(pcm_path))
        pcm = pcm_path.read_bytes()
        with wave.open(str(out_path), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SILK_SAMPLE_RATE)
            w.writeframes(pcm)
        return True
    except Exception:
        return False
    finally:
        for p in (silk_path, pcm_path):
            try:
                p.unlink()
            except OSError:
                pass


# ---------- per message export ----------

def export_image(entries, wx_dir: Path, media_dir: Path, name: str) -> Optional[str]:
    """Returns the path relative to the export folder, or None"""
    src = find_image_file(entries, wx_dir)
    if not src:
        return None
    out_dir = media_dir / 'images'
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        data = src.read_bytes()
    except OSError:
        return None
    if src.suffix.lower() == '.dat':
        decoded = decode_dat_image(data)
        if not decoded:
            return None
        ext, data = decoded
    else:
        ext = src.suffix.lower()
    (out_dir / (name + ext)).write_bytes(data)
    return f'media/images/{name}{ext}'


def export_video(entries, wx_dir: Path, media_dir: Path, name: str) -> Optional[str]:
    src = find_video_file(entries, wx_dir)
    if not src:
        return None
    out_dir = media_dir / 'videos'
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(src, out_dir / (name + '.mp4'))
    except OSError:
        return None
    return f'media/videos/{name}.mp4'


def export_voice(cursor, svr_id, media_dir: Path, name: str) -> Tuple[Optional[str], str]:
    """
    Pull the voice note for MsgSvrID out of the Media table.
    Returns (relative path or None, 'wav' | 'silk' | 'missing')
    """
    if not svr_id:
        return None, 'missing'
    try:
        cursor.execute("SELECT Buf FROM Media WHERE Reserved0 = ? LIMIT 1", (svr_id,))
        row = cursor.fetchone()
    except Exception:
        return None, 'missing'
    if not row or not row[0]:
        return None, 'missing'

    out_dir = media_dir / 'voice'
    out_dir.mkdir(parents=True, exist_ok=True)
    silk = bytes(row[0])

    if silk_to_wav(silk, out_dir / (name + '.wav')):
        return f'media/voice/{name}.wav', 'wav'

    # No decoder available, keep the raw file so nothing is lost
    (out_dir / (name + '.silk')).write_bytes(silk[1:] if silk[:1] == b'\x02' else silk)
    return f'media/voice/{name}.silk', 'silk'

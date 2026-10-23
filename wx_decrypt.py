# -*- coding: utf-8 -*-
"""
WeChat Database Decryption Module for UsChats
Completely standalone - extracts key automatically from running WeChat!
Based on pywxdump by xaoyaoo
"""

import ctypes
import ctypes.wintypes as wintypes
import hashlib
import hmac
import json
import os
import re
import sqlite3
import winreg
from pathlib import Path
from typing import List, Tuple, Optional, Dict

try:
    from Crypto.Cipher import AES
except ImportError:
    from Cryptodome.Cipher import AES

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Constants
SQLITE_FILE_HEADER = "SQLite format 3\x00"
KEY_SIZE = 32
DEFAULT_PAGESIZE = 4096
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

# Memory protection flags
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READWRITE = 0x04
PAGE_READONLY = 0x02
MEM_COMMIT = 0x1000

# Windows API
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

OpenProcess = kernel32.OpenProcess
OpenProcess.restype = wintypes.HANDLE
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

ReadProcessMemory = kernel32.ReadProcessMemory

CloseHandle = kernel32.CloseHandle
CloseHandle.restype = wintypes.BOOL
CloseHandle.argtypes = [wintypes.HANDLE]

# Memory offsets for different WeChat versions
# Format: [nickname, account, mobile, mail, key]
WX_OFFSETS = {
    "3.9.12.15": [93813544, 93814880, 93813352, 0, 93814816],
    "3.9.12.17": [93834984, 93836320, 93834792, 0, 93836256],
    "3.9.11.25": [93701080, 93702416, 93700888, 0, 93702352],
    "3.9.11.23": [93701208, 93700984, 93701016, 0, 93700920],
    "3.9.10.27": [95125656, 95126992, 95125464, 0, 95126928],
    "3.9.10.19": [95129768, 95131104, 95129576, 0, 95131040],
    "3.9.9.43": [68065944, 68067280, 68065752, 0, 68067216],
    "3.9.9.35": [68065304, 68066640, 68065112, 0, 68066576],
    "3.9.8.25": [65000920, 65002256, 65000728, 0, 65002192],
    "3.9.8.15": [64996632, 64997968, 64996440, 0, 64997904],
    "3.9.7.29": [63486984, 63488320, 63486792, 0, 63488256],
    "3.9.7.25": [63482760, 63484096, 63482568, 0, 63484032],
    "3.9.7.15": [63482696, 63484032, 63482504, 0, 63483968],
    "3.9.6.33": [62030600, 62031936, 62030408, 0, 62031872],
    "3.9.5.91": [61654904, 61656240, 61654712, 0, 61656176],
    "3.9.5.81": [61650872, 61652208, 61650680, 0, 61652144],
}


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.restype = ctypes.c_size_t
VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, 
                           ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]


def get_process_list() -> List[Tuple[int, str, str]]:
    """Get list of running processes with paths"""
    if not PSUTIL_AVAILABLE:
        return []
    
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            processes.append((proc.info['pid'], proc.info['name'], proc.info.get('exe', '')))
        except:
            pass
    return processes


def get_wechat_processes() -> List[Dict]:
    """Find running WeChat processes with version info"""
    results = []
    for pid, name, exe_path in get_process_list():
        if name and name.lower() == "wechat.exe" and exe_path:
            version = get_file_version(exe_path)
            results.append({
                'pid': pid,
                'exe_path': exe_path,
                'version': version
            })
    return results


def is_wechat_running() -> bool:
    """Check if WeChat is running"""
    return len(get_wechat_processes()) > 0


def get_file_version(path: str) -> Optional[str]:
    """Get file version from exe"""
    try:
        import ctypes
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if size == 0:
            return None
        
        res = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(path, 0, size, res)
        
        # Query fixed file info
        uLen = ctypes.c_uint()
        lpBuf = ctypes.c_void_p()
        ctypes.windll.version.VerQueryValueW(res, "\\", ctypes.byref(lpBuf), ctypes.byref(uLen))
        
        if lpBuf:
            # Read VS_FIXEDFILEINFO structure
            class VS_FIXEDFILEINFO(ctypes.Structure):
                _fields_ = [
                    ("dwSignature", ctypes.c_uint32),
                    ("dwStrucVersion", ctypes.c_uint32),
                    ("dwFileVersionMS", ctypes.c_uint32),
                    ("dwFileVersionLS", ctypes.c_uint32),
                    ("dwProductVersionMS", ctypes.c_uint32),
                    ("dwProductVersionLS", ctypes.c_uint32),
                    ("dwFileFlagsMask", ctypes.c_uint32),
                    ("dwFileFlags", ctypes.c_uint32),
                    ("dwFileOS", ctypes.c_uint32),
                    ("dwFileType", ctypes.c_uint32),
                    ("dwFileSubtype", ctypes.c_uint32),
                    ("dwFileDateMS", ctypes.c_uint32),
                    ("dwFileDateLS", ctypes.c_uint32),
                ]
            
            ffi = ctypes.cast(lpBuf, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
            ms = ffi.dwFileVersionMS
            ls = ffi.dwFileVersionLS
            version = f"{(ms >> 16) & 0xffff}.{ms & 0xffff}.{(ls >> 16) & 0xffff}.{ls & 0xffff}"
            return version
    except:
        pass
    return None


def get_module_base_address(pid: int, module_name: str = "WeChatWin.dll") -> Optional[Tuple[int, str]]:
    """Get base address and path of a module in the process"""
    if not PSUTIL_AVAILABLE:
        return None, None
    
    try:
        process = psutil.Process(pid)
        for module in process.memory_maps():
            if module.path and module_name.lower() in module.path.lower():
                # Parse the address range
                addr_str = module.addr.split('-')[0]
                return int(addr_str, 16), module.path
    except Exception as e:
        print(f"Error getting module base: {e}")
    return None, None


def get_wechat_dll_info(pid: int) -> Optional[Tuple[int, str]]:
    """Get WeChatWin.dll base address and version using Windows API"""
    try:
        import ctypes
        from ctypes import wintypes
        
        # Use CreateToolhelp32Snapshot to enumerate modules
        TH32CS_SNAPMODULE = 0x00000008
        TH32CS_SNAPMODULE32 = 0x00000010
        
        class MODULEENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("th32ModuleID", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("GlsBaseAddr", wintypes.DWORD),
                ("ProccntUsage", wintypes.DWORD),
                ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", wintypes.DWORD),
                ("hModule", wintypes.HMODULE),
                ("szModule", ctypes.c_char * 256),
                ("szExePath", ctypes.c_char * 260),
            ]
        
        CreateToolhelp32Snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot
        Module32First = ctypes.windll.kernel32.Module32First
        Module32Next = ctypes.windll.kernel32.Module32Next
        CloseHandle = ctypes.windll.kernel32.CloseHandle
        
        snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if snapshot == -1:
            return None, None
        
        me32 = MODULEENTRY32()
        me32.dwSize = ctypes.sizeof(MODULEENTRY32)
        
        if Module32First(snapshot, ctypes.byref(me32)):
            while True:
                module_name = me32.szModule.decode('utf-8', errors='ignore')
                if 'WeChatWin.dll' in module_name:
                    base_addr = me32.modBaseAddr
                    module_path = me32.szExePath.decode('utf-8', errors='ignore')
                    CloseHandle(snapshot)
                    return base_addr, module_path
                
                if not Module32Next(snapshot, ctypes.byref(me32)):
                    break
        
        CloseHandle(snapshot)
    except Exception as e:
        print(f"Error getting DLL info: {e}")
    
    return None, None


def read_memory(handle, address: int, size: int) -> Optional[bytes]:
    """Read memory from process"""
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()
    
    if ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(bytes_read)):
        return buffer.raw[:bytes_read.value]
    return None


def read_string_from_memory(handle, address: int, max_len: int = 64) -> Optional[str]:
    """Read null-terminated string from memory"""
    data = read_memory(handle, address, max_len)
    if data:
        try:
            # Find null terminator
            null_pos = data.find(b'\x00')
            if null_pos > 0:
                return data[:null_pos].decode('utf-8', errors='ignore')
        except:
            pass
    return None


def get_key_from_offset(handle, address: int, addr_len: int = 8) -> Optional[str]:
    """Read key from memory offset"""
    try:
        # Read pointer first
        ptr_bytes = read_memory(handle, address, addr_len)
        if not ptr_bytes:
            return None
        
        # Convert to address
        ptr = int.from_bytes(ptr_bytes, byteorder='little')
        if ptr == 0:
            return None
        
        # Read 32 bytes key
        key_bytes = read_memory(handle, ptr, 32)
        if key_bytes and len(key_bytes) == 32:
            return key_bytes.hex()
    except:
        pass
    return None


def verify_key(key: str, db_path: str) -> bool:
    """Verify if the key can decrypt the database"""
    if not key or len(key) != 64:
        return False
    
    if not os.path.exists(db_path):
        return False
    
    try:
        password = bytes.fromhex(key.strip())
        with open(db_path, "rb") as f:
            blist = f.read(4096)
        
        if len(blist) < 4096:
            return False
        
        salt = blist[:16]
        if len(salt) != 16:
            return False
        
        mac_salt = bytes([(salt[i] ^ 58) for i in range(16)])
        byteHmac = hashlib.pbkdf2_hmac("sha1", password, salt, 64000, KEY_SIZE)
        mac_key = hashlib.pbkdf2_hmac("sha1", byteHmac, mac_salt, 2, KEY_SIZE)
        
        hash_mac = hmac.new(mac_key, blist[16:4064], hashlib.sha1)
        hash_mac.update(b'\x01\x00\x00\x00')
        
        first = blist[16:4096]
        return hash_mac.digest() == first[-32:-12]
    except:
        return False


def search_key_in_memory(handle, pid: int, wx_dir: str, addr_len: int = 8) -> Optional[str]:
    """Search for decryption key in WeChat memory"""
    try:
        # Find a database to verify against
        test_db = None
        msg_dir = Path(wx_dir) / "Msg"
        if msg_dir.exists():
            for db in msg_dir.glob("*.db"):
                test_db = str(db)
                break
        
        if not test_db:
            return None
        
        # Search for key pattern in memory
        mbi = MEMORY_BASIC_INFORMATION()
        address = 0
        max_address = 0x7FFFFFFFFFFF if addr_len == 8 else 0x7FFFFFFF
        
        while address < max_address:
            if VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
                break
            
            # Check if memory is readable
            if mbi.State == MEM_COMMIT and mbi.Protect in [PAGE_READWRITE, PAGE_READONLY]:
                try:
                    region_size = min(mbi.RegionSize, 0x100000)  # Read max 1MB at a time
                    data = read_memory(handle, mbi.BaseAddress, region_size)
                    
                    if data:
                        # Search for key patterns (32 bytes that could be a key)
                        # Keys are usually after certain patterns
                        for i in range(0, len(data) - 32, 8):
                            candidate = data[i:i+32]
                            if len(set(candidate)) > 16:  # Has variety (not all zeros)
                                key_hex = candidate.hex()
                                if verify_key(key_hex, test_db):
                                    return key_hex
                except:
                    pass
            
            address = mbi.BaseAddress + mbi.RegionSize
            if address <= mbi.BaseAddress:
                break
    except:
        pass
    return None


def extract_wechat_info(pid: int) -> Dict:
    """Extract WeChat info including key from running process"""
    result = {
        'pid': pid,
        'version': None,
        'wxid': None,
        'nickname': None,
        'key': None,
        'wx_dir': None,
        'data_dir': None,
        'error': None
    }
    
    try:
        # Get process handle
        handle = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            result['error'] = "Cannot open process (run as admin?)"
            return result
        
        # Get WeChat.exe path and version
        if PSUTIL_AVAILABLE:
            try:
                proc = psutil.Process(pid)
                exe_path = proc.exe()
                result['version'] = get_file_version(exe_path)
            except:
                pass
        
        # Get WeChatWin.dll base address using Windows API
        base_addr, dll_path = get_wechat_dll_info(pid)
        
        # Fallback to psutil method
        if not base_addr:
            base_addr, dll_path = get_module_base_address(pid)
        
        if not base_addr:
            result['error'] = "WeChatWin.dll not found"
            CloseHandle(handle)
            return result
        
        # Get version from DLL if not from exe
        if not result['version'] and dll_path:
            result['version'] = get_file_version(dll_path)
        
        addr_len = 8  # 64-bit
        
        # Get offsets for this version
        offsets = WX_OFFSETS.get(result['version'])
        
        if offsets and len(offsets) >= 5:
            # Try to read from known offsets
            # [nickname, account, mobile, mail, key]
            
            # Get key from offset
            key_offset = offsets[4]
            if key_offset:
                key = get_key_from_offset(handle, base_addr + key_offset, addr_len)
                if key:
                    result['key'] = key
        
        # Try to get wxid from registry
        result['data_dir'] = get_wechat_data_dir()
        if result['data_dir']:
            wxids = find_wxid_folders(result['data_dir'])
            if wxids:
                result['wxid'] = wxids[0]  # Use first found
                result['wx_dir'] = os.path.join(result['data_dir'], result['wxid'])
        
        # If key not found from offset, try memory search
        if not result['key'] and result['wx_dir']:
            result['key'] = search_key_in_memory(handle, pid, result['wx_dir'], addr_len)
        
        CloseHandle(handle)
        
    except Exception as e:
        result['error'] = str(e)
    
    return result


def get_wechat_data_dir() -> Optional[str]:
    """Get WeChat data directory from registry"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 
                             r"Software\Tencent\WeChat", 
                             0, winreg.KEY_READ)
        value, _ = winreg.QueryValueEx(key, "FileSavePath")
        winreg.CloseKey(key)
        
        if value and value != "MyDocument:":
            if Path(value).exists():
                return value
    except:
        pass
    
    # Try to get actual Documents folder from Windows
    try:
        import ctypes.wintypes
        CSIDL_PERSONAL = 5  # My Documents
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, buf)
        docs_path = Path(buf.value) / "WeChat Files"
        if docs_path.exists():
            return str(docs_path)
    except:
        pass
    
    # Common locations to check
    possible_locations = [
        Path.home() / "Documents" / "WeChat Files",
        Path("D:/Documents/WeChat Files"),
        Path("C:/Users") / os.getlogin() / "Documents" / "WeChat Files",
    ]
    
    for loc in possible_locations:
        if loc.exists():
            return str(loc)
    
    # Search common drives
    for drive in ["C:", "D:", "E:", "F:"]:
        wc_path = Path(drive) / "Documents" / "WeChat Files"
        if wc_path.exists():
            return str(wc_path)
    
    return None


def find_wxid_folders(data_dir: str) -> List[str]:
    """Find wxid folders in the data directory"""
    wxids = []
    data_path = Path(data_dir)
    if data_path.exists():
        for item in data_path.iterdir():
            if item.is_dir() and item.name.startswith("wxid_"):
                wxids.append(item.name)
    return wxids


def find_databases(wxid_path: str) -> List[Dict]:
    """Find all WeChat database files for a wxid"""
    databases = []
    wxid_path = Path(wxid_path)
    
    # Core database types
    db_patterns = [
        ("MSG", "Msg"),
        ("MicroMsg", "Msg"),
        ("MediaMSG", "Msg"),
        ("PublicMsg", "Msg"),
        ("Favorite", "Favorite"),
        ("Emotion", ""),
    ]
    
    for db_type, subdir in db_patterns:
        search_path = wxid_path / subdir if subdir else wxid_path
        if search_path.exists():
            for db_file in search_path.rglob("*.db"):
                if db_type.lower() in db_file.name.lower():
                    databases.append({
                        "db_path": str(db_file),
                        "db_type": db_type,
                        "name": db_file.name
                    })
    
    return databases


def decrypt_database(key: str, db_path: str, out_path: str) -> Tuple[bool, str]:
    """Decrypt a WeChat database file"""
    if not os.path.exists(db_path):
        return False, f"Database not found: {db_path}"
    
    if len(key) != 64:
        return False, f"Invalid key length"
    
    try:
        password = bytes.fromhex(key.strip())
    except ValueError:
        return False, "Invalid key format"
    
    try:
        with open(db_path, "rb") as f:
            blist = f.read()
    except Exception as e:
        return False, f"Cannot read database: {e}"
    
    if len(blist) < 4096:
        return False, "Database too small"
    
    salt = blist[:16]
    first = blist[16:4096]
    
    mac_salt = bytes([(salt[i] ^ 58) for i in range(16)])
    byteHmac = hashlib.pbkdf2_hmac("sha1", password, salt, 64000, KEY_SIZE)
    mac_key = hashlib.pbkdf2_hmac("sha1", byteHmac, mac_salt, 2, KEY_SIZE)
    
    hash_mac = hmac.new(mac_key, blist[16:4064], hashlib.sha1)
    hash_mac.update(b'\x01\x00\x00\x00')
    
    if hash_mac.digest() != first[-32:-12]:
        return False, "Wrong key"
    
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    try:
        with open(out_path, "wb") as out_file:
            out_file.write(SQLITE_FILE_HEADER.encode())
            for i in range(0, len(blist), 4096):
                tblist = blist[i:i + 4096] if i > 0 else blist[16:i + 4096]
                out_file.write(AES.new(byteHmac, AES.MODE_CBC, tblist[-48:-32]).decrypt(tblist[:-48]))
                out_file.write(tblist[-48:])
    except Exception as e:
        return False, f"Write failed: {e}"
    
    return True, out_path


def merge_databases(decrypted_paths: List[str], output_path: str) -> Tuple[bool, str]:
    """Merge multiple decrypted databases into one"""
    if not decrypted_paths:
        return False, "No databases to merge"
    
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        out_conn = sqlite3.connect(output_path)
        out_cursor = out_conn.cursor()
        
        tables_created = set()
        
        for db_path in decrypted_paths:
            if not os.path.exists(db_path):
                continue
            
            try:
                src_conn = sqlite3.connect(db_path)
                src_cursor = src_conn.cursor()
                
                src_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                tables = [row[0] for row in src_cursor.fetchall()]
                
                for table in tables:
                    src_cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
                    schema_row = src_cursor.fetchone()
                    if not schema_row or not schema_row[0]:
                        continue
                    
                    if table not in tables_created:
                        try:
                            out_cursor.execute(schema_row[0])
                            tables_created.add(table)
                        except:
                            pass
                    
                    src_cursor.execute(f"SELECT * FROM {table}")
                    rows = src_cursor.fetchall()
                    
                    if rows:
                        placeholders = ",".join(["?" for _ in rows[0]])
                        for row in rows:
                            try:
                                out_cursor.execute(f"INSERT OR IGNORE INTO {table} VALUES ({placeholders})", row)
                            except:
                                pass
                
                src_conn.close()
            except:
                continue
        
        out_conn.commit()
        out_conn.close()
        
        return True, output_path
    except Exception as e:
        return False, f"Merge failed: {e}"


def auto_decrypt() -> Dict:
    """
    Fully automatic decryption - detects WeChat, extracts key, decrypts all databases.
    Returns status and any error messages.
    """
    result = {
        'success': False,
        'message': '',
        'wechat_running': False,
        'version': None,
        'wxid': None,
        'key': None,
        'db_path': None,
        'data_dir': None,
        'step': 'init'
    }
    
    # Step 1: Check if WeChat is running
    result['step'] = 'detect_wechat'
    wechat_procs = get_wechat_processes()
    
    if not wechat_procs:
        result['message'] = "WeChat is not running. Please start WeChat first."
        return result
    
    result['wechat_running'] = True
    result['version'] = wechat_procs[0]['version']
    
    # Step 2: Get data directory
    result['step'] = 'find_data_dir'
    data_dir = get_wechat_data_dir()
    
    if not data_dir:
        result['message'] = "Cannot find WeChat data folder."
        return result
    
    result['data_dir'] = data_dir
    
    # Step 3: Find wxid folders
    result['step'] = 'find_wxid'
    wxids = find_wxid_folders(data_dir)
    
    if not wxids:
        result['message'] = f"No WeChat accounts found in {data_dir}"
        return result
    
    result['wxid'] = wxids[0]  # Use first account
    wx_dir = os.path.join(data_dir, result['wxid'])
    result['wx_dir'] = wx_dir

    # Step 4: Extract key from memory
    result['step'] = 'extract_key'
    pid = wechat_procs[0]['pid']
    info = extract_wechat_info(pid)
    
    if not info.get('key'):
        result['message'] = f"Cannot extract key. WeChat version: {result['version']}"
        if result['version'] not in WX_OFFSETS:
            result['message'] += f"\n\nThis version is not supported yet. Supported versions: {', '.join(WX_OFFSETS.keys())}"
        return result
    
    result['key'] = info['key']
    
    # Step 5: Find and decrypt databases
    result['step'] = 'decrypt'
    databases = find_databases(wx_dir)
    
    if not databases:
        result['message'] = "No databases found to decrypt."
        return result
    
    # Create output directory
    script_dir = Path(__file__).parent
    output_dir = script_dir / "data" / result['wxid']
    output_dir.mkdir(parents=True, exist_ok=True)
    decrypted_dir = output_dir / "decrypted"
    decrypted_dir.mkdir(exist_ok=True)
    
    # Decrypt all databases
    decrypted_paths = []
    for db in databases:
        out_path = str(decrypted_dir / Path(db['db_path']).name)
        success, msg = decrypt_database(result['key'], db['db_path'], out_path)
        if success:
            decrypted_paths.append(out_path)
    
    if not decrypted_paths:
        result['message'] = "Failed to decrypt any databases. Key might be wrong."
        return result
    
    # Step 6: Merge databases
    result['step'] = 'merge'
    merge_path = str(output_dir / "merge_all.db")
    success, msg = merge_databases(decrypted_paths, merge_path)
    
    if not success:
        result['message'] = f"Merge failed: {msg}"
        return result
    
    result['success'] = True
    result['db_path'] = merge_path
    result['message'] = f"Success! Decrypted and merged {len(decrypted_paths)} databases."
    result['step'] = 'done'
    
    return result


def get_wechat_info() -> Dict:
    """Get WeChat information for display"""
    info = {
        "running": False,
        "version": None,
        "data_dir": None,
        "wxids": [],
        "pids": [],
        "key_available": False,
        "supported_version": False
    }
    
    wechat_procs = get_wechat_processes()
    info["running"] = len(wechat_procs) > 0
    
    if wechat_procs:
        info["pids"] = [p['pid'] for p in wechat_procs]
        info["version"] = wechat_procs[0]['version']
        info["supported_version"] = info["version"] in WX_OFFSETS
    
    info["data_dir"] = get_wechat_data_dir()
    
    if info["data_dir"]:
        info["wxids"] = find_wxid_folders(info["data_dir"])
    
    return info


if __name__ == "__main__":
    print("UsChats WeChat Decryptor")
    print("=" * 40)
    
    info = get_wechat_info()
    print(f"WeChat running: {info['running']}")
    print(f"Version: {info['version']}")
    print(f"Supported: {info['supported_version']}")
    print(f"Data dir: {info['data_dir']}")
    print(f"Accounts: {info['wxids']}")
    
    if info['running']:
        print("\nAttempting auto-decrypt...")
        result = auto_decrypt()
        print(f"Success: {result['success']}")
        print(f"Message: {result['message']}")
        if result['db_path']:
            print(f"Database: {result['db_path']}")

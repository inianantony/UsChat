# 💬 UsChats - Simple WeChat Chat Exporter

**Created by RTB Ruhan**

A clean, modern tool to export your WeChat chat history. **Completely standalone - no wxdump needed!**

![UsChats](https://img.shields.io/badge/Made%20with-❤️-red)
![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)

---

## ⚠️ IMPORTANT: How This Tool Works

This tool reads from your **LIVE WeChat PC data** - NOT from WeChat's "Backup" feature!

| ❌ This does NOT work | ✅ This DOES work |
|----------------------|-------------------|
| WeChat's "Backup to PC" files | Live chat data while WeChat is running |
| `BackupFiles` folder | `Msg` folder with MSG0.db, MicroMsg.db etc. |
| Phone backup data | PC synced messages |

**Your messages must be synced to your PC version of WeChat to be exported.**

---

## 🚀 Quick Start

### Step 1: Install WeChat 3.9.12.15
Download and install WeChat version **3.9.12.15** (this specific older version is required).

Default install location:
```
C:\Program Files (x86)\Tencent\WeChat\WeChat.exe
```

### Step 2: Sync and Save Messages
1. Open WeChat 3.9.12.15
2. Log in with your account
3. **Wait for messages to sync** - you should see your chat history appear
4. **Close WeChat completely** (this saves pending messages to the database)
5. **Reopen WeChat** and keep it running

> ⚠️ **Important**: WeChat stores new messages in a temporary file (WAL). Closing WeChat forces it to save everything to the main database, which we can then decrypt.

### Step 3: Run UsChats
```bash
cd UsChats
pip install -r requirements.txt
python app.py
```
Or double-click **`START.bat`**

### Step 4: Click "Auto Decrypt My Chats"
The tool will automatically:
- ✅ Detect WeChat is running
- ✅ Extract the decryption key from memory
- ✅ Decrypt your chat databases
- ✅ Show your conversations!

---

## 📁 Where WeChat Stores Data

WeChat stores your chat data in these locations:

### Default Location (Windows)
```
C:\Users\YOUR_USERNAME\Documents\WeChat Files\YOUR_WXID\Msg\
```

### Custom Location (if you changed it)
Check WeChat Settings → Files → File Location

### What's Inside
```
WeChat Files/
└── wxid_xxxxxxxxx/           <- Your WeChat ID
    ├── Msg/                  <- Chat databases (what we read!)
    │   ├── Multi/
    │   │   └── MSG0.db       <- Main message database
    │   ├── MicroMsg.db       <- Contacts & settings
    │   └── ...
    ├── FileStorage/          <- Media files
    └── BackupFiles/          <- Phone backups (NOT supported)
```

---

## ❓ Common Questions

### "No chats found" after decrypt?
**Your WeChat PC hasn't synced any messages yet.**
- Open WeChat on your phone
- Make sure PC WeChat shows your chat history
- The messages must appear in PC WeChat to be exported

### "BackupFiles" doesn't work?
The `BackupFiles` folder contains encrypted phone backup data in a different format. This tool reads the LIVE database files, not backup files.

### Can I export phone-only messages?
Only if you sync them to PC WeChat first. Open the chat on your phone, and it will sync to PC.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔓 **Built-in Decryption** | Extracts key automatically - no wxdump needed! |
| 💬 **Chat Browser** | WhatsApp-like interface with search |
| 📄 **TXT Export** | Plain text format |
| 📋 **JSON Export** | Structured data for analysis |
| 🌐 **HTML Export** | Beautiful web page view |
| 📊 **CSV Export** | Spreadsheet format |
| 🖼️ **Media Support** | View images, play audio/video |

---

## 🔧 Supported WeChat Versions

| Version | Status |
|---------|--------|
| 3.9.12.15 | ✅ Fully Supported |
| 3.9.12.17 | ✅ Supported |
| 3.9.11.x | ✅ Supported |
| 3.9.10.x | ✅ Supported |
| 3.9.9.x | ✅ Supported |
| 3.9.8.x | ✅ Supported |
| 3.9.7.x | ✅ Supported |
| 3.9.6.x | ✅ Supported |
| 3.9.5.x | ✅ Supported |

---

## 🔒 Privacy

- All processing happens **locally** on your computer
- No data is sent to any server
- Your decryption key is stored locally in `config.json`
- Export files stay in the `exports/` folder

---

## 📝 License

MIT License - Free to use and modify.

---

Made with ❤️ by RTB Ruhan

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

## 🖼️ HTML Export with Images, Videos and Voice Notes (`media-export` branch)

This fork's `media-export` branch makes the **HTML export** include everything: text, images, videos and voice notes.

### Get it on a new machine
```bash
git clone -b media-export https://github.com/inianantony/UsChat.git
cd UsChat
pip install -r requirements.txt
pip install -r requirements-voice.txt   # optional, makes voice notes playable
python app.py
```
Or double-click **`START.bat`** (it installs `requirements.txt` for you, but not the optional voice package).

### Before you click "Auto Decrypt My Chats"
1. WeChat must be **running and logged in** on that machine.
2. If `Documents\WeChat Files` has more than one `wxid_*` folder, the tool picks the **first one**, which may not be your logged-in account. That gives `Failed to decrypt any databases. Key might be wrong.`
   Workaround: rename the other account folders with a leading `_` (for example `_wxid_old`), then try again. Rename them back afterwards.
3. Check the WeChat version is in the supported list below.

### Exporting
1. Open a chat and click the **HTML** export button.
2. The export is a **folder**, not a single file:
```
exports/html/<chat name>_<timestamp>/
├── index.html          <- open this
└── media/
    ├── images/         <- decoded .jpg / .png / .gif
    ├── videos/         <- .mp4
    └── voice/          <- .wav (or .silk if pilk is not installed)
```
3. When it finishes, a message shows how many images, videos and voice notes were exported and how many were not found. `index.html` then opens automatically.
4. To share the export, zip the **whole folder**. `index.html` uses relative links to `media/`.

### Good to know
- **Media is read from the live WeChat folder** (`WeChat Files\<wxid>\FileStorage`), so keep WeChat's data folder where it is while exporting.
- **Only media WeChat has downloaded to disk can be exported.** Anything never opened on this PC, or expired on WeChat's servers, shows `not available on disk` in the page.
- **Voice notes** need the optional `pilk` package to become playable `.wav` files. Without it they are saved as raw `.silk` files with a download link.
- **Images** are decoded from WeChat's `.dat` format. Some newer 3.9.x builds use a different encrypted `.dat` format that cannot be decoded yet. Those images show as not available.
- **The export reads the chat database, not WeChat's Backup feature.** See the table at the top.

### If images or videos show "not available on disk"
Open the `FileStorage` folder under your account folder and check the files exist (folder names and file counts are enough, no need to open them). If the files exist but the export still says they are missing, the media paths stored in your WeChat build do not match what this tool expects. Note the numbers from the export message and report them.

### Security notes for this fork
- Run it only on a machine you own or are authorized to use. It reads another process's memory to get the database key.
- The decryption key is saved in plain text in `config.json`, and decrypted databases and exports are plain files in `data/` and `exports/`. Delete them when you are done.
- The server listens on `127.0.0.1` only and has no login. Don't browse untrusted websites while it is running.
- Both `config.json` and the data folders are git-ignored, so they won't be committed.

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
| 🌐 **HTML Export** | Web page view with images, videos and voice notes (see the `media-export` section) |
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

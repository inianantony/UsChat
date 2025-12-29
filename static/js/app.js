/**
 * UsChats - Simple WeChat Chat Exporter
 * by RTB Ruhan
 */

let contacts = [];
let currentContact = null;
let isInitialized = false;
let isGroupChat = false;
let senderNames = {};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ============================================
// Init
// ============================================

document.addEventListener('DOMContentLoaded', async () => {
    await checkStatus();
    setupNavigation();
    setupSearch();
    setupWechatLauncher();
    setupResize();
    setupHeartbeat();
    setupExportDropdown();
});

// ============================================
// Export Dropdown
// ============================================

function setupExportDropdown() {
    const btn = $('#export-btn');
    const menu = $('#export-menu');
    if (!btn || !menu) return;
    
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        menu.classList.toggle('show');
    });
    
    document.addEventListener('click', () => {
        menu.classList.remove('show');
    });
    
    menu.addEventListener('click', () => {
        menu.classList.remove('show');
    });
}

// ============================================
// Heartbeat - keeps server alive, shuts down when tab closes
// ============================================

function setupHeartbeat() {
    // Send heartbeat every 3 seconds
    setInterval(() => {
        fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
    }, 3000);
    
    // Send initial heartbeat
    fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
    
    // Also try to shutdown on tab close (backup)
    // Removed: beforeunload shutdown - heartbeat timeout handles server shutdown
    // This was causing issues with page navigation within the app
    
    // Handle visibility change (tab hidden/visible)
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
        }
    });
}

// ============================================
// Resizable Panel
// ============================================

function setupResize() {
    const handle1 = $('#resize-handle');
    const handle2 = $('#chat-resize-handle');
    const panel = $('#contact-list');
    if (!panel) return;
    
    let isResizing = false;
    let activeHandle = null;
    
    function startResize(e, handle) {
        isResizing = true;
        activeHandle = handle;
        if (handle) handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    }
    
    if (handle1) {
        handle1.addEventListener('mousedown', (e) => startResize(e, handle1));
    }
    
    if (handle2) {
        handle2.addEventListener('mousedown', (e) => startResize(e, handle2));
    }
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        // Account for sidebar width (60px)
        const sidebarWidth = 60;
        const newWidth = e.clientX - sidebarWidth;
        if (newWidth >= 200 && newWidth <= 600) {
            panel.style.width = newWidth + 'px';
        }
    });
    
    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            if (activeHandle) activeHandle.classList.remove('active');
            activeHandle = null;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            // Save preference
            localStorage.setItem('panelWidth', panel.style.width);
        }
    });
    
    // Restore saved width
    const savedWidth = localStorage.getItem('panelWidth');
    if (savedWidth) {
        panel.style.width = savedWidth;
    }
}

async function checkStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        // Pre-fill database path if one is found
        const dbInput = $('#input-db-path');
        if (data.existing_db_path && dbInput) {
            dbInput.value = data.existing_db_path;
            dbInput.placeholder = data.existing_db_path;
        }
        
        if (data.wechat_exe_path) {
            $('#input-wechat-exe').value = data.wechat_exe_path;
        }
        
        // Always update settings fields
        $('#setting-db-path').value = data.db_path || '';
        $('#setting-exe-path').value = data.wechat_exe_path || '';
        if ($('#setting-export-path')) {
            $('#setting-export-path').value = data.export_path || '';
        }
        if ($('#setting-my-wxid')) {
            $('#setting-my-wxid').value = data.my_wxid || 'Not detected';
        }
        
        if (data.setup_complete && data.db_ready) {
            isInitialized = true;
            showView('chats');
            loadContacts();
        } else {
            // We're on setup view - check WeChat status
            checkWeChatStatus();
        }
    } catch (err) {
        console.error('Status check failed:', err);
    }
}

// ============================================
// Navigation
// ============================================

function setupNavigation() {
    $$('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            if (!isInitialized && view !== 'settings') {
                showToast('Complete setup first', 'warning');
                return;
            }
            $$('.nav-item').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            showView(view);
            if (view === 'chats') loadContacts();
            if (view === 'exports') loadExports();
        });
    });
}

function showView(viewName) {
    $$('.view').forEach(v => v.style.display = 'none');
    const view = $(`#view-${viewName}`);
    if (view) {
        // Setup and chats views need flex for proper layout/centering
        if (viewName === 'chats' || viewName === 'setup') {
            view.style.display = 'flex';
        } else {
            view.style.display = 'block';
        }
    }
    $$('.nav-item').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === viewName);
    });
    
    // Check WeChat status when showing setup
    if (viewName === 'setup') {
        setTimeout(checkWeChatStatus, 100);
    }
}

// ============================================
// Setup
// ============================================

function showStep(step) {
    $$('.step').forEach(s => s.classList.remove('active'));
    const stepEl = $(`.step[data-step="${step}"]`);
    if (stepEl) stepEl.classList.add('active');
    
    $$('.progress-dot').forEach((dot, i) => {
        dot.classList.remove('active', 'completed');
        if (i + 1 < step) dot.classList.add('completed');
        if (i + 1 === step) dot.classList.add('active');
    });
}

async function checkWeChatStatus() {
    const statusBox = $('#wechat-status-box');
    const autoBtn = $('#btn-auto-decrypt');
    
    if (!statusBox) return;
    
    statusBox.innerHTML = '<span class="spinner"></span> Checking WeChat status...';
    
    try {
        const res = await fetch('/api/wechat-info');
        const data = await res.json();
        
        if (data.success && data.running) {
            if (data.supported_version) {
                statusBox.innerHTML = `✓ WeChat ${data.version} is running (supported!)`;
                statusBox.className = 'info-box success';
                autoBtn.disabled = false;
            } else {
                statusBox.innerHTML = `⚠️ WeChat ${data.version} is running but version not fully supported. Auto-decrypt may not work.`;
                statusBox.className = 'info-box warning';
                autoBtn.disabled = false;
            }
        } else if (data.success && !data.running) {
            statusBox.innerHTML = '⚠️ WeChat is not running. Please start WeChat first!';
            statusBox.className = 'info-box warning';
            autoBtn.disabled = true;
        } else {
            statusBox.innerHTML = '⚠️ ' + (data.error || 'Cannot detect WeChat');
            statusBox.className = 'info-box warning';
            autoBtn.disabled = true;
        }
    } catch (err) {
        statusBox.innerHTML = '⚠️ Cannot check WeChat status';
        statusBox.className = 'info-box warning';
    }
}

async function autoDecrypt() {
    // Show progress step
    showStep(2);
    
    const progressBar = $('#decrypt-progress');
    const statusEl = $('#decrypt-status');
    const descEl = $('#decrypt-step-desc');
    
    progressBar.style.width = '10%';
    statusEl.textContent = 'Detecting WeChat...';
    descEl.textContent = 'This may take a minute';
    
    try {
        progressBar.style.width = '20%';
        statusEl.textContent = 'Extracting decryption key from WeChat memory...';
        
        const res = await fetch('/api/auto-decrypt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        
        if (data.success) {
            progressBar.style.width = '100%';
            statusEl.textContent = 'Complete!';
            
            // Check if we actually found any chats
            const contactsRes = await fetch('/api/contacts');
            const contactsData = await contactsRes.json();
            const contactCount = contactsData.contacts ? contactsData.contacts.length : 0;
            
            if (contactCount === 0) {
                showToast('Decryption complete but no chats found. WeChat may be empty.', 'warning');
                if ($('#success-message')) {
                    $('#success-message').innerHTML = 
                        'Decryption successful but no chat history found.<br>' +
                        '<small style="color: var(--text-muted);">' +
                        'Your WeChat may be new or chats haven\'t synced. ' +
                        'Or use "I Already Have a Database" to load an existing backup.</small>';
                }
            } else {
                showToast('Decryption complete!', 'success');
                if ($('#success-message')) {
                    $('#success-message').textContent = `Found ${contactCount} conversations!`;
                }
            }
            
            showStep(3);
        } else {
            // Show error
            progressBar.style.width = '0%';
            
            let errorMsg = data.message || 'Decryption failed';
            
            // More helpful error messages
            if (data.step === 'detect_wechat') {
                errorMsg = "WeChat is not running. Please start WeChat and try again.";
            } else if (data.step === 'extract_key') {
                errorMsg = "Could not extract the decryption key. ";
                if (data.version) {
                    errorMsg += `Your WeChat version (${data.version}) may not be fully supported yet.`;
                }
            }
            
            showToast(errorMsg, 'error');
            showStep(1);
            
            // Re-check status
            setTimeout(checkWeChatStatus, 1000);
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
        showStep(1);
    }
}

async function useExistingDatabase() {
    showToast('Connecting...', 'info');
    try {
        const res = await fetch('/api/use-existing-db', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast('Connected!', 'success');
            if ($('#success-message')) {
                $('#success-message').textContent = `Found ${data.contact_count || 0} conversations`;
            }
            showStep(3);  // Go to done step
        } else {
            showToast(data.error || 'Failed', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

function browseDatabase() {
    // Create a file input and trigger it
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.db';
    input.onchange = (e) => {
        const file = e.target.files[0];
        if (file) {
            // Get the file path - note: browsers don't give full path for security
            // So we'll show a message to paste the path manually
            showToast('Please paste the full path to your database file', 'info');
        }
    };
    input.click();
}

async function useCustomDatabase() {
    const dbPath = $('#input-db-path').value.trim();
    if (!dbPath) {
        showToast('Enter database path', 'error');
        return;
    }
    showToast('Connecting...', 'info');
    try {
        const res = await fetch('/api/set-database', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ db_path: dbPath })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Connected!', 'success');
            if ($('#success-message')) {
                $('#success-message').textContent = `Found ${data.contact_count || 0} conversations`;
            }
            showStep(3);  // Go to done step
        } else {
            showToast(data.error || 'Not found', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

async function completeSetup() {
    const exePath = $('#input-wechat-exe').value.trim();
    try {
        const res = await fetch('/api/complete-setup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ wechat_exe_path: exePath })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Setup complete!', 'success');
            isInitialized = true;
            $('#setting-db-path').value = data.db_path || '';
            $('#setting-exe-path').value = exePath;
            setTimeout(() => {
                showView('chats');
                loadContacts();
            }, 500);
        } else {
            showToast(data.error || 'Failed', 'error');
        }
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

function resetSetup() {
    // Clear config and go back to setup
    fetch('/api/reset-setup', { method: 'POST' })
        .then(() => {
            isInitialized = false;
            showStep(1);
            showView('setup');
            checkStatus();
            showToast('Setup reset', 'success');
        })
        .catch(() => {
            // Still show setup even if API fails
            isInitialized = false;
            showStep(1);
            showView('setup');
        });
}

function refreshContacts() {
    loadContacts();
    showToast('Refreshed', 'success');
}

// ============================================
// Contacts
// ============================================

async function loadContacts() {
    const list = $('#contacts-list');
    list.innerHTML = '<div class="loading"><span class="spinner"></span>Loading...</div>';
    
    try {
        const res = await fetch('/api/contacts');
        const data = await res.json();
        
        if (data.success && data.contacts.length) {
            contacts = data.contacts;
            renderContacts(contacts);
        } else if (data.success) {
            list.innerHTML = '<div class="loading">No chats found</div>';
        } else {
            list.innerHTML = '<div class="loading">' + (data.error || 'Failed') + '</div>';
        }
    } catch (err) {
        list.innerHTML = '<div class="loading">Error loading</div>';
    }
}

function renderContacts(list) {
    const container = $('#contacts-list');
    container.innerHTML = list.map(c => `
        <div class="contact-item" data-id="${escapeAttr(c.id)}" onclick="selectContact('${escapeAttr(c.id)}')">
            <div class="contact-avatar ${c.type === 'group' ? 'group' : ''}">${c.type === 'group' ? 'G' : 'U'}</div>
            <div class="contact-info">
                <div class="contact-name">${escapeHtml(c.nickname || c.id)}</div>
                <div class="contact-meta">${c.message_count.toLocaleString()} msgs</div>
            </div>
        </div>
    `).join('');
}

function setupSearch() {
    const input = $('#search-contacts');
    if (!input) return;
    input.addEventListener('input', (e) => {
        const q = e.target.value.toLowerCase();
        if (!q) {
            renderContacts(contacts);
            return;
        }
        renderContacts(contacts.filter(c => 
            (c.nickname || '').toLowerCase().includes(q) || c.id.toLowerCase().includes(q)
        ));
    });
}

async function selectContact(id) {
    $$('.contact-item').forEach(item => {
        item.classList.toggle('active', item.dataset.id === id);
    });
    
    currentContact = contacts.find(c => c.id === id);
    if (!currentContact) return;
    
    isGroupChat = currentContact.type === 'group';
    
    $('#chat-header').style.display = 'flex';
    $('#messages-container').style.display = 'block';
    $('.chat-placeholder').style.display = 'none';
    
    const avatar = $('#chat-avatar');
    avatar.textContent = isGroupChat ? 'G' : 'U';
    avatar.style.background = isGroupChat ? 'var(--accent-primary)' : 'var(--bg-tertiary)';
    
    $('#chat-name').textContent = currentContact.nickname || currentContact.id;
    $('#chat-stats').textContent = currentContact.message_count.toLocaleString() + ' messages';
    
    await loadMessages(id);
}

async function loadMessages(id) {
    const list = $('#messages-list');
    list.innerHTML = '<div class="loading"><span class="spinner"></span>Loading...</div>';
    
    try {
        const res = await fetch(`/api/messages/${encodeURIComponent(id)}?limit=500`);
        const data = await res.json();
        
        if (data.success) {
            senderNames = data.senders || {};
            renderMessages(data.messages);
        } else {
            list.innerHTML = '<div class="loading">Failed to load</div>';
        }
    } catch (err) {
        list.innerHTML = '<div class="loading">Error</div>';
    }
}

function renderMessages(messages) {
    const list = $('#messages-list');
    
    if (!messages.length) {
        list.innerHTML = '<div class="loading">No messages</div>';
        return;
    }
    
    list.innerHTML = messages.map(msg => {
        const side = msg.is_sender ? 'sent' : 'received';
        const time = formatTime(msg.time);
        
        // Format message - get both text and any media HTML
        const { text, mediaHtml } = formatMessageWithMedia(msg.content, msg.type, msg.media_path);
        
        // Skip truly empty messages
        if (!text && !mediaHtml) {
            return '';
        }
        
        // Show sender name in group chats
        let senderHtml = '';
        if (isGroupChat && !msg.is_sender && msg.sender) {
            const name = senderNames[msg.sender] || msg.sender;
            senderHtml = `<div class="message-sender">${escapeHtml(name)}</div>`;
        }
        
        const contentHtml = mediaHtml || escapeHtml(text);
        
        return `
            <div class="message ${side}">
                ${senderHtml}
                <div class="message-bubble">${contentHtml}</div>
                <div class="message-time">${time}</div>
            </div>
        `;
    }).filter(x => x).join('');
    
    const container = $('#messages-container');
    container.scrollTop = container.scrollHeight;
}

function formatMessageWithMedia(content, type, mediaPath) {
    if (content === null || content === undefined) return { text: null, mediaHtml: null };
    if (typeof content !== 'string') content = String(content);
    
    // Voice message with audio player
    if (type === 34) {
        if (mediaPath) {
            return {
                text: null,
                mediaHtml: `<div class="message-media"><audio controls src="/api/media/${mediaPath}"></audio></div>`
            };
        }
        if (content.includes('翻译结果：')) {
            const match = content.match(/翻译结果：(.+)/);
            if (match) return { text: '🎤 ' + match[1].trim(), mediaHtml: null };
        }
        return { text: '🎤 Voice message', mediaHtml: null };
    }
    
    // Video
    if (type === 43) {
        if (mediaPath) {
            return {
                text: null,
                mediaHtml: `<div class="message-media"><video controls src="/api/media/${mediaPath}"></video></div>`
            };
        }
        return { text: '🎬 Video', mediaHtml: null };
    }
    
    // Image
    if (type === 3) {
        if (mediaPath) {
            return {
                text: null,
                mediaHtml: `<div class="message-media"><img src="/api/media/${mediaPath}" onclick="window.open(this.src)"></div>`
            };
        }
        return { text: '🖼️ Image', mediaHtml: null };
    }
    
    // Use existing formatMessage for other types
    const text = formatMessage(content, type);
    
    // Check for URLs and make them clickable
    if (text && (text.includes('http://') || text.includes('https://'))) {
        const urlRegex = /(https?:\/\/[^\s<>\[\]]+)/g;
        const linkedText = escapeHtml(text).replace(urlRegex, '<a href="$1" target="_blank" class="message-link-inline">$1</a>');
        return { text: null, mediaHtml: linkedText };
    }
    
    return { text, mediaHtml: null };
}

function formatMessage(content, type) {
    if (content === null || content === undefined) return null;
    if (typeof content !== 'string') content = String(content);
    
    // Voice message
    if (type === 34) {
        if (content.includes('翻译结果：')) {
            const match = content.match(/翻译结果：(.+)/);
            if (match) return '🎤 ' + match[1].trim();
        }
        return '🎤 Voice message';
    }
    
    // VOIP/Call
    if (content.includes('<voipmsg') || content.includes('VoIPBubbleMsg')) {
        if (content.includes('Line busy') || content.includes('not received')) {
            return '📞 Missed call';
        }
        return '📞 Call';
    }
    
    // Image
    if (type === 3) return '🖼️ Image';
    
    // Video  
    if (type === 43) return '🎬 Video';
    
    // Emoji/Sticker
    if (type === 47) return '😀 Sticker';
    
    // System message
    if (type === 10000) {
        let clean = content.replace(/<[^>]+>/g, '').trim();
        return clean || 'System message';
    }
    
    // Revoked
    if (type === 10002) return '⚠️ Message recalled';
    
    // File/Link/App message (type 49)
    if (type === 49) {
        // Reply/Quote message - extract the actual reply text
        if (content.includes('<refermsg>') || content.includes('「')) {
            // Try to find the actual message content (not the quoted part)
            const msgMatch = content.match(/<title>([^<]+)<\/title>/i);
            if (msgMatch) {
                const title = msgMatch[1];
                // If it's a quote format like "Name: quoted text"
                if (title.includes('：') || title.includes(':')) {
                    return title;  // Show the reply as-is
                }
                return title;
            }
        }
        
        // Extract title if available
        const titleMatch = content.match(/<title[^>]*>([^<]+)<\/title>/i);
        if (titleMatch) {
            const title = titleMatch[1];
            // Check if it's a file (has extension)
            if (title.match(/\.(pdf|doc|docx|xls|xlsx|ppt|zip|rar|txt)$/i)) {
                return '📄 ' + title;
            }
            return '🔗 ' + title;
        }
        
        // Mini program
        if (content.includes('weappinfo')) {
            const nameMatch = content.match(/<sourcedisplayname>([^<]+)<\/sourcedisplayname>/i);
            if (nameMatch) return '📱 ' + nameMatch[1];
            return '📱 Mini Program';
        }
        
        // Check for file description
        if (content.includes('<des>')) {
            const desMatch = content.match(/<des>([^<]+)<\/des>/i);
            if (desMatch) {
                const des = desMatch[1].substring(0, 80);
                return '📎 ' + des;
            }
        }
        
        return '📎 Link/File';
    }
    
    // Location
    if (type === 48) return '📍 Location';
    
    // Business card
    if (type === 42) return '👤 Contact card';
    
    // If it's XML but we couldn't parse it
    if (content.startsWith('<?xml') || (content.startsWith('<') && content.includes('</'))) {
        // Try one more time to extract any meaningful text
        const anyTitle = content.match(/<title>([^<]+)<\/title>/i);
        if (anyTitle) return anyTitle[1];
        return '📦 Special message';
    }
    
    // Regular text - return as is
    if (content.trim()) {
        return content;
    }
    
    return null;
}

function formatTime(timeStr) {
    if (!timeStr) return '';
    try {
        const date = new Date(timeStr);
        return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
    } catch {
        return timeStr;
    }
}

// ============================================
// Export
// ============================================

async function exportChat(format) {
    if (!currentContact) {
        showToast('Select a chat first', 'error');
        return;
    }
    
    showToast('Preparing export...', 'info');
    
    try {
        // Get export data from server
        const res = await fetch('/api/export-data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                contact_id: currentContact.id,
                contact_name: currentContact.nickname || currentContact.id,
                format: format
            })
        });
        
        const data = await res.json();
        
        if (!data.success) {
            showToast('Failed: ' + data.error, 'error');
            return;
        }
        
        // File type info
        const types = {
            txt: { ext: '.txt', mime: 'text/plain' },
            html: { ext: '.html', mime: 'text/html' },
            json: { ext: '.json', mime: 'application/json' },
            csv: { ext: '.csv', mime: 'text/csv' }
        };
        
        const fileType = types[format] || types.txt;
        const fileName = (currentContact.nickname || currentContact.id).replace(/[<>:"/\\|?*]/g, '_') + fileType.ext;
        
        // Try native file picker (modern browsers)
        if (window.showSaveFilePicker) {
            try {
                const handle = await window.showSaveFilePicker({
                    suggestedName: fileName,
                    types: [{
                        description: format.toUpperCase() + ' File',
                        accept: { [fileType.mime]: [fileType.ext] }
                    }]
                });
                
                const writable = await handle.createWritable();
                await writable.write(data.content);
                await writable.close();
                
                showToast('Saved successfully!', 'success');
                return;
            } catch (err) {
                if (err.name === 'AbortError') {
                    showToast('Export cancelled', 'info');
                    return;
                }
                // Fall through to download method
            }
        }
        
        // Fallback: download file
        const blob = new Blob([data.content], { type: fileType.mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showToast('Downloaded: ' + fileName, 'success');
        
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
    }
}

async function openFile(filepath) {
    try {
        await fetch('/api/open-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filepath })
        });
    } catch (err) {
        console.error(err);
    }
}

// ============================================
// Exports View
// ============================================

async function loadExports() {
    const grid = $('#exports-list');
    grid.innerHTML = '<div class="loading"><span class="spinner"></span>Loading...</div>';
    
    try {
        const res = await fetch('/api/exports');
        const data = await res.json();
        
        if (data.success && data.exports.length) {
            grid.innerHTML = data.exports.map(exp => `
                <div class="export-card" onclick="openFile('${escapeAttr(exp.path)}')">
                    <div class="export-icon">${exp.format === 'txt' ? '📄' : exp.format === 'json' ? '📋' : '🌐'}</div>
                    <div class="export-name">${escapeHtml(exp.name)}</div>
                    <div class="export-meta">
                        <span>${exp.format.toUpperCase()}</span>
                        <span>${exp.created}</span>
                    </div>
                </div>
            `).join('');
        } else {
            grid.innerHTML = '<div class="no-exports">No exports yet</div>';
        }
    } catch (err) {
        grid.innerHTML = '<div class="loading">Failed to load</div>';
    }
}

async function openExportsFolder() {
    try {
        await fetch('/api/open-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder: 'exports' })
        });
    } catch (err) {
        showToast('Failed', 'error');
    }
}

async function saveSettings() {
    const dbPath = $('#setting-db-path').value.trim();
    const exePath = $('#setting-exe-path').value.trim();
    const exportPath = $('#setting-export-path').value.trim();
    const myWxid = $('#setting-my-wxid').value.trim();
    
    try {
        const res = await fetch('/api/save-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                db_path: dbPath,
                wechat_exe_path: exePath,
                export_path: exportPath,
                wxid: myWxid
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast('Settings saved!', 'success');
            // Reload contacts if database path changed
            if (data.db_changed) {
                loadContacts();
            }
        } else {
            showToast(data.error || 'Failed to save', 'error');
        }
    } catch (err) {
        console.error('Save settings error:', err);
        showToast('Failed to save settings', 'error');
    }
}

function browseForSetting(type) {
    // Due to browser security, we can't get file paths directly
    // Show a message to manually paste the path
    const messages = {
        'db': 'Please paste the full path to your merge_all.db file',
        'exe': 'Please paste the full path to WeChat.exe',
        'export': 'Please paste the full path to your exports folder'
    };
    showToast(messages[type] || 'Paste the path manually', 'info');
}

async function refreshContacts() {
    showToast('Refreshing...', 'info');
    await loadContacts();
    showToast('Contacts refreshed!', 'success');
}

// ============================================
// WeChat Launcher
// ============================================

function setupWechatLauncher() {
    const btn = $('#btn-launch-wechat');
    if (!btn) return;
    btn.addEventListener('click', async () => {
        showToast('Launching...', 'info');
        try {
            const res = await fetch('/api/launch-wechat', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                showToast('WeChat launched!', 'success');
            } else {
                showToast(data.error || 'Failed', 'error');
            }
        } catch (err) {
            showToast('Failed', 'error');
        }
    });
}

// ============================================
// Utils
// ============================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function escapeAttr(text) {
    if (!text) return '';
    return String(text).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

function showToast(message, type = 'info') {
    const container = $('#toast-container');
    const icons = { success: '✓', error: '✗', warning: '!', info: 'i' };
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${icons[type]}</span><span>${escapeHtml(message)}</span>`;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}


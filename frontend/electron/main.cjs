const { app, BrowserWindow, Menu } = require('electron');
const path = require('path');

const DEV_URL = process.env.HR_DEV_URL || 'http://127.0.0.1:5173';

let win = null;

// Remove the default application menu entirely (File/Edit/View/Window/Help).
Menu.setApplicationMenu(null);

function createWindow() {
    win = new BrowserWindow({
        width: 1280,
        height: 860,
        minWidth: 900,
        minHeight: 640,
        title: 'HR CHATBOT',
        backgroundColor: '#E3E3E3',
        autoHideMenuBar: true,
        webPreferences: {
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
            devTools: false,
        },
    });

    // Belt-and-suspenders: kill devtools if anything opens them.
    win.webContents.on('devtools-opened', () => {
        win.webContents.closeDevTools();
    });

    // Block reload/devtools/shortcut keys and the top-level menu shortcuts.
    win.webContents.on('before-input-event', (event, input) => {
        const key = (input.key || '').toLowerCase();
        const ctrl = input.control || input.meta;
        if (input.type === 'keyDown' && ctrl) {
            // Ctrl+R -> explicit reload (menu is hidden, so default accelerator may not fire).
            if (key === 'r') {
                event.preventDefault();
                win.webContents.reload();
                return;
            }
            // Ctrl + / Ctrl - -> zoom in/out, Ctrl 0 -> reset.
            if (key === '=' || key === '+' || key === 'add') {
                event.preventDefault();
                setZoom(win.webContents.getZoomFactor() + 0.1);
                return;
            }
            if (key === '-' || key === 'subtract') {
                event.preventDefault();
                setZoom(win.webContents.getZoomFactor() - 0.1);
                return;
            }
            if (key === '0') {
                event.preventDefault();
                win.webContents.setZoomLevel(0);
                showZoomBadge(100);
                return;
            }
            // F12, Ctrl+Shift+I/J, Ctrl+Shift+C -> block devtools.
            if (input.key === 'F12' ||
                (input.shiftKey && (key === 'i' || key === 'j' || key === 'c')) ||
                key === 'i') {
                event.preventDefault();
            }
        }
    });

    function setZoom(factor) {
        const clamped = Math.min(3.0, Math.max(0.5, factor));
        win.webContents.setZoomFactor(clamped);
        showZoomBadge(clamped * 100);
    }

    function showZoomBadge(pct) {
        win.webContents.executeJavaScript(`(function(){
            var el = document.getElementById('__zoom_badge');
            if (!el) {
                el = document.createElement('div');
                el.id = '__zoom_badge';
                el.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:rgba(0,0,0,.75);color:#fff;padding:6px 16px;border-radius:999px;font:600 14px system-ui;z-index:2147483647;pointer-events:none;opacity:0;transition:opacity .25s;box-shadow:0 4px 14px rgba(0,0,0,.3);';
                document.body.appendChild(el);
            }
            el.textContent = Math.round(${pct}) + '%';
            el.style.opacity = '1';
            clearTimeout(window.__zoomHide);
            window.__zoomHide = setTimeout(function(){ el.style.opacity = '0'; }, 1200);
        })()`).catch(() => {});
    }

    win.loadURL(DEV_URL);
    win.on('closed', () => { win = null; });
}

app.whenReady().then(() => {
    createWindow();
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});

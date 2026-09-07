// Auto-start backend + Vite dev server, then launch Electron.
// `npm run dev` stays the pure web mode; `npm run desktop` opens Electron.
const { spawn, execSync } = require('child_process');
const path = require('path');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');
const BACKEND_DIR = path.resolve(ROOT, '..', 'backend');
const VENV_PYTHON = path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe');
const DEV_PORT = 5173;
const API_PORT = 8000;
const DEV_URL = `http://127.0.0.1:${DEV_PORT}`;
const isWin = process.platform === 'win32';

const children = new Set();
let shuttingDown = false;

function log(tag, msg) {
    console.log(`[${tag}] ${msg}`);
}

// Kill a child process and, on Windows, its whole tree.
function killChild(proc) {
    if (!proc || proc.exitCode !== null) return;
    try {
        if (isWin) {
            execSync(`taskkill /PID ${proc.pid} /T /F`, { stdio: 'ignore' });
        } else {
            proc.kill('SIGKILL');
        }
    } catch {
        try { proc.kill(); } catch { /* ignore */ }
    }
}

function cleanup(signal) {
    if (shuttingDown) return;
    shuttingDown = true;
    log('desktop', `shutting down${signal ? ` (${signal})` : ''}...`);
    for (const proc of children) killChild(proc);
    children.clear();
    // Force exit in case spawned grandchildren outlive us.
    setTimeout(() => { process.exit(0); }, 500);
}

for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK']) {
    process.on(sig, () => cleanup(sig));
}
process.on('exit', () => cleanup('exit'));

function waitFor(port, host, timeoutMs, label) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
        const tick = () => {
            if (shuttingDown) return reject(new Error('shutdown'));
            const req = http.get({ host, port, path: '/', timeout: 1200 }, (res) => {
                res.resume();
                resolve();
            });
            req.on('error', () => {
                req.destroy();
                if (Date.now() - start > timeoutMs) reject(new Error(`Timed out waiting for ${label} on ${host}:${port}`));
                else setTimeout(tick, 400);
            });
            req.on('timeout', () => { req.destroy(); });
        };
        tick();
    });
}

function startBackend() {
    log('backend', 'starting...');
    const proc = spawn(VENV_PYTHON, ['main.py'], {
        cwd: BACKEND_DIR,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
        env: { ...process.env, WEB_CONCURRENCY: process.env.WEB_CONCURRENCY || '2' },
    });
    children.add(proc);
    proc.stdout.on('data', (d) => process.stdout.write(d));
    proc.stderr.on('data', (d) => process.stderr.write(d));
    proc.on('exit', (code) => {
        if (!shuttingDown) log('backend', `exited (code ${code})`);
        children.delete(proc);
    });
    return proc;
}

function startVite() {
    log('vite', 'starting dev server...');
    // Bind 127.0.0.1 + strict port so we never drift host (IPv6 localhost) or port.
    const cmd = isWin
        ? `npm run dev:vite -- --host 127.0.0.1 --port ${DEV_PORT} --strictPort`
        : `npm run dev:vite -- --host 127.0.0.1 --port ${DEV_PORT} --strictPort`;
    const proc = spawn(isWin ? 'cmd.exe' : 'sh', isWin ? ['/d', '/s', '/c', cmd] : ['-c', cmd], {
        cwd: ROOT,
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
        shell: false,
    });
    children.add(proc);
    proc.stdout.on('data', (d) => process.stdout.write(d));
    proc.stderr.on('data', (d) => process.stderr.write(d));
    proc.on('exit', (code) => {
        if (!shuttingDown) log('vite', `exited (code ${code})`);
        children.delete(proc);
    });
    return proc;
}

// Resolve the actual Electron binary path from the electron package.
function electronBinaryPath() {
    const electronApi = require('electron');
    if (typeof electronApi === 'string') return electronApi;
    return electronApi.toString();
}

async function main() {
    // --- Backend on :8000 ---
    try {
        await waitFor(API_PORT, '127.0.0.1', 2500, 'backend');
        log('backend', 'already running.');
    } catch {
        startBackend();
        try {
            await waitFor(API_PORT, '127.0.0.1', 20000, 'backend');
        } catch (e) {
            log('backend', 'failed to start: ' + e.message);
            return cleanup();
        }
        log('backend', 'ready.');
    }

    // --- Vite dev server on :5173 (strict) ---
    let viteReady = false;
    try {
        await waitFor(DEV_PORT, '127.0.0.1', 2500, 'vite');
        log('vite', 'already running on ' + DEV_URL);
        viteReady = true;
    } catch {
        startVite();
        try {
            await waitFor(DEV_PORT, '127.0.0.1', 20000, 'vite');
            viteReady = true;
            log('vite', 'ready.');
        } catch (e) {
            log('vite', 'failed to start: ' + e.message);
            return cleanup();
        }
    }

    if (!viteReady) return cleanup();

    // --- Launch Electron ---
    log('electron', `launching at ${DEV_URL}...`);
    let electronPath;
    try {
        electronPath = electronBinaryPath();
    } catch (e) {
        log('electron', 'electron not installed: ' + e.message);
        return cleanup();
    }
    const mainFile = path.join(ROOT, 'electron', 'main.cjs');
    const child = spawn(electronPath, [mainFile], {
        cwd: ROOT,
        stdio: 'inherit',
        env: { ...process.env, HR_DEV_URL: DEV_URL },
        windowsHide: false,
    });
    children.add(child);
    child.on('exit', (code) => {
        children.delete(child);
        if (!shuttingDown) {
            log('electron', `closed (code ${code})`);
            cleanup();
        }
    });
    child.on('error', (err) => {
        log('electron', 'failed to launch: ' + err.message);
        cleanup();
    });
}

main();

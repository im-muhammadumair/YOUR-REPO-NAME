// Auto-start backend + Vite dev server for web mode.
// `npm run dev` runs this; `npm run desktop` additionally launches Electron.
const { spawn, execSync } = require('child_process');
const path = require('path');
const http = require('http');

const ROOT = path.resolve(__dirname, '..');
const BACKEND_DIR = path.resolve(ROOT, '..', 'backend');
const VENV_PYTHON = path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe');
const DEV_PORT = 5173;
const API_PORT = 8000;
const DEV_HOST = '0.0.0.0'; // bind all interfaces so LAN users can connect
const DEV_URL = `http://127.0.0.1:${DEV_PORT}`;
const isWin = process.platform === 'win32';

const children = new Set();
let shuttingDown = false;

function log(tag, msg) {
    console.log(`[${tag}] ${msg}`);
}

// Best-effort LAN IP so other devices on the network can open the app.
function lanIp() {
    const os = require('os');
    const ifaces = os.networkInterfaces();
    for (const name of Object.keys(ifaces)) {
        for (const iface of ifaces[name] || []) {
            if (iface.family === 'IPv4' && !iface.internal) {
                return iface.address;
            }
        }
    }
    return '127.0.0.1';
}

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
    log('dev', `shutting down${signal ? ` (${signal})` : ''}...`);
    for (const proc of children) killChild(proc);
    children.clear();
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
    const cmd = `npm run dev:vite -- --host ${DEV_HOST} --port ${DEV_PORT} --strictPort`;
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

async function main() {
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

    try {
        await waitFor(DEV_PORT, '127.0.0.1', 2500, 'vite');
        log('vite', 'already running on ' + DEV_URL);
    } catch {
        startVite();
        try {
            await waitFor(DEV_PORT, '127.0.0.1', 20000, 'vite');
            log('vite', 'ready.');
        } catch (e) {
            log('vite', 'failed to start: ' + e.message);
            return cleanup();
        }
    }

    const ip = lanIp();
    const netUrl = `http://${ip}:${DEV_PORT}`;
    console.log('');
    console.log('  MTM HR CHATBOT is running:');
    console.log(`  Local:   ${DEV_URL}/`);
    console.log(`  Network: ${netUrl}/`);
    console.log('  Share the Network link with anyone on the same Wi-Fi.');
    console.log('  Press Ctrl+C to stop.');
    log('dev', 'ready.');
}

main();

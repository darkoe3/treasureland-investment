// Chromium clamps small headless windows; CDP emulation sets the actual CSS viewport.
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep, basename } from 'node:path';
export async function executeChromium(chrome, args) {
  const width = Number(args.find((arg) => arg.startsWith('--window-size='))?.split('=')[1].split(',')[0] || 1440);
  const target = args.at(-1);
  const folder = await mkdtemp(join(tmpdir(), 'tl-chromium-viewport-'));
  const child = spawn(chrome, ['--headless', '--disable-gpu', '--no-sandbox', '--remote-debugging-port=0', '--no-first-run', `--user-data-dir=${folder}`, 'about:blank'], { windowsHide: true });
  let socket;
  try {
    const endpoint = await new Promise((resolve, reject) => {
      let stderr = '';
      const timer = setTimeout(() => reject(new Error('Chromium startup timed out')), 15000);
      child.on('error', (error) => { clearTimeout(timer); reject(error); });
      child.stderr.on('data', (chunk) => { stderr += chunk; const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) { clearTimeout(timer); resolve(match[1]); } });
    });
    socket = new WebSocket(endpoint);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let id = 0; const pending = new Map();
    socket.onmessage = ({ data }) => { const result = JSON.parse(data); const item = pending.get(result.id); if (item) { pending.delete(result.id); clearTimeout(item.timer); if (result.error) item.reject(new Error(result.error.message)); else item.resolve(result.result); } };
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => { const callId = ++id; const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 15000); pending.set(callId, { resolve, reject, timer }); socket.send(JSON.stringify({ id: callId, method, params, ...(sessionId ? { sessionId } : {}) })); });
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: false }, sessionId);
    await send('Page.navigate', { url: target }, sessionId);
    const { result } = await send('Runtime.evaluate', { expression: "new Promise(resolve => { const read = () => { if (document.querySelector('#layout-result')) resolve(document.documentElement.outerHTML); else setTimeout(read, 20); }; read(); })", awaitPromise: true, returnByValue: true }, sessionId);
    return { stdout: result.value };
  } finally {
    socket?.close(); child.kill();
    await new Promise((resolve) => { if (child.exitCode !== null) resolve(); else child.once('exit', resolve); });
    // This directory was created by this helper beneath the OS temp directory.
    if (!resolve(folder).startsWith(resolve(tmpdir()) + sep) || !basename(folder).startsWith('tl-chromium-viewport-')) throw new Error('Unexpected temporary directory');
    await rm(folder, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }).catch(() => {});
  }
}

import { executeChromium } from "./chromium-viewport.mjs";
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, writeFile, unlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
const chrome = process.env.CHROME_HEADLESS_PATH;
if (!chrome) throw new Error('Set CHROME_HEADLESS_PATH to Chromium.');
const chunks = new URL('../.next/static/chunks/', import.meta.url);
const css = (await Promise.all((await readdir(chunks)).filter((name) => name.endsWith('.css')).map((name) => readFile(new URL(name, chunks), 'utf8')))).join('\n');
const folder = await mkdtemp(join(tmpdir(), 'audit-profile-layout-'));
const execute = executeChromium;
const row = { id: 1, actor: 'A'.repeat(255), actor_role: 'SUPER_ADMIN', created_at: '2026-11-13T10:00:00Z', action_label: 'Profile updated', model_name: 'User', agency_name: 'B'.repeat(120), object_id: '1', result: 'SUCCESS', description: 'Profile updated', metadata: { before: {}, after: { changed_fields: ['full_name'] } } };
for (const mode of ['profile', 'audit', 'detail']) {
  const name = mode === 'profile' ? 'ProfileClient' : 'AuditLogClient';
  const source = await readFile(new URL(`../components/${name}.js`, import.meta.url), 'utf8');
  const compiled = require('next/dist/build/swc').transformSync(source, { filename: `${name}.js`, jsc: { parser: { syntax: 'ecmascript', jsx: true }, transform: { react: { runtime: 'automatic' } } }, module: { type: 'commonjs' } }).code;
  const states = mode === 'profile' ? [{ full_name: 'A'.repeat(255), email: 'b'.repeat(150) + '@example.com', role: 'ACCOUNTANT', agencies: [{ name: 'C'.repeat(120) }], is_active: true }, 'Display Name', { current_password: '', new_password: '', confirm_password: '' }, {}, '', false, false] : [{}, '', 1, { count: 1, results: [row] }, false, false, '', mode === 'detail' ? row : null];
  let index = 0; const mod = { exports: {} };
  vm.runInNewContext(compiled, { exports: mod.exports, module: mod, require(name) {
    if (name === 'react') return { ...React, useEffect() {}, useState() { return [states[index++], () => {}]; } };
    if (name === 'next/navigation') return { useRouter: () => ({}) };
    if (name.includes('client-api')) return {};
    return require(name);
  } });
  const markup = renderToStaticMarkup(React.createElement(mod.exports.default));
  const filename = join(folder, `${mode}.html`);
  await writeFile(filename, `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><div class="dashboard-frame"><aside class="dashboard-sidebar">Treasureland</aside><div class="dashboard-main"><main class="dashboard-content">${markup}</main></div></div><script>${mode === 'detail' ? "document.querySelector('dialog').showModal();" : ''}const r={width:innerWidth,page:document.documentElement.scrollWidth,component:document.querySelector('.audit-profile-page').getBoundingClientRect().width,overflow:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth && !e.closest('.audit-table-scroll')).map(e=>[e.tagName,e.className,e.getBoundingClientRect().width])};document.body.insertAdjacentHTML('beforeend','<pre id="layout-result">'+JSON.stringify(r)+'</pre>')</script>`);
  for (const width of [390, 768, 1440]) {
    const { stdout } = await execute(chrome, ['--headless', '--disable-gpu', '--no-sandbox', `--window-size=${width},900`, '--dump-dom', pathToFileURL(filename).href], { windowsHide: true, maxBuffer: 5 * 1024 * 1024 });
    const metrics = JSON.parse(stdout.match(/<pre id="layout-result">(\{[^<]+\})<\/pre>/)[1]);
    assert.equal(metrics.width, width); assert.ok(metrics.page <= width && metrics.component <= width, `${mode}: ${JSON.stringify(metrics)}`);
    console.log(`${mode} ${width}px: no viewport overflow`);
  }
  await unlink(filename);
}

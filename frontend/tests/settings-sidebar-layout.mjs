// Uses real compiled components and production CSS, with only services mocked.
import { executeChromium } from './chromium-viewport.mjs';
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
const folder = await mkdtemp(join(tmpdir(), 'settings-sidebar-layout-'));
async function compile(name, states) {
  const source = await readFile(new URL(`../components/${name}.js`, import.meta.url), 'utf8');
  const code = require('next/dist/build/swc').transformSync(source, { filename: `${name}.js`, jsc: { parser: { syntax: 'ecmascript', jsx: true }, transform: { react: { runtime: 'automatic' } } }, module: { type: 'commonjs' } }).code;
  let index = 0;
  const mod = { exports: {} };
  vm.runInNewContext(code, { module: mod, exports: mod.exports, require(id) {
    if (id === 'react') return { ...React, useEffect() {}, useState() { return [states[index++], () => {}]; } };
    if (id === 'next/navigation') return { usePathname: () => '/dashboard/settings' };
    if (id === 'next/link') return { __esModule: true, default: ({ children, ...props }) => React.createElement('a', props, children) };
    if (id === './BrandLogo') return { __esModule: true, default: Brand };
    if (id === 'next/image') return { __esModule: true, default: ({ priority: _priority, ...props }) => React.createElement('img', props) };
    if (id === './LogoutButton') return { __esModule: true, default: () => React.createElement('button', { className: 'icon-text-button ghost' }, 'Logout') };
    if (id.includes('client-api') || id === './AccessDenied') return {};
    return require(id);
  } });
  return mod.exports.default;
}
const Brand = await compile('BrandLogo', []);
const record = { display_name: 'O'.repeat(160), address: 'A'.repeat(500), telephone: '+234 12345678', contact_email: 'office@example.com', receipt_heading: 'Receipt', receipt_footer: 'F'.repeat(500), timezone: 'Africa/Lagos', date_format: 'YYYY-MM-DD', financial_policy: { currency: 'NGN', currency_name: 'Nigerian Naira', currency_symbol: '₦', commission_rate: '0.02' }, system_information: { application: 'Treasureland Investment Management System', settings_version: 1 } };
for (const [width, height] of [[1366, 600], [1280, 720], [1024, 600], [768, 600], [390, 640], [320, 568]]) {
  const mobile = width <= 980;
  const Shell = await compile('DashboardShell', [mobile]);
  const Settings = await compile('SettingsClient', [record, record, true, false, {}, '', false, 0]);
  const markup = renderToStaticMarkup(React.createElement(Shell, { user: { role: 'SUPER_ADMIN', full_name: 'Admin' } }, React.createElement(Settings)));
  const filename = join(folder, `${width}-${height}.html`);
  await writeFile(filename, `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style>${markup}<script>
    const mobile = ${mobile};
    const dialog = document.querySelector('dialog');
    if (mobile) dialog.showModal();
    const sidebar = document.querySelector(mobile ? '.mobile-drawer' : '.dashboard-sidebar');
    const nav = sidebar.querySelector('nav');
    const links = [...nav.querySelectorAll('a')];
    const visible = e => { const r=e.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight+1; };
    const reachable = links.map(link => { link.focus(); return document.activeElement === link && visible(link); });
    const settings = links.find(e=>e.textContent==='Settings');
    const profile = links.find(e=>e.textContent==='My Profile');
    const scrolled = nav.scrollTop > 0;
    const logout = sidebar.querySelector('button:last-child'); logout.focus();
    const logoutVisible = visible(logout);
    if (!mobile) window.scrollTo(0,1000);
    const pinned = Math.abs(sidebar.getBoundingClientRect().top) < 1;
    const result = { width: innerWidth, height: innerHeight, page: document.documentElement.scrollWidth, reachable, scrolled, scrollable: getComputedStyle(nav).overflowY === 'auto', settings: !!settings, profile: !!profile, active: settings.getAttribute('aria-current'), logoutVisible, pinned, dialog: !mobile || dialog.matches(':modal') };
    if (mobile) dialog.close();
    result.contentWidth = document.documentElement.scrollWidth;
    document.body.insertAdjacentHTML('beforeend','<pre id="layout-result">'+JSON.stringify(result)+'</pre>');
  </script>`);
  const { stdout } = await executeChromium(chrome, [`--window-size=${width},${height}`, pathToFileURL(filename).href]);
  const metrics = JSON.parse(stdout.match(/<pre id="layout-result">(\{[^<]+\})<\/pre>/)[1]);
  assert.equal(metrics.width, width); assert.equal(metrics.height, height);
  assert.ok(metrics.page <= width && metrics.contentWidth <= width, JSON.stringify(metrics));
  for (const key of ['scrolled', 'scrollable', 'settings', 'profile', 'logoutVisible', 'pinned', 'dialog']) assert.equal(metrics[key], true, `${key}: ${JSON.stringify(metrics)}`);
  assert.ok(metrics.reachable.every(Boolean), JSON.stringify(metrics));
  assert.equal(metrics.active, 'page');
  console.log(`${width}x${height}: every navigation link focusable and visible, independent scrolling, pinned sidebar, logout and responsive settings reachable`);
  await unlink(filename);
}

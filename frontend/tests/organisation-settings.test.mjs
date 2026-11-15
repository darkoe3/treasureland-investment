import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';
import { isAllowedBackendProxyPath, isBinaryBackendProxyPath } from '../lib/controlled-proxy-path.js';

const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost', pretendToBeVisual: true });
globalThis.window = dom.window; globalThis.document = dom.window.document; globalThis.HTMLElement = dom.window.HTMLElement; globalThis.IS_REACT_ACT_ENVIRONMENT = true;
window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
window.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new window.Event('close')); };
const React = await import('react');
const { createRoot } = await import('react-dom/client');
const require = createRequire(import.meta.url);
let requests, handler, root, container;
async function component(name) {
  const source = await readFile(new URL(`../components/${name}.js`, import.meta.url), 'utf8');
  const compiled = require('next/dist/build/swc').transformSync(source, { filename: `${name}.js`, jsc: { parser: { syntax: 'ecmascript', jsx: true }, transform: { react: { runtime: 'automatic' } }, target: 'es2020' }, module: { type: 'commonjs' } }).code;
  const mod = { exports: {} };
  vm.runInNewContext(compiled, { exports: mod.exports, module: mod, URLSearchParams, URL, document, require(name) {
    if (name === 'next/link') return { __esModule: true, default: ({ children, ...props }) => React.createElement('a', props, children) };
    if (name === './AccessDenied') return { __esModule: true, default: () => React.createElement('p', null, 'Access denied') };
    if (name === './BrandLogo') return { __esModule: true, default: () => React.createElement('div', null, 'Treasureland') };
    if (name === './LogoutButton') return { __esModule: true, default: () => React.createElement('button', null, 'Logout') };
    if (name === 'next/navigation') return { usePathname: () => '/dashboard/settings', useRouter: () => ({ refresh() {} }) };
    if (name.includes('client-api')) return { apiPath: (path) => path, clientRequest: async (path, options) => { requests.push({ path, options }); return handler(path, options); }, clientDownload: async (path) => { requests.push({ path }); return handler(path); } };
    return require(name);
  } });
  return mod.exports.default;
}
const Settings = await component('SettingsClient');
const settings = { display_name: 'Treasureland', address: '', telephone: '', contact_email: '', receipt_heading: 'Payment Receipt', receipt_footer: 'Thank you', timezone: 'Africa/Lagos', date_format: 'YYYY-MM-DD', financial_policy: { currency_name: 'Nigerian Naira', currency: 'NGN', currency_symbol: '?', commission_rate: '0.02' }, system_information: { application: 'Treasureland Investment Management System', settings_version: 1 } };
async function mount() { requests = []; container = document.createElement('div'); document.body.append(container); root = createRoot(container); await React.act(async () => root.render(React.createElement(Settings))); }
async function cleanup() { await React.act(async () => root.unmount()); container.remove(); }
function button(text) { return [...container.querySelectorAll('button')].find((node) => node.textContent.includes(text)); }
async function click(text) { await React.act(async () => button(text).click()); }
async function type(value) { const node = container.querySelector('#setting-display_name'); await React.act(async () => { Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(node, value); node.dispatchEvent(new window.Event('input', { bubbles: true })); }); }
async function submit() { await React.act(async () => container.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))); }

test('settings edit, validation, network failure, duplicate prevention, success and cancel', async () => {
  let mode = 'validation', resolve;
  handler = async (path, options) => {
    if (!options) return settings;
    if (mode === 'validation') throw { status: 400, payload: { display_name: ['Invalid organisation.'] } };
    if (mode === 'network') throw new TypeError('Network unavailable');
    return new Promise((done) => { resolve = done; });
  };
  await mount();
  assert.equal(container.querySelector('[role="status"].form-success'), null);
  assert.equal(container.querySelector('input').disabled, true);
  assert.ok(container.textContent.includes('2%'));
  assert.ok(container.textContent.includes('Historical Daily Sheets retain'));
  assert.equal(container.querySelector('a').getAttribute('href'), '/dashboard/profile');
  await click('Edit settings');
  assert.ok(button('Save settings'));
  assert.ok(button('Cancel'));
  assert.equal(container.querySelector('#setting-display_name').disabled, false);
  await type('Edited'); await submit();
  assert.ok(container.textContent.includes('Invalid organisation.'));
  assert.equal(container.querySelector('input').getAttribute('aria-invalid'), 'true');
  mode = 'network'; await submit();
  assert.ok(container.textContent.includes('Your changes are preserved'));
  assert.equal(container.querySelector('input').value, 'Edited');
  mode = 'success'; await submit(); await submit();
  assert.equal(requests.filter((r) => r.options?.method === 'PATCH').length, 3);
  assert.equal(button('Saving').disabled, true);
  assert.deepEqual(JSON.parse(requests.at(-1).options.body), { display_name: 'Edited' });
  await React.act(async () => resolve({ ...settings, display_name: 'Edited' }));
  assert.ok(container.textContent.includes('Settings saved successfully.'));
  await click('Edit settings');
  assert.equal(container.querySelector('[role="status"].form-success'), null);
  await type('Discard'); await click('Cancel');
  assert.equal(container.querySelector('input').value, 'Edited');
  assert.ok(button('Edit settings'));
  assert.equal(button('Save settings'), undefined);
  assert.equal(container.querySelector('#setting-display_name').disabled, true);
  assert.equal(container.querySelector('[role="status"].form-success'), null);
  await cleanup();
  await mount();
  assert.equal(container.querySelector('[role="status"].form-success'), null);
  await cleanup();
});

test('load failure can retry and permission loss shows access denied', async () => {
  let fail = true;
  handler = async () => { if (fail) throw new Error('Offline'); return settings; };
  await mount(); assert.ok(button('Retry')); fail = false; await click('Retry'); assert.ok(button('Edit settings'));
  handler = async () => { throw { status: 403 }; };
  await click('Edit settings'); await type('Denied'); await submit();
  assert.ok(container.textContent.includes('Access denied')); assert.equal(container.querySelectorAll('input').length, 0);
  await cleanup();
});

test('controlled settings proxy accepts only dedicated GET/PATCH route', () => {
  for (const method of ['GET', 'PATCH']) assert.equal(isAllowedBackendProxyPath('organisation-settings/', method), true);
  for (const method of ['POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS']) assert.equal(isAllowedBackendProxyPath('organisation-settings/', method), false);
  for (const path of ['organisation-settings/1', 'organisation-settings/history', 'configuration', 'settings']) assert.equal(isAllowedBackendProxyPath(path, 'PATCH'), false);
  assert.equal(isBinaryBackendProxyPath('organisation-settings/'), false);
});

test('settings route restricts accountants while profile remains authenticated', async () => {
  const route = await readFile(new URL('../app/dashboard/settings/page.js', import.meta.url), 'utf8');
  assert.match(route, /user.role !== "SUPER_ADMIN"/); assert.match(route, /<AccessDenied/);
  const profile = await readFile(new URL('../app/dashboard/profile/page.js', import.meta.url), 'utf8');
  assert.match(profile, /requireDashboardUser/); assert.doesNotMatch(profile, /SUPER_ADMIN/);
});


test('mobile menu opens, closes, restores focus and preserves role navigation', async () => {
  const Shell = await component('DashboardShell');
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  await React.act(async () => root.render(React.createElement(Shell, { user: { role: 'SUPER_ADMIN', full_name: 'Admin' } })));
  const trigger = container.querySelector('[aria-label="Open navigation"]');
  await React.act(async () => trigger.click());
  assert.ok(container.querySelector('dialog').open);
  assert.equal(document.body.style.overflow, 'hidden');
  assert.equal(trigger.getAttribute('aria-expanded'), 'true');
  const links = [...container.querySelectorAll('dialog nav a')];
  assert.ok(links.some(link => link.textContent === 'Settings'));
  assert.ok(links.some(link => link.textContent === 'My Profile'));
  await React.act(async () => container.querySelector('[aria-label="Close navigation"]').click());
  assert.equal(container.querySelector('dialog'), null); assert.equal(document.activeElement, trigger);
  assert.equal(document.body.style.overflow, '');
  await React.act(async () => trigger.click());
  await React.act(async () => container.querySelector('dialog').dispatchEvent(new window.Event('cancel', { bubbles: true })));
  assert.equal(container.querySelector('dialog'), null);
  await React.act(async () => root.render(React.createElement(Shell, { user: { role: 'ACCOUNTANT', full_name: 'Accountant' } })));
  assert.equal(container.querySelector('a[href="/dashboard/settings"]'), null);
  assert.ok(container.querySelector('a[href="/dashboard/profile"]'));
  await cleanup();
});

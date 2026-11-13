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
    if (name === 'next/navigation') return { useRouter: () => ({ refresh() {} }) };
    if (name.includes('client-api')) return { apiPath: (path) => path, clientRequest: async (path, options) => { requests.push({ path, options }); return handler(path, options); }, clientDownload: async (path) => { requests.push({ path }); return handler(path); } };
    return require(name);
  } });
  return mod.exports.default;
}
const Profile = await component('ProfileClient'); const Audit = await component('AuditLogClient');
const profile = { id: 1, full_name: 'Original Name', email: 'a@example.com', role: 'ACCOUNTANT', agencies: [], is_active: true };
const event = { id: 1, actor: 'Admin', actor_role: 'SUPER_ADMIN', action_label: 'Profile updated', model_name: 'User', object_id: '1', result: 'SUCCESS', description: 'Profile updated', created_at: '2026-11-13T10:00:00Z', metadata: { before: {}, after: { changed_fields: ['full_name'] } } };
async function mount(Component) { requests = []; container = document.createElement('div'); document.body.append(container); root = createRoot(container); await React.act(async () => root.render(React.createElement(Component))); }
async function cleanup() { await React.act(async () => root.unmount()); container.remove(); }
function button(text) { return [...container.querySelectorAll('button')].find((node) => node.textContent.includes(text)); }
async function click(text) { await React.act(async () => button(text).click()); }
async function type(label, value) { const node = [...container.querySelectorAll('label')].find((node) => node.textContent.startsWith(label)).querySelector('input'); await React.act(async () => { Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(node, value); node.dispatchEvent(new window.Event('input', { bubbles: true })); }); }
async function submit(index) { await React.act(async () => container.querySelectorAll('form')[index].dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }))); }

test('profile retains invalid edits, displays field errors, blocks duplicate submits and announces success', async () => {
  let fail = true, resolve;
  handler = async (path, options) => { if (!options) return profile; if (fail) throw { payload: { full_name: ['Invalid name.'] } }; return new Promise((done) => { resolve = done; }); };
  await mount(Profile); await type('Full name', 'New Name'); await submit(0);
  assert.ok(container.textContent.includes('Invalid name.')); assert.equal(container.querySelector('input').value, 'New Name');
  fail = false; await submit(0); await submit(0);
  assert.equal(requests.filter((r) => r.options?.method === 'PATCH').length, 2);
  assert.equal(button('Saving').disabled, true);
  await React.act(async () => resolve({ ...profile, full_name: 'New Name' }));
  assert.ok(container.textContent.includes('Profile updated successfully.'));
  assert.ok(!container.textContent.includes('Invalid name.'));
  assert.equal(container.querySelectorAll('input[type=email]').length, 0);
  await cleanup();
});

test('password errors preserve values; success clears form and offers re-login', async () => {
  let fail = true;
  handler = async (path, options) => { if (!options) return profile; if (path.includes('change-password') && fail) throw { payload: { current_password: ['Incorrect password.'] } }; return { reauthenticate: true }; };
  await mount(Profile); await type('Current password', 'wrong'); await type('New password', 'New-pass-123!'); await type('Confirm new password', 'New-pass-123!'); await submit(1);
  assert.ok(container.textContent.includes('Incorrect password.')); assert.equal(container.querySelector('input[type=password]').value, 'wrong');
  fail = false; await submit(1); assert.ok(container.textContent.includes('Password changed.')); assert.equal(container.querySelectorAll('input[type=password]').length, 0); assert.equal(container.querySelector('a').getAttribute('href'), '/login');
  await cleanup();
});

test('audit uses backend filters and pagination, shows detail and clears filters', async () => {
  handler = async (path) => path === 'audit-logs/1/' ? event : { count: 26, results: [event], previous: path.includes('page=2') ? 'previous' : null, next: path.includes('page=2') ? null : 'next' };
  await mount(Audit); await type('Search', 'Admin'); await type('Agency ID', '2'); await submit(0);
  assert.ok(requests.at(-1).path.includes('search=Admin&agency=2&page=1'));
  await click('Next'); assert.ok(requests.at(-1).path.endsWith('page=2'));
  await click('View details'); assert.ok(container.querySelector('dialog').open); assert.ok(container.querySelector('dialog').textContent.includes('full_name'));
  await click('Close'); assert.equal(container.querySelector('dialog').open, false);
  await click('Clear filters'); assert.equal(container.querySelector('input[type=search]').value, ''); assert.equal(requests.at(-1).path, 'audit-logs/?&page=1');
  await cleanup();
});

test('audit surfaces backend failures without exposing stale results', async () => {
  handler = async () => { throw new Error('Access denied.'); };
  await mount(Audit); assert.ok(container.querySelector('[role=alert]').textContent.includes('Access denied.')); assert.equal(container.querySelector('table'), null); await cleanup();
});

test('proxy allows exact self-service and read-only audit routes', () => {
  for (const method of ['GET', 'PATCH']) assert.equal(isAllowedBackendProxyPath('profile/', method), true);
  assert.equal(isAllowedBackendProxyPath('profile/change-password/', 'POST'), true);
  assert.equal(isBinaryBackendProxyPath('audit-logs/export/?agency=1', 'GET'), true);
  for (const path of ['audit-logs/1/', 'audit-logs/export/']) {
    assert.equal(isAllowedBackendProxyPath(path, 'GET'), true);
    for (const method of ['POST', 'PATCH', 'PUT', 'DELETE']) assert.equal(isAllowedBackendProxyPath(path, method), false);
  }
  for (const [path, method] of [['profile/1', 'PATCH'], ['profile', 'POST'], ['profile/change-password', 'GET'], ['profile/change-password/1', 'POST'], ['profile/role', 'PATCH'], ['audit-logs/export/1', 'GET']]) assert.equal(isAllowedBackendProxyPath(path, method), false);
});

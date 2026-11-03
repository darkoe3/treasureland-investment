// Optional real Chromium layout and keyboard-focus checks with synthetic data only.
// Build first, then set CHROME_HEADLESS_PATH to a local Chromium executable.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, readFile, readdir, writeFile, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as operations from "../lib/payment-operations.js";

const chrome = process.env.CHROME_HEADLESS_PATH;
if (!chrome) throw new Error("Set CHROME_HEADLESS_PATH to a local Chromium executable.");
const require = createRequire(import.meta.url);
const source = await readFile(new URL("../components/PaymentNumberPicker.js", import.meta.url), "utf8");
const compiled = require("next/dist/build/swc").transformSync(source, { filename: "PaymentNumberPicker.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
const chunks = new URL("../.next/static/chunks/", import.meta.url);
const css = (await Promise.all((await readdir(chunks)).filter((name) => name.endsWith(".css")).map((name) => readFile(new URL(name, chunks), "utf8")))).join("\n");
const row = { id: 1, payer: 1, payer_name: "Long payer name for keyboard and mobile layout verification", sub_agent_number: "S".repeat(80), terminal_number: "T".repeat(80), agency: 1, agency_name: "Agency", is_active: true, selectable: true, outstanding_balance: "123456789.00", open_obligation_count: 100 };
const folder = await mkdtemp(join(tmpdir(), "payment-number-layout-"));
const execute = promisify(execFile);
for (const mode of ["search", "quick", "success"]) {
  let index = 0;
  const search = mode === "search" ? "SEARCH" : "NONE";
  const states = [search, 1, mode === "quick" ? { sub_agent_number: "", terminal_number: "", confirmed: false } : null, "Payer", 1, null, "", mode === "success", false,
    { rows: mode === "search" ? [row] : [], count: mode === "search" ? 1 : 0, loading: false, error: "", key: `agencies/1/payment-numbers/|${search}|1` },
    { rows: [{ id: 1, payer_name: row.payer_name }], count: 1, loading: false, error: "", key: "payment-payers/?agency=1&active=true|Payer|1" }];
  const mod = { exports: {} };
  vm.runInNewContext(compiled, { module: mod, exports: mod.exports, require(name) {
    if (name === "react") return { ...React, useEffect() {}, useRef() { return { current: null }; }, useState() { return [states[index++], () => {}]; } };
    if (name === "react/jsx-runtime") return require(name);
    if (name === "next/link") return function TestLink({ href, children }) { return React.createElement("a", { href }, children); };
    if (name.includes("client-api")) return {};
    if (name.includes("payment-operations")) return operations;
    throw new Error(name);
  } });
  const markup = renderToStaticMarkup(mod.exports.default({ agency: 1, agencyName: "Agency", user: { role: "SUPER_ADMIN" }, value: mode === "success" ? row : null, onSelect() {}, disabled: false }));
  for (const width of [390, 768, 1440]) {
    const filename = join(folder, `${mode}-${width}.html`);
    const child = `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><dialog class="payment-dialog"><form>${markup}</form></dialog>`;
    await writeFile(filename, `<!doctype html><iframe id="frame" style="width:${width}px;height:900px;border:0"></iframe><script>
      const frame=document.getElementById('frame');
      frame.onload=()=>{const doc=frame.contentDocument,dialog=doc.querySelector('dialog');dialog.showModal();const controls=[...dialog.querySelectorAll('input,button,a')].filter(e=>!e.disabled);let focusable=true;for(const el of controls){el.focus();focusable=focusable&&doc.activeElement===el;}const success=dialog.querySelector('[tabindex="-1"]');if(success){success.focus();focusable=focusable&&doc.activeElement===success;}const r={width:frame.contentWindow.innerWidth,page:doc.documentElement.scrollWidth,dialog:dialog.getBoundingClientRect().width,content:dialog.scrollWidth,client:dialog.clientWidth,modal:dialog.matches(':modal'),focusable};document.body.insertAdjacentHTML('beforeend','<pre id="layout-result">'+JSON.stringify(r)+'</pre>');};frame.srcdoc=${JSON.stringify(child)};
    </script>`);
    const { stdout } = await execute(chrome, ["--headless", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=1000", "--dump-dom", pathToFileURL(filename).href], { windowsHide: true, maxBuffer: 5 * 1024 * 1024 });
    const match = stdout.match(/<pre id="layout-result">(\{[^<]+\})<\/pre>/);
    assert.ok(match, "Browser produced layout results");
    const metrics = JSON.parse(match[1]);
    assert.equal(metrics.width, width);
    assert.ok(metrics.page <= width && metrics.dialog <= width && metrics.content <= metrics.client + 1, `${mode}: ${JSON.stringify(metrics)}`);
    assert.ok(metrics.modal && metrics.focusable, `${mode}: modal controls accept keyboard focus`);
    console.log(`${mode} ${width}px: no overflow; modal controls and success feedback focusable`);
    await unlink(filename);
  }
}

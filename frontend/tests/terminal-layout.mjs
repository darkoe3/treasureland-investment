// Optional real Chromium layout check: build first, then set CHROME_HEADLESS_PATH.
// Uses the actual React component and compiled application CSS with synthetic data.
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
import * as api from "../lib/client-api.js";
import * as operations from "../lib/terminal-operations.js";

const chrome = process.env.CHROME_HEADLESS_PATH;
if (!chrome) throw new Error("Set CHROME_HEADLESS_PATH to an installed Chromium/headless-shell executable.");
const require = createRequire(import.meta.url);
const { transformSync } = require("next/dist/build/swc");
const source = await readFile(new URL("../components/TerminalNumbersClient.js", import.meta.url), "utf8");
const compiled = transformSync(source, { filename: "TerminalNumbersClient.js", jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
const chunks = new URL("../.next/static/chunks/", import.meta.url);
const css = (await Promise.all((await readdir(chunks)).filter((name) => name.endsWith(".css")).map((name) => readFile(new URL(name, chunks), "utf8")))).join("\n");
const terminal = { id: 1, terminal_number: "000" + "A".repeat(77), sub_agent_number_value: "000" + "B".repeat(77), person_name: "Person with a long name for responsive layout verification", agency_name: "Musa", agency: 1, is_active: true, updated_at: "2026-09-16" };
const batch = { id: 1, agency: 1, status: "PREVIEWED", original_filename: "terminal-register.xlsx", expires_at: "2099-01-01", warnings: [{ message: "Row 2: Numeric identifier may have lost leading zeroes." }], errors: [], preview_payload: { rows: [{ row: 2, ...terminal, name: terminal.person_name, classification: "New" }] } };
const folder = await mkdtemp(join(tmpdir(), "terminal-layout-"));
const execute = promisify(execFile);
for (const mode of ["list", "add", "reassign", "upload"]) {
  let index = 0;
  const states = [[terminal], [], { agency: "", active: "", search: "" }, ["add", "reassign"].includes(mode) ? { mode, item: mode === "reassign" ? terminal : null } : null, { agency: "", person: "", sub_agent_number: "", terminal_number: "", reason: "", confirmed: false, is_active: true }, null, "1", null, mode === "upload" ? batch : null, false, false, "", ""];
  const compiledModule = { exports: {} };
  vm.runInNewContext(compiled, { module: compiledModule, exports: compiledModule.exports, Date, require(name) {
    if (name === "react") return { ...React, useEffect() {}, useState() { return [states[index++], () => {}]; } };
    if (name === "react/jsx-runtime") return require(name);
    if (name === "next/link") return function TestLink({ href, children }) { return React.createElement("a", { href }, children); };
    if (name === "../lib/client-api") return api;
    if (name === "../lib/terminal-operations") return operations;
    throw new Error(name);
  } });
  const markup = renderToStaticMarkup(compiledModule.exports.default({ user: { role: "SUPER_ADMIN" }, agencies: [{ id: 1, name: "Musa" }], uploadPage: mode === "upload" }));
  const filename = join(folder, `${mode}.html`);
  await writeFile(filename, `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><div class="dashboard-frame"><aside class="dashboard-sidebar">Treasureland Investment</aside><div class="dashboard-main"><main class="dashboard-content">${markup}</main></div></div><script>const r={width:innerWidth,page:document.documentElement.scrollWidth,component:document.querySelector('.terminal-register').getBoundingClientRect().width};document.body.insertAdjacentHTML('beforeend','<pre id="layout-result">'+JSON.stringify(r)+'</pre>')</script>`);
  for (const width of [390, 768, 1440]) {
    const { stdout } = await execute(chrome, ["--headless", "--disable-gpu", "--no-sandbox", `--window-size=${width},900`, "--dump-dom", pathToFileURL(filename).href], { windowsHide: true, maxBuffer: 5 * 1024 * 1024 });
    const metrics = JSON.parse(stdout.match(/<pre id="layout-result">(\{[^<]+\})<\/pre>/)[1]);
    assert.equal(metrics.width, width);
    assert.ok(metrics.page <= metrics.width, `${mode} overflow: ${JSON.stringify(metrics)}`);
    assert.ok(metrics.component <= metrics.width, `${mode} component overflow`);
    console.log(`${mode} ${width}px: no page overflow (${metrics.page}px)`);
  }
  await unlink(filename);
}

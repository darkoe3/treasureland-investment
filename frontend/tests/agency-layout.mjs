// Run after npm run build, with CHROME_HEADLESS_PATH pointing to local Chromium.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, readdir, writeFile, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { harness } from "./agency-management.test.mjs";

const chrome = process.env.CHROME_HEADLESS_PATH;
if (!chrome) throw new Error("Set CHROME_HEADLESS_PATH to an installed Chromium executable.");
const chunks = new URL("../.next/static/chunks/", import.meta.url);
const css = (await Promise.all((await readdir(chunks)).filter((name) => name.endsWith(".css")).map((name) => readFile(new URL(name, chunks), "utf8")))).join("\n");
const folder = await mkdtemp(join(tmpdir(), "agency-layout-"));
const execute = promisify(execFile);
for (const mode of ["list", "create", "edit", "deactivate", "reactivate"]) {
  const row = { id: 1, name: "A".repeat(120), code: "B".repeat(40), is_active: true, counts: { editable_daily_sheets: 2 } };
  const ui = harness({ editor: mode === "list" ? null : { mode, row, impact: row.counts } });
  ui.states[0] = [row, { ...row, id: 2, is_active: false }];
  const filename = join(folder, `${mode}.html`);
  await writeFile(filename, `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><div class="dashboard-frame"><aside class="dashboard-sidebar">Treasureland Investment</aside><div class="dashboard-main"><main class="dashboard-content">${ui.html()}</main></div></div><script>const d=document.querySelector('dialog');if(d&&d.querySelector('form'))d.showModal();const r={width:innerWidth,page:document.documentElement.scrollWidth,component:document.querySelector('.agency-management').getBoundingClientRect().width,dialog:d?.open?d.getBoundingClientRect().width:0};document.body.insertAdjacentHTML('beforeend','<pre id="layout-result">'+JSON.stringify(r)+'</pre>')</script>`);
  for (const width of [390, 768, 1440]) {
    const { stdout } = await execute(chrome, ["--headless", "--disable-gpu", "--no-sandbox", `--window-size=${width},900`, "--dump-dom", pathToFileURL(filename).href], { windowsHide: true, maxBuffer: 5 * 1024 * 1024 });
    const metrics = JSON.parse(stdout.match(/<pre id="layout-result">(\{[^<]+\})<\/pre>/)[1]);
    assert.equal(metrics.width, width);
    assert.ok(metrics.page <= width && metrics.component <= width && metrics.dialog <= width, `${mode} overflow: ${JSON.stringify(metrics)}`);
    console.log(`${mode} ${width}px: no viewport expansion`);
  }
  await unlink(filename);
}

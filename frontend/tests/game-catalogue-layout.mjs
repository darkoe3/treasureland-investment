import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rmdir, unlink, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { executeChromium } from "./chromium-viewport.mjs";

const chrome = process.env.CHROME_HEADLESS_PATH;
if (!chrome) throw new Error("Set CHROME_HEADLESS_PATH to a local Chromium executable.");

const require = createRequire(import.meta.url);
const source = await readFile(new URL("../components/GameCatalogue.js", import.meta.url), "utf8");
let stateOverrides = null;
let stateIndex = 0;
const compiled = require("next/dist/build/swc").transformSync(source, {
  filename: "GameCatalogue.js",
  jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } },
  module: { type: "commonjs" },
}).code;
const componentModule = { exports: {} };
const icon = () => null;
const reactWithState = {
  ...require("react"),
  useState(initial) {
    const index = stateIndex++;
    return [stateOverrides && index in stateOverrides ? stateOverrides[index] : (typeof initial === "function" ? initial() : initial), () => {}];
  },
};
vm.runInNewContext(compiled, {
  module: componentModule,
  exports: componentModule.exports,
  require(name) {
    if (name === "react") return reactWithState;
    if (name === "react/jsx-runtime") return require(name);
    if (name === "lucide-react") return { CalendarDays: icon, Edit2: icon, Power: icon, PowerOff: icon, Plus: icon, Save: icon, X: icon };
    if (name.includes("client-api")) return { apiPath: (path) => path, clientRequest: async () => ({}) };
    if (name.includes("game-schedule-operations")) {
      return { WEEKDAYS: [
        { value: 1, label: "Monday" }, { value: 2, label: "Tuesday" },
        { value: 3, label: "Wednesday" }, { value: 4, label: "Thursday" },
        { value: 5, label: "Friday" }, { value: 6, label: "Saturday" },
        { value: 7, label: "Sunday" },
      ] };
    }
    return require(name);
  },
});

const games = Array.from({ length: 10 }, (_, index) => ({
  id: index + 1,
  name: index === 0 ? `Long catalogue game ${"Name ".repeat(8)}` : `Game ${index + 1}`,
  category: index === 0 ? "GHANA" : index === 1 ? "DOUBLE_CHANCE" : "TIMED",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
}));
const markup = renderToStaticMarkup(React.createElement(componentModule.exports.default, {
  games,
  entries: [],
  onRefresh: async () => true,
  onSchedule() {},
}));
stateOverrides = {
  3: { id: 1, name: "Mobile schedule game", category: "TIMED", is_active: false },
  4: {
    name: "Mobile schedule game",
    category: "TIMED",
    is_active: false,
    confirmClearTimes: false,
    assignments: [
      { id: 1, weekday: 1, display_order: "1", is_active: false, closing_time: "", draw_time: "", replace_schedule_id: "" },
      { id: 2, weekday: 2, display_order: "2", is_active: false, closing_time: "", draw_time: "", replace_schedule_id: "" },
    ],
  },
};
stateIndex = 0;
const editorMarkup = renderToStaticMarkup(React.createElement(componentModule.exports.default, {
  games: [{ id: 1, name: "Mobile schedule game", category: "TIMED", is_active: false }],
  entries: [
    { id: 1, game: 1, weekday: 1, weekday_display: "Monday", display_order: 1, category: "TIMED", is_active: false, game_is_active: false },
    { id: 2, game: 1, weekday: 2, weekday_display: "Tuesday", display_order: 2, category: "TIMED", is_active: false, game_is_active: false },
  ],
  onRefresh: async () => true,
}));
stateOverrides = null;
const chunks = new URL("../.next/static/chunks/", import.meta.url);
const css = (await Promise.all(
  (await readdir(chunks)).filter((name) => name.endsWith(".css")).map((name) => readFile(new URL(name, chunks), "utf8")),
)).join("\n");
const folder = await mkdtemp(join(tmpdir(), "game-catalogue-layout-"));

try {
  for (const [width, height] of [[1440, 900], [1366, 600], [390, 844]]) {
    const filename = join(folder, `${width}-${height}.html`);
    const page = `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><div class="dashboard-frame"><aside class="dashboard-sidebar">Sidebar</aside><div class="dashboard-main"><main class="dashboard-content">${markup}${editorMarkup}</main></div></div><script>
      const root=document.querySelector('.game-catalogue'), rows=[...root.querySelectorAll('tbody tr')], buttons=[...root.querySelectorAll('button')];
      const editor=document.querySelector('.game-connected-editor'), editorButtons=[...editor.querySelectorAll('button')], assignments=[...editor.querySelectorAll('.game-assignment')];
      const metrics={width:innerWidth,height:innerHeight,page:document.documentElement.scrollWidth,component:root.getBoundingClientRect().width,rows:rows.length,buttons:buttons.length,buttonRows:[...root.querySelectorAll('.button-row')].map(e=>({width:e.clientWidth,scroll:e.scrollWidth,wrap:getComputedStyle(e).flexWrap})),minButtonHeight:Math.min(...buttons.map(e=>e.getBoundingClientRect().height)),editorWidth:editor.getBoundingClientRect().width,editorScroll:editor.scrollWidth,assignmentWidths:assignments.map(e=>({width:e.clientWidth,scroll:e.scrollWidth})),editorButtonHeight:Math.min(...editorButtons.map(e=>e.getBoundingClientRect().height))};
      document.body.insertAdjacentHTML('beforeend','<pre id="layout-result">'+JSON.stringify(metrics)+'</pre>');
    </script>`;
    await writeFile(filename, page);
    const { stdout } = await executeChromium(chrome, [
      "--headless", "--disable-gpu", "--no-sandbox", `--window-size=${width},${height}`,
      "--dump-dom", pathToFileURL(filename).href,
    ]);
    const match = stdout.match(/<pre id="layout-result">(\{[^<]+\})<\/pre>/);
    assert.ok(match, "Chromium produced catalogue layout metrics");
    const metrics = JSON.parse(match[1]);
    assert.equal(metrics.width, width);
    assert.equal(metrics.height, height);
    assert.ok(metrics.page <= width && metrics.component <= width, JSON.stringify(metrics));
    assert.equal(metrics.rows, games.length);
    assert.ok(metrics.buttons > 0 && metrics.minButtonHeight >= 40, JSON.stringify(metrics));
    assert.ok(metrics.buttonRows.every((row) => row.wrap === "wrap" && row.scroll <= row.width + 1), JSON.stringify(metrics));
    assert.ok(metrics.editorWidth <= width && metrics.editorScroll <= metrics.editorWidth + 1, JSON.stringify(metrics));
    assert.ok(metrics.assignmentWidths.every((row) => row.scroll <= row.width + 1), JSON.stringify(metrics));
    assert.ok(metrics.editorButtonHeight >= 40, JSON.stringify(metrics));
    console.log(`${width}x${height}: catalogue fits viewport and action buttons remain usable`);
    await unlink(filename);
  }
} finally {
  for (const file of await readdir(folder)) await unlink(join(folder, file));
  await rmdir(folder);
}

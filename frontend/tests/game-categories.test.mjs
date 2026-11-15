import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import vm from "node:vm";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as operations from "../lib/game-schedule-operations.js";
import * as phase4 from "../lib/phase4-operations.js";
import * as shapes from "../lib/resource-shapes.js";
const require = createRequire(import.meta.url);
const { transformSync } = require("next/dist/build/swc");
async function renderComponent(name, props, stateOverrides = {}) {
  const source = await readFile(new URL(`../components/${name}.js`, import.meta.url), "utf8");
  const compiled = transformSync(source, { filename: `${name}.js`, jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } }, module: { type: "commonjs" } }).code;
  let index = 0;
  const fakeReact = { ...React, useEffect() {}, useMemo: (fn) => fn(), useState(initial) { const i = index++; return [i in stateOverrides ? stateOverrides[i] : (typeof initial === "function" ? initial() : initial), () => {}]; } };
  const mod = { exports: {} };
  vm.runInNewContext(compiled, { module: mod, exports: mod.exports, require(name) {
    if (name === "react") return fakeReact;
    if (name === "../lib/game-schedule-operations") return operations;
    if (name === "../lib/phase4-operations") return phase4;
    if (name === "../lib/resource-shapes") return shapes;
    if (name === "./GameCatalogue") return () => null;
    if (name === "../lib/client-api") return {};
    if (name === "./SheetSafetyControls") return () => null;
    if (name === "next/link") return function Link({ children, ...props }) { return React.createElement("a", props, children); };
    return require(name);
  } });
  return renderToStaticMarkup(mod.exports.default(props));
}
const names = ["MSP", "Lucky Ghana", "Midweek", "Fortune", "Bonanza", "National", "Aseda"];
const entries = names.flatMap((name, index) => [
  { game_name: name, category: "GHANA", is_whole_day: true },
  { game_name: "Double Chance", category: "DOUBLE_CHANCE", is_whole_day: true },
  ...Array.from({ length: index === 6 ? 4 : 5 }, (_, n) => ({ game_name: `Timed ${n}`, category: "TIMED", closing_time: "12:30", draw_time: "12:45" })),
].map((entry, n) => ({ ...entry, id: index * 10 + n, weekday: index + 1, display_order: n + 1, is_active: true, game_is_active: true })));

test("weekly screen renders canonical names, categories, Whole Day and seven/six counts", async () => {
  const html = await renderComponent("GameScheduleClient", { user: { role: "ACCOUNTANT" } }, { 0: entries, 8: { loading: false } });
  for (const name of names) assert.ok(html.includes(name));
  for (const day of operations.WEEKDAYS) assert.ok(html.includes(day.label));
  assert.equal((html.match(/<strong>Double Chance<\/strong>/g) || []).length, 7);
  assert.equal((html.match(/Ghana Game/g) || []).length, 7);
  assert.ok(html.includes("7/7 active"));
  assert.ok(html.includes("6/6 active"));
  assert.ok(html.includes("Whole Day"));
});

test("Daily Sheet keeps Double Chance visible during Ghana holiday override", async () => {
  const sheet = { id: 1, agency: 1, status: "DRAFT", transaction_date: "2026-08-24", holiday_override_applied: true,
    holiday_replacement_game_name_snapshot: "Bonanza", holiday_source_date_snapshot: "2026-08-21", holiday_name_snapshot: "Holiday",
    sheet_games: entries.filter((e) => e.weekday === 1).map((e) => ({ id: e.id, game_name_snapshot: e.category === "GHANA" ? "Bonanza" : e.game_name, category_snapshot: e.category, is_whole_day_snapshot: e.is_whole_day })) };
  const html = await renderComponent("DailySheetDetailClient", { user: { role: "SUPER_ADMIN" }, initialSheet: sheet });
  for (const label of ["Bonanza", "Ghana Game", "Double Chance", "Timed", "Whole Day"]) assert.ok(html.includes(label), label);
  assert.ok(html.includes("Double Chance remains available"));
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /overflow-x: auto/);
});

test("Double Chance form preserves category and clears times", () => {
  const form = operations.withScheduleMode({ ...operations.emptyScheduleForm(), category: "DOUBLE_CHANCE", game: "1" }, true);
  assert.equal(operations.schedulePayload(form).category, "DOUBLE_CHANCE");
  assert.equal(operations.schedulePayload(form).closing_time, null);
});

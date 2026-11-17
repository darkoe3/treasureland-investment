import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import vm from "node:vm";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><body></body>", { url: "http://localhost", pretendToBeVisual: true });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import("react");
const { createRoot } = await import("react-dom/client");
const require = createRequire(import.meta.url);
let calls;
let requestHandler;
const source = await readFile(new URL("../components/GameCatalogue.js", import.meta.url), "utf8");
const compiled = require("next/dist/build/swc").transformSync(source, {
  filename: "GameCatalogue.js",
  jsc: { parser: { syntax: "ecmascript", jsx: true }, transform: { react: { runtime: "automatic" } } },
  module: { type: "commonjs" },
}).code;
const componentModule = { exports: {} };
vm.runInNewContext(compiled, { module: componentModule, exports: componentModule.exports, window, require(name) {
  if (name.includes("client-api")) return {
    apiPath: (path) => path,
    clientRequest: async (path, options) => {
      calls.push({ path, options });
      return requestHandler(path, options);
    },
  };
  if (name.includes("game-schedule-operations")) return {
    WEEKDAYS: [
      { value: 1, label: "Monday" }, { value: 2, label: "Tuesday" },
      { value: 3, label: "Wednesday" }, { value: 4, label: "Thursday" },
      { value: 5, label: "Friday" }, { value: 6, label: "Saturday" },
      { value: 7, label: "Sunday" },
    ],
  };
  return require(name);
} });
const GameCatalogue = componentModule.exports.default;

async function mount(t, props = {}) {
  calls = [];
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await React.act(async () => root.render(React.createElement(GameCatalogue, {
    games: [],
    entries: [],
    onRefresh: async () => true,
    onSchedule() {},
    ...props,
  })));
  t.after(async () => {
    await React.act(async () => root.unmount());
    container.remove();
  });
  return container;
}

function button(container, label) {
  return [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === label);
}

async function setValue(node, value) {
  const prototype = node.tagName === "SELECT" ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  await React.act(async () => {
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(node, value);
    node.dispatchEvent(new window.Event(node.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}

async function setChecked(node, checked) {
  if (node.checked !== checked) await React.act(async () => node.click());
}

test("empty catalogue creates trimmed games, reports safe field errors, and refreshes after success", async (t) => {
  requestHandler = async () => { throw { message: "Duplicate name.", payload: { name: ["A game with this name already exists."] } }; };
  let refreshes = 0;
  const container = await mount(t, { onRefresh: async () => { refreshes += 1; return true; } });
  assert.ok(container.textContent.includes("No games have been created."));
  await React.act(async () => button(container, "Create first game").click());
  const [name, category] = container.querySelectorAll(".game-catalogue-form input, .game-catalogue-form select");
  await setValue(name, "  ");
  await React.act(async () => container.querySelector(".game-catalogue-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.ok(container.textContent.includes("Game name is required."));
  assert.equal(calls.length, 0);

  await setValue(name, "  Lucky Star  ");
  await setValue(category, "GHANA");
  await React.act(async () => container.querySelector(".game-catalogue-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.equal(calls[0].path, "/games/");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), { name: "Lucky Star", category: "GHANA", is_active: true });
  assert.ok(container.textContent.includes("A game with this name already exists."));
  assert.equal(name.value, "  Lucky Star  ");

  requestHandler = async () => ({ id: 1, name: "Lucky Star", category: "GHANA", is_active: true });
  await React.act(async () => container.querySelector(".game-catalogue-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.equal(calls.filter((call) => call.options?.method === "POST").length, 2);
  assert.equal(refreshes, 1);
  assert.ok(container.textContent.includes("Game created successfully."));
  assert.ok(container.querySelector('[role="status"]'));
});

test("catalogue loading is not shown as an empty database", async (t) => {
  const container = await mount(t, { loading: true });
  assert.match(container.textContent, /Loading games/);
  assert.doesNotMatch(container.textContent, /No games have been created/);
  assert.equal(button(container, "Create game").disabled, true);
});

test("Ghana Game shortcut creates a timed catalogue game without assumed times", async (t) => {
  requestHandler = async () => ({ id: 99, name: "Ghana Game", category: "TIMED", is_active: true });
  const container = await mount(t);
  await React.act(async () => button(container, "Add Ghana Game").click());
  assert.equal(container.querySelector('.game-catalogue-form input').value, 'Ghana Game');
  assert.equal(container.querySelector('.game-catalogue-form select').value, 'TIMED');
  assert.equal(container.querySelector('.game-catalogue-form select').disabled, true);
  assert.match(container.textContent, /No weekdays or times are assigned automatically/);
  await React.act(async () => container.querySelector('.game-catalogue-form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })));
  assert.equal(calls[0].path, '/games/');
  assert.deepEqual(JSON.parse(calls[0].options.body), { name: 'Ghana Game', category: 'TIMED', is_active: true });
});

test("renaming a game to Ghana Game selects and locks the TIMED category", async (t) => {
  const container = await mount(t);
  await React.act(async () => button(container, "Create game").click());
  const name = container.querySelector('.game-catalogue-form input');
  const category = container.querySelector('.game-catalogue-form select');
  await setValue(category, "GHANA");
  await setValue(name, " Ghana Game ");
  assert.equal(category.value, "TIMED");
  assert.equal(category.disabled, true);
});

test("Ghana Game shortcut is hidden when the named game already exists", async (t) => {
  const container = await mount(t, { games: [{ id: 99, name: 'Ghana Game', category: 'TIMED', is_active: true }] });
  assert.equal(button(container, 'Add Ghana Game'), undefined);
});

test("deactivation explicitly identifies affected weekdays and never hard-deletes", async (t) => {
  const game = { id: 7, name: "Lucky Star", category: "TIMED", is_active: true, created_at: "2026-01-01", updated_at: "2026-01-02" };
  const entries = [{ game: 7, weekday: 1, is_active: true, game_is_active: true }];
  const confirm = window.confirm;
  window.confirm = (message) => message.includes("Monday") && message.includes("Daily Sheets");
  requestHandler = async () => ({ ...game, is_active: false });
  const container = await mount(t, { games: [game], entries });
  await React.act(async () => container.querySelector('[aria-label="Deactivate Lucky Star"]').click());
  assert.equal(calls[0].path, "/games/7/");
  assert.equal(calls[0].options.method, "PATCH");
  assert.deepEqual(JSON.parse(calls[0].options.body), { is_active: false, confirm_deactivation: true });
  assert.equal(calls.some((call) => call.options?.method === "DELETE"), false);
  window.confirm = confirm;
});

test("game reactivation displays the backend weekday-capacity error", async (t) => {
  const game = { id: 8, name: "Inactive scheduled game", category: "TIMED", is_active: false };
  requestHandler = async () => {
    throw {
      message: "Request failed.",
      payload: { is_active: ["Cannot reactivate this game because Monday already has 7 active games."] },
    };
  };
  const container = await mount(t, {
    games: [game],
    entries: [{ game: 8, weekday: 1, is_active: true, game_is_active: false }],
  });
  await React.act(async () => container.querySelector('[aria-label="Activate Inactive scheduled game"]').click());
  assert.ok(container.textContent.includes("Monday already has 7 active games."));
});

test("Edit schedule opens the connected workflow for inactive assignments and submits explicit weekday times", async (t) => {
  const game = { id: 8, name: "Enugu", category: "TIMED", is_active: false };
  const entries = [
    { id: 80, game: 8, game_name: "Enugu", category: "GHANA", weekday: 3, weekday_display: "Wednesday", display_order: 4, is_whole_day: true, is_active: false, game_is_active: false },
    { id: 81, game: 8, game_name: "Enugu", category: "GHANA", weekday: 7, weekday_display: "Sunday", display_order: 1, is_whole_day: true, is_active: false, game_is_active: false },
  ];
  requestHandler = async () => ({ game: { ...game, is_active: true }, assignments: [] });
  let refreshes = 0;
  const container = await mount(t, {
    games: [game],
    entries,
    onRefresh: async () => { refreshes += 1; return true; },
  });
  for (const label of ["Edit game", "Edit schedule", "Activate"]) assert.ok(button(container, label), label);
  await React.act(async () => button(container, "Edit schedule").click());
  assert.ok(container.textContent.includes("Wednesday — Inactive assignment"));
  assert.ok(container.textContent.includes("Sunday — Inactive assignment"));
  const assignments = container.querySelectorAll(".game-assignment");
  assert.equal(assignments.length, 2);
  assert.equal(assignments[0].querySelector('input[type="time"]').value, "");

  await setValue(assignments[0].querySelector('input[type="time"]'), "19:30");
  await setValue(assignments[0].querySelectorAll('input[type="time"]')[1], "19:45");
  await setValue(assignments[1].querySelector('input[type="time"]'), "15:30");
  await setValue(assignments[1].querySelectorAll('input[type="time"]')[1], "15:45");
  await setChecked(container.querySelector(".game-connected-fields input[type=checkbox]"), true);
  for (const assignment of assignments) await setChecked(assignment.querySelector('input[type=checkbox]'), true);
  await React.act(async () => container.querySelector(".game-connected-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));

  assert.equal(calls[0].path, "/games/8/edit-schedule/");
  assert.equal(calls[0].options.method, "POST");
  const payload = JSON.parse(calls[0].options.body);
  assert.equal(payload.is_active, true);
  assert.equal(payload.category, "TIMED");
  assert.deepEqual(payload.assignments.map(({ weekday, closing_time, draw_time, is_active }) => ({ weekday, closing_time, draw_time, is_active })), [
    { weekday: 3, closing_time: "19:30", draw_time: "19:45", is_active: true },
    { weekday: 7, closing_time: "15:30", draw_time: "15:45", is_active: true },
  ]);
  assert.equal(refreshes, 1);
  assert.ok(container.textContent.includes("Game and schedule assignments saved."));
});

test("connected editor displays weekday conflicts beside the affected assignment", async (t) => {
  const game = { id: 9, name: "Capacity Game", category: "TIMED", is_active: false };
  requestHandler = async () => {
    throw {
      message: "Invalid schedule.",
      payload: {
        weekday_conflicts: [{
          weekday: 1,
          weekday_display: "Monday",
          errors: [{ code: "full_capacity", message: "Monday has 8 active games; capacity is 7." }],
        }],
      },
    };
  };
  const container = await mount(t, {
    games: [game],
    entries: [{
      id: 90, game: 9, game_name: "Capacity Game", category: "TIMED", weekday: 1,
      weekday_display: "Monday", display_order: 8, is_whole_day: false,
      closing_time: "12:30", draw_time: "12:45", is_active: false, game_is_active: false,
    }],
  });
  await React.act(async () => button(container, "Edit schedule").click());
  await setChecked(container.querySelector(".game-connected-fields input[type=checkbox]"), true);
  await setChecked(container.querySelector(".game-assignment input[type=checkbox]"), true);
  await React.act(async () => container.querySelector(".game-connected-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.ok(container.querySelector(".game-assignment [role=alert]").textContent.includes("capacity is 7"));
});

test("Timed-to-Whole-Day conversion asks first, clears entered times, and submits confirmation", async (t) => {
  const game = { id: 10, name: "Whole Day Conversion", category: "TIMED", is_active: true };
  const entry = {
    id: 100, game: 10, game_name: game.name, category: "TIMED", weekday: 1,
    weekday_display: "Monday", display_order: 2, is_whole_day: false,
    closing_time: "12:30", draw_time: "12:45", is_active: true, game_is_active: true,
  };
  requestHandler = async () => ({ game, assignments: [] });
  const previousConfirm = window.confirm;
  let confirmation = "";
  window.confirm = (message) => { confirmation = message; return true; };
  const container = await mount(t, { games: [game], entries: [entry] });
  await React.act(async () => button(container, "Edit game").click());
  await setValue(container.querySelector(".game-connected-fields select"), "GHANA");
  assert.match(confirmation, /clear the closing and draw times on Monday/);
  assert.equal(container.querySelectorAll(".game-assignment input[type=time]").length, 0);
  await React.act(async () => container.querySelector(".game-connected-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  const payload = JSON.parse(calls[0].options.body);
  assert.equal(payload.confirm_clear_times, true);
  assert.equal(payload.category, "GHANA");
  assert.equal(payload.assignments[0].closing_time, null);
  assert.equal(payload.assignments[0].draw_time, null);
  window.confirm = previousConfirm;
});

test("game management tab remains Super Admin-only and catalogue supports schedule action", async () => {
  const source = await readFile(new URL("../components/GameScheduleClient.js", import.meta.url), "utf8");
  assert.ok(source.includes('{canMutate ? <button type="button" aria-pressed={activeTab === "games"}'));
  assert.ok(source.includes('activeTab === "games" && canMutate ? <GameCatalogue'));
  assert.ok(source.includes('onSchedule={(game) => { beginCreate(game); setActiveTab("schedule"); }}'));
});

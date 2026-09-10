import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { clientRequest, resetClientApiStateForTests, validationMessage } from "../lib/client-api.js";
import { searchPeople } from "../lib/phase4-operations.js";

const detail = "TPM code 123456 already exists and is assigned to Ayo. Edit the existing TPM code instead.";

test("client displays Django field validation detail", async () => {
  resetClientApiStateForTests();
  const fetchImpl = async (path) => path === "/api/auth/csrf"
    ? new Response(JSON.stringify({ csrfToken: "test-csrf" }), { status: 200 })
    : new Response(JSON.stringify({ code: [detail] }), { status: 400 });
  await assert.rejects(clientRequest("/api/backend/tpm-codes/", { method: "POST", body: "{}" }, fetchImpl), (error) => {
    assert.equal(error.message, detail);
    assert.equal(error.status, 400);
    return true;
  });
  assert.equal(validationMessage({ detail }, 400), detail);
  assert.equal(validationMessage({ detail: "private traceback" }, 500), "Upstream service error.");
});

test("inactive TPM codes remain searchable and editable", async () => {
  const person = { id: 1, full_name: "Ayo", tpm_codes: [{ id: 4, code: "123456", is_active: false }] };
  assert.deepEqual(searchPeople([person], "123456"), [person]);
  const source = await readFile(new URL("../components/PeopleTpmClient.js", import.meta.url), "utf8");
  assert.match(source, /Edit\/Reassign/);
  assert.match(source, /disabled=\{!canForAgency\(user, person.agency, "can_edit"\)\}/);
  assert.match(source, /is_active: code.is_active/);
  assert.match(source, /TPM status/);
  assert.match(source, /\(Inactive\)/);
  assert.match(source, /\{state.error\}/);
});

test("reassignment handler cancels without a request and sends confirmation on acceptance", async () => {
  const source = await readFile(new URL("../components/PeopleTpmClient.js", import.meta.url), "utf8");
  const body = source.split("async function saveCode(event) {")[1].split("\n  async function deactivateCode")[0].replace(/\}\s*$/, "");
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const run = new AsyncFunction("event", "editingCode", "codeForm", "people", "window", "clientRequest", "apiPath", "setCodeForm", "setEditingCode", "setState", "loadPeople", body);
  const requests = [];
  const invoke = (accept) => run({ preventDefault() {} }, { id: 4, person: 1, person_name: "Ayo", code: "123456" },
    { person: 2, code: "123456", is_active: true }, [{ id: 2, full_name: "Bisi" }],
    { confirm(message) { assert.match(message, /from Ayo to Bisi/); return accept; } },
    async (path, options) => requests.push({ path, ...options }), (path) => path, () => {}, () => {}, () => {}, async () => {});
  await invoke(false);
  assert.equal(requests.length, 0);
  await invoke(true);
  assert.equal(requests[0].method, "PATCH");
  assert.deepEqual(JSON.parse(requests[0].body), { person: 2, code: "123456", is_active: true, confirm_reassignment: true });
});

// Live browser check of the production deployment (Playwright; see ui_check.mjs for the install note).
//   HAN_URL=https://han.tniglobal.org HAN_USER=pilot03@tniglobal.org HAN_PASS=... \
//   HAN_ADMIN=han.ops@tniglobal.org HAN_ADMIN_PASS=... node scripts/ui_check_live.mjs
// Uses the REAL model, so the first translation can take a while.
import { createRequire } from "node:module";
import os from "node:os";
import fs from "node:fs";

const playwrightDir = process.env.HAN_PLAYWRIGHT_DIR || `${os.homedir()}/.han-venvs/pw`;
const { chromium } = createRequire(`${playwrightDir}/`)("playwright");
const base = process.env.HAN_URL;
const shots = new URL("./shots/", import.meta.url).pathname;
fs.mkdirSync(shots, { recursive: true });
let failed = 0;
const check = (label, ok, detail = "") => { console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}${!ok && detail ? " - " + detail : ""}`); if (!ok) failed++; };
const seen = async (loc, ms = 15000) => loc.first().waitFor({ timeout: ms }).then(() => true).catch(() => false);

const browser = await chromium.launch();
async function login(email, password) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [], leaks = [];
  page.on("console", (m) => { if (m.type() === "error" && !/status of (401|403|422|429|503)/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("response", async (r) => {
    if (!r.url().includes("/v1/") || r.url().includes("/v1/admin/")) return;
    try { const t = await r.text(); for (const k of ["provider_id", "model_id", "route_reason", "latency_ms", "estimated_cost", "model_key"]) if (t.includes(`"${k}"`)) leaks.push(k); } catch { /* no body */ }
  });
  await page.goto(base + "/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/projects", { timeout: 20000 });
  return { ctx, page, errors, leaks };
}

{
  const { ctx, page, errors, leaks } = await login(process.env.HAN_USER, process.env.HAN_PASS);
  check("translator signs in over HTTPS with a trusted certificate", await seen(page.getByRole("heading", { name: "Your projects" })));
  await page.getByRole("link", { name: /TNI Translator Pilot/ }).click();
  check("pilot project opens", await seen(page.getByRole("heading", { name: "TNI Translator Pilot", level: 1 })));
  check("experimental readiness is shown", await seen(page.getByText("Internal warning: controlled pilot only.")));

  await page.locator("#chat-input").fill("Translate this text from English to German: The delivery will arrive on Monday morning.");
  await page.getByRole("button", { name: "Send" }).click();
  const target = page.locator("textarea[id^='target-']").first();
  check("HAN chat returns a draft (real model)", await seen(target, 180000));
  const draft = await target.inputValue();
  console.log(`    HAN draft: ${draft}`);
  check("draft is real German, not a stub", draft.length > 10 && !draft.includes("[MOCK") && /Lieferung|Montag/i.test(draft), draft);
  check("review prompt shown", await seen(page.getByText("Please review it and make any corrections before approving it.")));
  check("experimental warning shown on the draft", await seen(page.getByText(/controlled pilot/i)));
  await page.screenshot({ path: shots + "live-1-chat.png" });

  await target.fill(draft + " ");
  await page.getByRole("button", { name: "Save as new version" }).click();
  check("edit creates version 2", await seen(page.getByText(/Version 2 · Translator-edited/)));
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Approve version" }).click();
  check("human approval recorded", await seen(page.getByText("Your approved translation has been saved to the project's Translation Memory.")));
  await page.screenshot({ path: shots + "live-2-approved.png" });

  await page.getByRole("tab", { name: "Quick translate" }).click();
  await page.locator("#qt-pair").selectOption("en>de");
  await page.locator("#qt-text").fill("The delivery will arrive on Monday morning.");
  await page.getByRole("button", { name: "Prepare draft" }).click();
  check("approved sentence now appears as a 100% Translation Memory match", await seen(page.getByText(/Translation Memory · 100%/), 180000));

  const body = (await page.locator("body").innerText()).toLowerCase();
  check("no engine/vendor names in the translator UI", !/(madlad|nllb|google|openai|sophia)/.test(body));
  check("no engine metadata in translator-facing API responses", leaks.length === 0, leaks.join(","));
  check("no browser console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await login(process.env.HAN_ADMIN, process.env.HAN_ADMIN_PASS);
  await page.getByRole("link", { name: "Operations" }).click();
  check("technical admin sees the model registry", await seen(page.getByRole("heading", { name: "Model registry" })));
  check("routing events visible to the technical admin only", await seen(page.getByRole("heading", { name: "Recent routing events" })));
  await page.screenshot({ path: shots + "live-3-ops.png", fullPage: true });
  check("no browser console errors (admin)", errors.length === 0, errors.slice(0, 2).join(" | "));
  await ctx.close();
}
await browser.close();
process.exit(failed ? 1 : 0);

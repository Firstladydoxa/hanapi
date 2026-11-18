// Browser end-to-end checks (Playwright). Playwright is NOT a repo dependency; install it separately, e.g.
//   mkdir -p ~/.han-venvs/pw && cd ~/.han-venvs/pw && npm init -y && npm i playwright && npx playwright install chromium
// then run it against the live stack (HAN_PLAYWRIGHT_DIR defaults to ~/.han-venvs/pw):
//   ~/.han-venvs/han/bin/python scripts/smoke_e2e.py --ui scripts/ui_check.mjs
// Screenshots are written to scripts/shots/ (git-ignored).
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

const browser = await chromium.launch();
const FORBIDDEN_KEYS = ["provider_id", "model_id", "route_reason", "latency_ms", "estimated_cost", "model_key"];

async function session(email, password, label) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  const leaks = [];
  page.on("console", (m) => { if (m.type() === "error" && !/status of (401|403|422|503)/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("response", async (r) => {
    const url = r.url();
    if (!url.includes("/v1/") || url.includes("/v1/admin/")) return;
    try { const t = await r.text(); for (const k of FORBIDDEN_KEYS) if (t.includes(`"${k}"`)) leaks.push(`${k} in ${url}`); } catch { /* body unavailable */ }
  });
  await page.goto(base + "/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/projects");
  return { ctx, page, errors, leaks, label };
}

// ---------------------------------------------------------------- translator journey
{
  const { ctx, page, errors, leaks } = await session(process.env.HAN_TRANSLATOR_EMAIL, process.env.HAN_TRANSLATOR_PASSWORD, "translator");
  check("signed in and lands on projects", await page.getByRole("heading", { name: "Your projects" }).waitFor({ timeout: 10000 }).then(() => true).catch(() => false));
  check("sees the authorised project", await page.getByText("Demo project").first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false));
  check("admin navigation hidden for translators", (await page.getByRole("link", { name: "Administration" }).count()) === 0);
  await page.screenshot({ path: shots + "1-projects.png" });

  await page.getByRole("link", { name: /Demo project/ }).click();
  await page.getByRole("heading", { name: "Demo project", level: 1 }).waitFor();
  check("language readiness tiers shown", await page.getByText("Experimental").first().isVisible());

  await page.locator("#chat-input").fill("Translate this text from English to German: Good morning, team. The meeting is on 12 May.");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByText("Here is my suggested translation:").first().waitFor({ timeout: 20000 });
  const target = page.locator("textarea[id^='target-']").first();
  await target.waitFor();
  check("HAN returns an editable suggested draft", (await target.inputValue()).includes("[MOCK DRAFT]"));
  check("review prompt shown", await page.getByText("Please review it and make any corrections before approving it.").isVisible());
  await page.screenshot({ path: shots + "2-chat-draft.png" });

  await target.fill("Guten Morgen, Team. Das Treffen ist am 12. Mai.");
  await page.getByRole("button", { name: "Save as new version" }).click();
  await page.getByText("saved as a new version").waitFor();
  check("edit saved as version 2 (translator-edited)", await page.getByText(/Version 2 · Translator-edited/).first().isVisible());
  check("version 1 still listed (immutable history)", await page.getByText(/Version 1 · Suggested draft/).first().isVisible());

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Approve version" }).click();
  await page.getByText("Your approved translation has been saved to the project's Translation Memory.").waitFor();
  check("approval recorded by the human", await page.getByText(/Version 2 · Approved translation/).first().isVisible());
  check("approve button disabled after decision", await page.getByRole("button", { name: "Approve version" }).isDisabled());
  await page.screenshot({ path: shots + "3-approved.png" });

  // quick translate + engine question
  await page.locator("#chat-input").fill("Which engine did you use?");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByText("HAN manages the translation process").waitFor();
  check("engine question politely deflected", true);

  // workspace
  await page.getByRole("tab", { name: "Translation Workspace" }).click();
  await page.locator("#job-text").fill("First paragraph of the document.\n\nSecond paragraph with 25 items.");
  await page.getByRole("button", { name: "Create job" }).click();
  await page.getByRole("list", { name: "Segments" }).waitFor({ timeout: 20000 });
  check("job shows two side-by-side segments", (await page.getByRole("list", { name: "Segments" }).getByRole("listitem").count()) === 2);
  await page.getByRole("list", { name: "Segments" }).getByRole("button").first().click();
  await page.getByRole("region", { name: "Translation review" }).waitFor();
  check("segment editor with quality checks and history", await page.getByText("Quality checks").isVisible() && await page.getByText("Version history").isVisible());
  await page.screenshot({ path: shots + "4-workspace.png" });

  // mobile layout
  await page.setViewportSize({ width: 390, height: 800 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  check("no horizontal overflow on a phone-sized screen", !overflow);
  await page.screenshot({ path: shots + "5-mobile.png" });

  // role isolation
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto(base + "/admin/ops");
  check("direct visit to operations shows restricted state", await page.getByText("Access restricted").waitFor({ timeout: 10000 }).then(() => true).catch(() => false));
  const body = (await page.locator("body").innerText()).toLowerCase();
  check("no engine/vendor names anywhere in the translator UI", !/(madlad|nllb|afrinllb|google|openai|sophia)/.test(body));
  check("no engine metadata in any translator-facing API response", leaks.length === 0, leaks.join("; "));
  check("no browser console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();
}

// ---------------------------------------------------------------- technical administrator
{
  const { ctx, page, errors } = await session(process.env.HAN_TECH_EMAIL, process.env.HAN_TECH_PASSWORD, "tech");
  await page.getByRole("link", { name: "Operations" }).click();
  await page.getByRole("heading", { name: "Model registry" }).waitFor({ timeout: 15000 });
  check("technical admin sees the protected model registry", await page.getByText("dev-mock").first().isVisible());
  check("technical admin sees routing events", await page.getByRole("heading", { name: "Recent routing events" }).isVisible());
  await page.screenshot({ path: shots + "6-ops.png", fullPage: true });
  await page.getByRole("link", { name: "Administration" }).click();
  await page.getByRole("tab", { name: "Language readiness" }).click();
  check("readiness editor lists directions", await page.getByText("en → de").first().waitFor({ timeout: 10000 }).then(() => true).catch(() => false));
  check("no browser console errors (admin)", errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();
}

await browser.close();
process.exit(failed ? 1 : 0);

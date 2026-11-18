// Live browser check of the production deployment (Playwright; see ui_check.mjs for the install note).
//   HAN_URL=https://han.tniglobal.org HAN_USER=pilot03@tniglobal.org HAN_PASS=... \
//   HAN_ADMIN=han.ops@tniglobal.org HAN_ADMIN_PASS=... node scripts/ui_check_live.mjs
// READ-ONLY: it signs in, navigates every menu item and exercises the toggle/drawer, but creates no translations.
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
const nav = (page, name) => page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name });
const width = async (page) => (await page.locator("#han-sidebar").boundingBox())?.width ?? 0;

const browser = await chromium.launch();
async function login(email, password) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/status of (401|403|422|429|503)/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(base + "/login");
  await page.screenshot({ path: shots + "live-0-login.png" });
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/projects", { timeout: 20000 });
  return { ctx, page, errors };
}

{
  const { ctx, page, errors } = await login(process.env.HAN_USER, process.env.HAN_PASS);
  check("translator signs in over HTTPS", await seen(page.getByRole("heading", { name: "Your projects" })));
  check("translator menu has no administration items", (await nav(page, /Users|Operations|Audit trail|Terminology/).count()) === 0);
  await page.getByRole("link", { name: /TNI Translator Pilot/ }).click();
  check("project overview page", await seen(page.getByRole("heading", { name: "TNI Translator Pilot", level: 1 })));
  check("language pairs labelled experimental", await seen(page.getByText("Internal warning: controlled pilot only.")));
  await page.screenshot({ path: shots + "live-1-overview.png" });
  const open = await width(page);
  await page.getByRole("button", { name: "Hide navigation menu" }).click();
  await page.waitForTimeout(450);
  check("menu toggle collapses the sidebar", open > 200 && (await width(page)) < 110);
  await page.getByRole("button", { name: "Show navigation menu" }).click();
  for (const [link, heading] of [["HAN Chat", "HAN Chat"], ["Quick translate", "Quick translate"], ["Translation workspace", "Translation workspace"], ["Overview", "TNI Translator Pilot"]]) {
    await nav(page, link).click();
    check(`menu item "${link}" opens its page`, await seen(page.getByRole("heading", { name: heading, level: 1 })));
  }
  await nav(page, "Translation workspace").click();
  await seen(page.getByRole("heading", { name: "Your jobs" }));
  await page.screenshot({ path: shots + "live-2-workspace.png" });
  await page.setViewportSize({ width: 390, height: 800 });
  await page.waitForTimeout(500);
  check("phone: no horizontal overflow", !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)));
  await page.getByRole("button", { name: "Show navigation menu" }).click();
  await page.waitForTimeout(450);
  check("phone: menu button opens the drawer", await nav(page, "Quick translate").isVisible());
  await page.screenshot({ path: shots + "live-3-mobile-drawer.png" });
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto(base + "/admin/ops");
  check("operations is restricted for translators", await seen(page.getByText("Access restricted"), 10000));
  const body = (await page.locator("body").innerText()).toLowerCase();
  check("no engine/vendor names in the translator UI", !/(madlad|nllb|google|openai|sophia)/.test(body));
  check("no browser console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
  await ctx.close();
}
{
  const { ctx, page, errors } = await login(process.env.HAN_ADMIN, process.env.HAN_ADMIN_PASS);
  for (const name of ["Users", "Projects & members", "Terminology", "Language readiness", "Operations", "Audit trail"]) {
    await nav(page, name).click();
    check(`admin menu item "${name}" opens its page`, await seen(page.getByRole("heading", { name, level: 1 })));
  }
  await nav(page, "Operations").click();
  check("operations shows the model registry to the technical admin", await seen(page.getByRole("heading", { name: "Model registry" })));
  await page.screenshot({ path: shots + "live-4-ops.png", fullPage: true });
  check("no browser console errors (admin)", errors.length === 0, errors.slice(0, 2).join(" | "));
  await ctx.close();
}
await browser.close();
process.exit(failed ? 1 : 0);

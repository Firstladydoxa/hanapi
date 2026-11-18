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
const seen = (loc, ms = 15000) => loc.first().waitFor({ timeout: ms }).then(() => true).catch(() => false);

const browser = await chromium.launch();
const FORBIDDEN_KEYS = ["provider_id", "model_id", "route_reason", "latency_ms", "estimated_cost", "model_key"];

async function session(email, password) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [], leaks = [];
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
  return { ctx, page, errors, leaks };
}
const sidebar = (page) => page.locator("#han-sidebar");
const sidebarWidth = async (page) => (await sidebar(page).boundingBox())?.width ?? 0;
const nav = (page, name) => page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name });

// ---------------------------------------------------------------- translator journey
{
  const { ctx, page, errors, leaks } = await session(process.env.HAN_TRANSLATOR_EMAIL, process.env.HAN_TRANSLATOR_PASSWORD);
  await page.screenshot({ path: shots + "0-login-then-projects.png" });
  check("signed in and lands on the projects page", await seen(page.getByRole("heading", { name: "Your projects" })));
  check("sidebar menu is shown with Projects", await seen(nav(page, "Projects")));
  check("administration/operations/audit links hidden for translators", (await nav(page, /Users|Operations|Audit trail|Terminology/).count()) === 0);
  check("no project section before a project is chosen", (await page.getByText("PROJECT", { exact: true }).count()) === 0);

  await page.getByRole("link", { name: /Demo project/ }).click();
  await page.waitForURL(/\/projects\/[^/]+$/);
  const projectUrl = page.url();
  check("project overview page", await seen(page.getByRole("heading", { name: "Demo project", level: 1 })));
  check("overview offers pages as cards (no tabs, no side column)", (await page.getByRole("tab").count()) === 0 && await seen(page.getByRole("link", { name: /HAN Chat/ }).nth(1)));
  check("project menu appears in the sidebar", await seen(nav(page, "HAN Chat")) && await seen(nav(page, "Quick translate")) && await seen(nav(page, "Translation workspace")) && await seen(nav(page, "Overview")));
  check("language readiness cards flow on the page", await seen(page.getByText("Internal warning: controlled pilot only.")));
  await page.screenshot({ path: shots + "1-overview.png" });

  // ---- toggleable navigation (desktop)
  const open = await sidebarWidth(page);
  await page.getByRole("button", { name: "Hide navigation menu" }).click();
  await page.waitForTimeout(450);
  const closed = await sidebarWidth(page);
  check("menu toggle collapses the sidebar to an icon rail", open > 200 && closed < 110, `${open} -> ${closed}`);
  check("collapsed rail hides the labels but keeps the links reachable", !(await page.getByText("Quick translate", { exact: true }).first().isVisible()) && await nav(page, "Quick translate").isVisible());
  await page.screenshot({ path: shots + "2-collapsed.png" });
  await page.reload();
  await page.waitForTimeout(600);
  check("collapsed state is remembered after a reload", (await sidebarWidth(page)) < 110);
  await page.getByRole("button", { name: "Show navigation menu" }).click();
  await page.waitForTimeout(450);
  check("menu toggle expands it again", (await sidebarWidth(page)) > 200);

  // ---- chat page (menu item -> separate page)
  await nav(page, "HAN Chat").click();
  await page.waitForURL(/\/chat$/);
  check("HAN Chat is its own page", await seen(page.getByRole("heading", { name: "HAN Chat", level: 1 })) && await nav(page, "HAN Chat").getAttribute("aria-current") === "page");
  await page.locator("#chat-input").fill("Translate this text from English to German: Good morning, team. The meeting is on 12 May.");
  await page.getByRole("button", { name: "Send" }).click();
  const target = page.locator("textarea[id^='target-']").first();
  check("HAN returns an editable draft", await seen(target, 30000) && (await target.inputValue()).includes("[MOCK DRAFT]"));
  check("review prompt shown", await seen(page.getByText("Please review it and make any corrections before approving it.")));
  await page.screenshot({ path: shots + "3-chat-draft.png" });
  await target.fill("Guten Morgen, Team. Das Treffen ist am 12. Mai.");
  await page.getByRole("button", { name: "Save as new version" }).click();
  check("edit saved as version 2 (translator-edited)", await seen(page.getByText(/Version 2 · Translator-edited/)));
  check("version 1 still listed", await seen(page.getByText(/Version 1 · Suggested draft/)));
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Approve version" }).click();
  check("approval recorded", await seen(page.getByText("Your approved translation has been saved to the project's Translation Memory.")));
  await page.screenshot({ path: shots + "4-approved.png" });

  await page.locator("#chat-input").fill("Which engine did you use?");
  await page.getByRole("button", { name: "Send" }).click();
  check("engine question politely deflected", await seen(page.getByText("HAN manages the translation process")));

  // ---- open in workspace (cross-page link)
  await page.getByRole("button", { name: "Open in Workspace" }).first().click();
  await page.waitForURL(/\/workspace\?translation=/);
  check("Open in Workspace navigates to the workspace page", await seen(page.getByRole("heading", { name: "Translation workspace", level: 1 })) && await seen(page.getByRole("region", { name: "Translation review" })));

  // ---- quick translate page
  await nav(page, "Quick translate").click();
  await page.waitForURL(/\/quick$/);
  await page.locator("#qt-pair").selectOption("en>de");
  await page.locator("#qt-text").fill("Please confirm the delivery address before 5 June.");
  await page.getByRole("button", { name: "Prepare draft" }).click();
  check("quick translate page returns a draft", await seen(page.locator("textarea[id^='target-']"), 30000));
  await page.screenshot({ path: shots + "5-quick.png" });

  // ---- workspace page: single column, segments expand in place
  await nav(page, "Translation workspace").click();
  await page.waitForURL(/\/workspace$/);
  await page.getByRole("button", { name: /New job|Hide form/ }).first().waitFor();
  if (!(await page.locator("#job-text").isVisible())) await page.getByRole("button", { name: "＋ New job" }).click();
  await page.locator("#job-text").fill("First paragraph of the document.\n\nSecond paragraph with 25 items.");
  await page.getByRole("button", { name: "Create job" }).click();
  const segs = page.getByRole("list", { name: "Segments" });
  check("job shows two full-width segments", await seen(segs, 30000) && (await segs.getByRole("listitem").count()) === 2);
  const first = segs.getByRole("listitem").first();
  const w = (await first.boundingBox())?.width ?? 0;
  const contentW = (await page.locator("#han-content").boundingBox())?.width ?? 1;
  check("segments use the full page width (not a narrow column)", w / contentW > 0.85, `${Math.round(w)} of ${Math.round(contentW)}`);
  await first.getByRole("button").first().click();
  check("segment expands in place with review, checks and history", await seen(first.getByRole("region", { name: "Translation review" })) && await first.getByText("Quality checks").isVisible() && await first.getByText("Version history").isVisible());
  await page.screenshot({ path: shots + "6-workspace.png", fullPage: true });

  // ---- phone: drawer menu
  await page.setViewportSize({ width: 390, height: 800 });
  await page.waitForTimeout(500);
  check("on a phone the sidebar is hidden until opened", !(await sidebar(page).isVisible()) || (await sidebar(page).boundingBox())?.x < -50);
  check("no horizontal overflow on a phone-sized screen", !(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2)));
  await page.getByRole("button", { name: "Show navigation menu" }).click();
  await page.waitForTimeout(450);
  check("menu button opens the drawer", await nav(page, "Quick translate").isVisible());
  await page.screenshot({ path: shots + "7-mobile-drawer.png" });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(450);
  check("Escape closes the drawer", (await sidebar(page).boundingBox())?.x < -50);
  await page.getByRole("button", { name: "Show navigation menu" }).click();
  await page.waitForTimeout(400);
  await nav(page, "Overview").click();
  await page.waitForURL(projectUrl);
  await page.waitForTimeout(450);
  check("choosing a menu item navigates and closes the drawer", (await sidebar(page).boundingBox())?.x < -50);
  await page.screenshot({ path: shots + "8-mobile-overview.png" });
  await page.setViewportSize({ width: 1360, height: 900 });

  // ---- role isolation + confidentiality
  await page.goto(base + "/admin/ops");
  check("direct visit to operations shows the restricted state", await seen(page.getByText("Access restricted"), 10000));
  const body = (await page.locator("body").innerText()).toLowerCase();
  check("no engine/vendor names anywhere in the translator UI", !/(madlad|nllb|afrinllb|google|openai|sophia)/.test(body));
  check("no engine metadata in any translator-facing API response", leaks.length === 0, leaks.join("; "));
  check("no browser console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();
}

// ---------------------------------------------------------------- technical administrator: every menu item is a page
{
  const { ctx, page, errors } = await session(process.env.HAN_TECH_EMAIL, process.env.HAN_TECH_PASSWORD);
  const pages = [["Users", "Users"], ["Projects & members", "Projects & members"], ["Terminology", "Terminology"], ["Language readiness", "Language readiness"], ["Operations", "Operations"], ["Audit trail", "Audit trail"]];
  check("administration and system sections are in the menu", await seen(page.getByText("ADMINISTRATION", { exact: true })) && await seen(page.getByText("SYSTEM", { exact: true })));
  for (const [link, heading] of pages) {
    await nav(page, link).click();
    check(`menu item "${link}" opens its own page`, await seen(page.getByRole("heading", { name: heading, level: 1 })) && await nav(page, link).getAttribute("aria-current") === "page");
  }
  check("technical admin sees the protected model registry", await seen(page.getByRole("heading", { name: "Model registry" }).or(page.getByRole("heading", { name: "Audit events" }))));
  await nav(page, "Operations").click();
  check("operations page shows registry and routing", await seen(page.getByRole("heading", { name: "Model registry" })) && await seen(page.getByRole("heading", { name: "Recent routing events" })));
  await page.screenshot({ path: shots + "9-ops.png", fullPage: true });
  await nav(page, "Language readiness").click();
  await page.getByText("en → de").first().waitFor({ timeout: 10000 });
  await page.screenshot({ path: shots + "10-readiness.png" });
  await page.goto(base + "/admin");
  check("/admin redirects to the first admin page", await seen(page.getByRole("heading", { name: "Users", level: 1 })));
  check("no browser console errors (admin)", errors.length === 0, errors.slice(0, 3).join(" | "));
  await ctx.close();
}

await browser.close();
process.exit(failed ? 1 : 0);

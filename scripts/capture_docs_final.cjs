const { chromium } = require(process.env.PW);
const path = require("path");

const BASE = process.env.BASE || "http://127.0.0.1:8787";
const OUT = path.join(__dirname, "..", "docs", "screenshots");

(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.stack || String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  const snap = async (name) => {
    await page.waitForTimeout(700);
    await page.screenshot({ path: path.join(OUT, name) });
  };
  const close = async () => {
    await page.locator("#modal-root [data-close]").last().click({ force: true }).catch(() => {});
    await page.waitForTimeout(300);
  };
  const closeAll = async () => {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      if (!(await page.locator("#modal-root .modal-layer").count())) break;
      await close();
    }
  };

  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector(".track-row");
  await snap("library.png");

  await page.evaluate(() => document.querySelector(".table-card")?.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(350);
  await snap("library-table.png");

  await page.evaluate(() => {
    const row = [...document.querySelectorAll(".track-row")].find((item) => item.textContent.includes("晨雾"));
    row?.scrollIntoView({ block: "center" });
  });
  await page.waitForTimeout(350);
  await snap("library-audio.png");

  await page.locator(".nav-item[data-view='categories']").click();
  await page.waitForTimeout(300);
  await page.evaluate(() => window.scrollTo(0, 0));
  await snap("categories.png");

  await page.evaluate(() => {
    const title = [...document.querySelectorAll(".section-title")].find((item) => item.textContent.includes("形体的八个抽屉"));
    title?.scrollIntoView({ block: "start" });
  });
  await page.waitForTimeout(350);
  await snap("categories-form.png");

  await page.evaluate(() => {
    const title = [...document.querySelectorAll(".section-title")].find((item) => item.textContent.includes("大类下的小类"));
    title?.scrollIntoView({ block: "start" });
  });
  await page.waitForTimeout(350);
  await snap("custom-drawers.png");

  await page.locator(".category-card[data-category='sfx']").click();
  await page.waitForTimeout(400);
  await snap("sfx-drawer.png");
  await close();

  await page.locator(".category-card[data-category='animation']").click();
  await page.waitForTimeout(400);
  await page.locator("[data-drawer-selectall]").check({ force: true }).catch(() => {});
  await snap("drawer-batch.png");
  await close();

  await page.locator(".nav-item[data-view='library']").click();
  await page.locator("[data-action='open-tag-filter']").click();
  await page.waitForTimeout(400);
  await page.locator("[data-tag-choice='夜晚']").check({ force: true });
  await snap("tag-filter.png");
  await page.locator("[data-tag-apply]").click();
  await page.waitForTimeout(400);

  await page.locator(".nav-item[data-view='favorites']").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await snap("favorites.png");

  await page.locator(".nav-item[data-view='library']").click();
  await page.locator("[data-action='open-tag-filter']").click();
  await page.waitForTimeout(300);
  await page.locator("[data-tag-clear]").click();
  await page.waitForTimeout(300);
  await page.locator(".row-title", { hasText: "蒙皮小人" }).click();
  await page.waitForSelector(".detail-layout");
  await snap("detail.png");
  await page.locator("[data-inspect-action='skin']").click();
  await page.waitForSelector(".skin-preview canvas", { timeout: 10000 });
  await page.waitForTimeout(1200);
  await snap("skin-preview.png");
  await page.locator("[data-preview-back]").click();
  await page.waitForTimeout(300);
  await closeAll();

  await page.locator(".row-title", { hasText: "待机循环" }).click();
  await page.waitForSelector(".detail-layout");
  await page.locator("[data-inspect-action='motion']").click();
  await page.waitForSelector("#motion-canvas", { timeout: 10000 });
  await page.waitForTimeout(600);
  await snap("motion-preview.png");
  await closeAll();

  await page.locator(".row-title", { hasText: "晨雾" }).click();
  await page.waitForTimeout(1200);
  await snap("playing.png");

  const rows = page.locator(".track-row");
  await rows.nth(0).locator("[data-select]").check({ force: true });
  await rows.nth(1).locator("[data-select]").check({ force: true });
  await page.locator("#selection-bar [data-action='bulk-rename']").click();
  await page.waitForSelector("#rename-form");
  await page.locator("#rename-name").fill("岛屿素材");
  await page.waitForTimeout(500);
  await snap("rename-preview.png");
  await close();

  await page.locator("[data-action='open-tag-filter']").click();
  await page.waitForTimeout(300);
  await page.locator("[data-tag-clear]").click();
  await page.waitForTimeout(200);

  await page.locator(".nav-item[data-view='categories']").click();
  await page.locator('[data-action="create-category"]').first().click();
  await page.waitForSelector("#create-category-form");
  await page.waitForTimeout(350);
  await snap("create-category.png");
  await close();

  await page.locator(".nav-item[data-view='library']").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  const pickRows = page.locator(".track-row");
  await pickRows.nth(0).locator("[data-select]").check({ force: true });
  await pickRows.nth(1).locator("[data-select]").check({ force: true });
  await page.locator("#selection-bar [data-action='bulk-category']").click();
  await page.waitForTimeout(400);
  await snap("category-picker.png");
  await close();

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(BASE, { waitUntil: "networkidle" });
  await mobile.waitForSelector(".track-row");
  await mobile.waitForTimeout(500);
  await mobile.screenshot({ path: path.join(OUT, "mobile-library.png") });

  console.log(JSON.stringify({ errors, shots: 13 }, null, 2));
  await browser.close();
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});

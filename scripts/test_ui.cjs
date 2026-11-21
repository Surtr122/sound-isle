const { chromium } = require(process.env.PW);

const BASE = process.env.BASE || "http://127.0.0.1:8787";

(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: "msedge",
    args: ["--use-angle=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  const consoleErrors = [];
  page.on("pageerror", (error) => errors.push(error.stack || String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector(".track-row", { timeout: 15000 });

  const initialRows = await page.locator(".track-row").count();
  const sourceChips = await page.locator(".source-chip").count();
  const sectionTitles = await page.locator(".section-title").allTextContents();

  await page.locator('[data-action="open-tag-filter"]').click();
  await page.waitForSelector(".tag-filter-choice");
  await page.locator("[data-tag-choice='夜晚']").check();
  await page.locator("[data-tag-apply]").click();
  await page.waitForTimeout(300);
  const taggedRows = await page.locator(".track-row").count();

  await page.locator('[data-action="open-tag-filter"]').click();
  await page.locator("[data-tag-clear]").click();
  await page.waitForTimeout(300);

  await page.locator("[data-type-filter]").selectOption("audio");
  await page.waitForTimeout(250);
  const audioRows = await page.locator(".track-row").count();
  await page.locator("[data-type-filter]").selectOption("all");
  await page.waitForTimeout(250);

  await page.locator('.nav-item[data-view="categories"]').click();
  await page.waitForTimeout(300);
  const hasSubDrawer = await page.locator(".section-title", { hasText: "大类下的小类" }).count();
  await page.locator('.category-card[data-category="animation"]').first().click();
  await page.waitForSelector(".drawer-layer");
  await page.waitForTimeout(300);
  const drawerWidth = await page.locator(".drawer-layer .modal").evaluate((node) => node.getBoundingClientRect().width);
  const drawerRows = await page.locator(".drawer-row").count();
  const removeButtons = await page.locator("[data-drawer-remove]").count();
  await page.locator("[data-close]").last().click();
  await page.waitForTimeout(250);

  await page.locator('.nav-item[data-view="library"]').click();
  await page.waitForTimeout(250);
  await page.locator('.row-title', { hasText: "蒙皮小人" }).first().click();
  await page.waitForSelector(".detail-layout");
  await page.locator('[data-inspect-action="skin"]').click();
  await page.waitForSelector(".skin-preview canvas", { timeout: 10000 });
  await page.waitForTimeout(800);
  const skinStatus = await page.locator("[data-skin-status]").first().innerText();
  const skinMeta = await page.locator("[data-skin-meta]").innerText();
  await page.locator("[data-preview-back]").click();
  await page.waitForSelector(".detail-layout");
  const returnedDetail = await page.locator(".detail-layout").count();
  await page.locator("[data-close]").last().click();
  await page.waitForTimeout(250);

  await page.locator('.row-title', { hasText: "待机循环" }).first().click();
  await page.waitForSelector(".detail-layout");
  await page.locator('[data-inspect-action="motion"]').click();
  await page.waitForSelector("#motion-canvas", { timeout: 10000 });
  const motionCanvas = await page.locator("#motion-canvas").count();
  await page.locator("[data-close]").last().click();

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(BASE, { waitUntil: "networkidle" });
  await mobile.waitForSelector(".track-row");
  const mobileWidth = await mobile.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));

  console.log(JSON.stringify({
    initialRows,
    sourceChips,
    sectionTitles,
    taggedRows,
    audioRows,
    hasSubDrawer,
    drawerWidth,
    drawerRows,
    removeButtons,
    skinStatus,
    skinMeta,
    returnedDetail,
    motionCanvas,
    mobileWidth,
    errors,
    consoleErrors,
  }, null, 2));
  await browser.close();
})().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});

// Render an HTML graphic to PNG at 2x: node reports/render.js in.html out.png
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const [input, output] = process.argv.slice(2);
  if (!input || !output) {
    console.error('usage: node reports/render.js in.html out.png');
    process.exit(1);
  }
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1000 }, deviceScaleFactor: 2 });
  await page.goto('file://' + path.resolve(input), { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: output, fullPage: true });
  await browser.close();
  console.log(output);
})();

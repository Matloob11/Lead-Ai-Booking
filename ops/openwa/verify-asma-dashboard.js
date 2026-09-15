const puppeteer = require('puppeteer');

const SESSION_ID = 'e209881a-0aa3-4463-849f-ff0ed37144b5';
const key = process.env.API_MASTER_KEY || process.env.API_KEY;
if (!key) throw new Error('master API key is unavailable');

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
  });
  try {
    const page = await browser.newPage();
    await page.goto('http://127.0.0.1:2785/', { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.evaluate(apiKey => {
      sessionStorage.setItem('openwa_api_key', apiKey);
      localStorage.setItem('openwa_user_role', 'admin');
    }, key);
    await page.goto('http://127.0.0.1:2785/chats', { waitUntil: 'networkidle0', timeout: 30_000 });
    await page.waitForSelector('select.session-selector', { timeout: 20_000 });

    const optionExists = await page.$eval(
      'select.session-selector',
      (select, id) => Array.from(select.options).some(option => option.value === id),
      SESSION_ID,
    );
    if (!optionExists) throw new Error('restored Asma is absent from dashboard selector');
    await page.select('select.session-selector', SESSION_ID);
    await page.waitForFunction(() => document.querySelectorAll('.chat-item-card').length > 0, { timeout: 20_000 });
    const chatCount = await page.$$eval('.chat-item-card', rows => rows.length);
    await page.click('.chat-item-card');
    await page.waitForFunction(() => document.querySelectorAll('.message-bubble').length > 0, { timeout: 20_000 });
    const messageBubbleCount = await page.$$eval('.message-bubble', rows => rows.length);

    await page.goto('http://127.0.0.1:2785/sessions', { waitUntil: 'networkidle0', timeout: 30_000 });
    await page.waitForSelector('.session-card', { timeout: 20_000 });
    const controlsPresent = await page.evaluate(() => {
      const heading = document.querySelector('.session-card h3[title="asma"]');
      const card = heading?.closest('.session-card');
      if (!card) return false;
      const buttons = Array.from(card.querySelectorAll('button'));
      const reset = buttons.some(button => button.textContent?.trim() === 'Reset profile');
      const remove = buttons.find(button => button.textContent?.trim() === 'Delete');
      if (!reset || !remove) return false;
      remove.click();
      return true;
    });
    if (!controlsPresent) throw new Error('restored Asma reset/delete controls are absent');
    await page.waitForFunction(
      () => document.querySelector('[role="dialog"]')?.textContent?.includes('675 stored messages') === true,
      { timeout: 20_000 },
    );

    console.log('dashboard-browser-asma-selector=PASS');
    console.log(`dashboard-browser-visible-chats=${chatCount}`);
    console.log(`dashboard-browser-open-thread-bubbles=${messageBubbleCount}`);
    console.log('dashboard-browser-stored-history=PASS');
    console.log('dashboard-browser-reset-control=PASS');
    console.log('dashboard-browser-delete-impact-675=PASS');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});

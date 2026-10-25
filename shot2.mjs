import puppeteer from "puppeteer-core";
const b = await puppeteer.launch({ executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe", headless: true, args: ["--no-sandbox"] });
const p = await b.newPage();
await p.setViewport({ width: 1440, height: 1000 });
await p.goto("http://localhost:5173/#/decision", { waitUntil: "networkidle0" });
await p.waitForSelector("#demand");
await new Promise(r => setTimeout(r, 800));
await p.screenshot({ path: "start.png", fullPage: true });
await p.type("#demand", "15000");
await new Promise(r => setTimeout(r, 400));
// Should NOT auto-calc: capture to prove no result yet
await p.screenshot({ path: "typed.png", fullPage: true });
await p.click('button[type="submit"]');
await p.waitForSelector('[data-testid="buy-total"]', { timeout: 15000 });
await new Promise(r => setTimeout(r, 1000));
await p.screenshot({ path: "loaded.png", fullPage: true });
await b.close();
console.log("ok");

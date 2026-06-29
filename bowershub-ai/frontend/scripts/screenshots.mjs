// Capture mobile + desktop screenshots with Playwright.
//   Default target = the deployed login page (no auth, no personal data).
//   For authed views: point SHOT_BASE at a seeded test stack, set SHOT_TOKEN
//   (a JWT for the test user) and SHOT_ROUTES (name:/path,name:/path).
import { chromium } from 'playwright'
import { mkdirSync } from 'fs'

const BASE = process.env.SHOT_BASE || 'http://localhost:5003'
const OUT = process.env.SHOT_OUT || '/home/michael/KiroProject/docs/screenshots'
const TOKEN = process.env.SHOT_TOKEN || ''
const USER = process.env.SHOT_USER || '' // JSON string for the auth store's `user`
const ROUTES = (process.env.SHOT_ROUTES || 'login:/login').split(',').map((s) => {
  const i = s.indexOf(':')
  return { name: s.slice(0, i), path: s.slice(i + 1) }
})
const VIEWPORTS = {
  desktop: { width: 1440, height: 900, isMobile: false },
  mobile: { width: 390, height: 844, isMobile: true, deviceScaleFactor: 2 },
}
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
for (const [vp, opts] of Object.entries(VIEWPORTS)) {
  const ctx = await browser.newContext({
    viewport: { width: opts.width, height: opts.height },
    isMobile: opts.isMobile,
    deviceScaleFactor: opts.deviceScaleFactor || 1,
  })
  const page = await ctx.newPage()
  if (TOKEN) {
    await page.goto(BASE + '/login').catch(() => {})
    await page.evaluate(
      ([t, u]) => {
        localStorage.setItem('accessToken', t)
        if (u) localStorage.setItem('user', u)
      },
      [TOKEN, USER],
    )
  }
  for (const r of ROUTES) {
    try {
      await page.goto(BASE + r.path, { waitUntil: 'networkidle', timeout: 15000 })
      await page.waitForTimeout(1500)
      const file = `${OUT}/${r.name}-${vp}.png`
      await page.screenshot({ path: file })
      console.log('saved', file)
    } catch (e) {
      console.log('FAILED', r.name, vp, String(e).slice(0, 140))
    }
  }
  await ctx.close()
}
await browser.close()

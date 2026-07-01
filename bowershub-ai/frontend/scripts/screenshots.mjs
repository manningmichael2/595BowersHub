// Capture mobile + desktop screenshots with Playwright.
//   Default target = the deployed login page (no auth, no personal data).
//   For authed views: point SHOT_BASE at a seeded test stack, set SHOT_TOKEN
//   and SHOT_ROUTES (name:/path,name:/path).
//
// Auth model: the PWA bootstraps a session from localStorage `refreshToken` +
// `user` (it does NOT read an access token from storage — see src/stores/auth.ts).
// So SHOT_TOKEN is a REFRESH token; on load the app exchanges it at
// /api/auth/refresh for an access token. Refresh tokens rotate on use and reuse
// trips theft-detection, so each browser context needs its OWN token: pass
// SHOT_TOKEN as a comma-separated list, one per viewport (desktop,mobile).
import { chromium } from 'playwright'
import { mkdirSync } from 'fs'

const BASE = process.env.SHOT_BASE || 'http://localhost:5003'
const OUT = process.env.SHOT_OUT || '/home/michael/KiroProject/docs/screenshots'
const TOKENS = (process.env.SHOT_TOKEN || '').split(',').map((s) => s.trim()).filter(Boolean)
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
let vpIndex = 0
for (const [vp, opts] of Object.entries(VIEWPORTS)) {
  const ctx = await browser.newContext({
    viewport: { width: opts.width, height: opts.height },
    isMobile: opts.isMobile,
    deviceScaleFactor: opts.deviceScaleFactor || 1,
  })
  const page = await ctx.newPage()
  // One refresh token per context (they can't be shared — see header note).
  const token = TOKENS[vpIndex] ?? TOKENS[0]
  if (token) {
    await page.goto(BASE + '/login').catch(() => {})
    await page.evaluate(
      ([t, u]) => {
        localStorage.setItem('refreshToken', t)
        if (u) localStorage.setItem('user', u)
      },
      [token, USER],
    )
  }
  for (const r of ROUTES) {
    try {
      await page.goto(BASE + r.path, { waitUntil: 'networkidle', timeout: 15000 })
      // The session bootstrap (refresh → access token) is async; if a guarded
      // route bounced us to /login before it settled, give it a beat and retry.
      if (token && r.path !== '/login' && page.url().includes('/login')) {
        await page.waitForTimeout(1500)
        await page.goto(BASE + r.path, { waitUntil: 'networkidle', timeout: 15000 })
      }
      await page.waitForTimeout(2000)
      const file = `${OUT}/${r.name}-${vp}.png`
      await page.screenshot({ path: file })
      console.log('saved', file)
    } catch (e) {
      console.log('FAILED', r.name, vp, String(e).slice(0, 140))
    }
  }
  await ctx.close()
  vpIndex++
}
await browser.close()

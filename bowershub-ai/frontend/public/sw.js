// BowersHub AI Service Worker — minimal pass-through, no caching, plus
// Web Share Target handler for Quick Capture.
//
// Why a fetch handler exists at all: Chrome on Android requires a service
// worker with an active fetch handler to qualify the site as installable
// (i.e. to show the "Install app" prompt instead of just "Add to Home
// screen"). A bare `addEventListener('fetch', () => {})` does NOT count
// because it never calls event.respondWith — we have to actually handle
// the request. Letting the SW pass requests through to the network keeps
// us installable without introducing the cache-staleness issues that
// motivated the May 26 disable.
//
// Web Share Target (R9.6, R9.7): manifest.json declares
// `share_target.action: "/quick-capture"` with `method: "POST"` and
// `enctype: "multipart/form-data"`. When the user shares text or an
// image to BowersHub from another Android app, the OS POSTs a multipart
// form to /quick-capture. The SPA can't read multipart bodies on
// navigation, so we intercept that POST here, stash the shared payload
// in a one-shot in-memory slot keyed by a short token, and redirect to
// /quick-capture?share=<token> so the SPA route can fetch it back via
// postMessage.
//
// When TODO #36 lands, this file will be replaced with a Workbox-managed
// service worker that does proper versioned caching.

const SHARE_TARGET_URL = '/quick-capture';

// One-shot share payload slots, keyed by a short token. Populated by the
// share-target POST handler, drained by a postMessage from the SPA.
// Lives in memory only — if the SW restarts before the SPA reads, the
// payload is lost (acceptable: user can just share again).
const _sharedPayloads = new Map();

function _makeShareToken() {
  // 9-char base36 string; unique enough for one-shot lookups.
  return Math.random().toString(36).slice(2, 11);
}

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.all([
      caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k)))),
      self.clients.claim(),
    ])
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Web Share Target: intercept POST /quick-capture from the OS share sheet.
  if (request.method === 'POST' && url.pathname === SHARE_TARGET_URL) {
    event.respondWith(_handleShareTarget(request));
    return;
  }

  // Network-only pass-through for GETs. Don't intercept WebSocket upgrades
  // or other non-GET methods.
  if (request.method !== 'GET') return;
  event.respondWith(fetch(request));
});

async function _handleShareTarget(request) {
  let payload = { title: '', text: '', url: '', files: [] };
  try {
    const form = await request.formData();
    payload.title = form.get('title') || '';
    payload.text = form.get('text') || '';
    payload.url = form.get('url') || '';
    // FormData.getAll returns File objects for file fields.
    const files = form.getAll('files') || [];
    for (const f of files) {
      // Only stash entries that are actually File-like (have arrayBuffer).
      if (f && typeof f.arrayBuffer === 'function') {
        const buffer = await f.arrayBuffer();
        payload.files.push({
          name: f.name || 'shared-file',
          type: f.type || 'application/octet-stream',
          size: f.size || buffer.byteLength,
          buffer,
        });
      }
    }
  } catch (err) {
    // Malformed multipart — fall through to the SPA with empty payload.
    // The Quick Capture overlay will just open with nothing pre-populated.
  }

  const token = _makeShareToken();
  _sharedPayloads.set(token, payload);

  // Auto-evict after 5 minutes so the in-memory map can't grow unbounded
  // if a client never claims its payload (e.g., user closes the share
  // intent before the SPA loads).
  setTimeout(() => {
    _sharedPayloads.delete(token);
  }, 5 * 60 * 1000);

  // Redirect to the SPA route. The SPA reads `?share=<token>` and asks
  // the SW for the payload via postMessage.
  return Response.redirect(`${SHARE_TARGET_URL}?share=${token}`, 303);
}

// SPA-side handshake: the Quick Capture page posts
// `{ type: 'share-target:claim', token }` to the SW; we reply with the
// payload and evict the slot so it's used at most once.
self.addEventListener('message', (event) => {
  const data = event.data;
  if (!data || typeof data !== 'object') return;

  if (data.type === 'share-target:claim' && typeof data.token === 'string') {
    const payload = _sharedPayloads.get(data.token);
    _sharedPayloads.delete(data.token);
    if (event.ports && event.ports[0]) {
      event.ports[0].postMessage({ ok: !!payload, payload: payload || null });
    } else if (event.source && typeof event.source.postMessage === 'function') {
      event.source.postMessage({
        type: 'share-target:payload',
        token: data.token,
        ok: !!payload,
        payload: payload || null,
      });
    }
  }
});

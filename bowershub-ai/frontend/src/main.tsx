import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import Toaster from './components/Toaster'
import ConfirmDialog from './components/ConfirmDialog'
import './index.css'
import { toast } from './stores/toast'
import { installGlobalErrorReporting } from './lib/reportError'

// Capture uncaught errors / unhandled rejections and report them so a silent
// break becomes visible (to the user via a toast, to the admin via the
// telemetry endpoint). Installed before render so it covers mount-time throws.
installGlobalErrorReporting()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <App />
        <Toaster />
        <ConfirmDialog />
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
)

// Register the service worker and surface updates. An installed PWA can stay
// pinned to an old bundle until it's fully closed; when a new worker installs
// while one is already in control, prompt the user to reload so they actually
// get the new code instead of silently running stale JS.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((reg) => {
        reg.addEventListener('updatefound', () => {
          const installing = reg.installing
          if (!installing) return
          installing.addEventListener('statechange', () => {
            // `installed` + an existing controller == an update (not first install).
            if (installing.state === 'installed' && navigator.serviceWorker.controller) {
              toast.info('A new version is available.', 0, {
                label: 'Reload',
                onClick: () => window.location.reload(),
              })
            }
          })
        })
      })
      .catch(() => {})
  })
}

/**
 * API client with auth token injection and 401 interceptor.
 */

import { useAuthStore } from '../stores/auth'
import { toast } from '../stores/toast'

const BASE_URL = ''

class ApiClient {
  private getToken(): string | null {
    return useAuthStore.getState().accessToken
  }

  private async request(method: string, path: string, data?: any, retry = true, extraHeaders?: Record<string, string>): Promise<any> {
    const token = this.getToken()
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    if (extraHeaders) {
      Object.assign(headers, extraHeaders)
    }

    const options: RequestInit = { method, headers }
    if (data && method !== 'GET') {
      options.body = JSON.stringify(data)
    }

    const response = await fetch(`${BASE_URL}${path}`, options)

    // Don't auto-retry on auth endpoints (prevents infinite loops)
    const isAuthEndpoint = path.startsWith('/api/auth/')

    // Handle 401 — try refresh once for non-auth endpoints
    if (response.status === 401 && retry && !isAuthEndpoint) {
      const refreshed = await useAuthStore.getState().refreshAuth()
      if (refreshed) {
        return this.request(method, path, data, false, extraHeaders)
      }
      // Refresh failed — logout cleanly
      toast.error('Your session expired. Please log in again.')
      useAuthStore.getState().logout()
      window.location.href = '/login'
      throw { response: { status: 401, data: { detail: 'Session expired' } } }
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Request failed' }))
      throw { response: { status: response.status, data: errorData } }
    }

    const contentType = response.headers.get('content-type')
    if (contentType?.includes('application/json')) {
      return { data: await response.json(), status: response.status }
    }
    return { data: await response.text(), status: response.status }
  }

  get(path: string) { return this.request('GET', path) }
  post(path: string, data?: any, headers?: Record<string, string>) { return this.request('POST', path, data, true, headers) }
  put(path: string, data?: any, headers?: Record<string, string>) { return this.request('PUT', path, data, true, headers) }
  patch(path: string, data?: any, headers?: Record<string, string>) { return this.request('PATCH', path, data, true, headers) }
  delete(path: string, headers?: Record<string, string>) { return this.request('DELETE', path, undefined, true, headers) }
}

export const api = new ApiClient()

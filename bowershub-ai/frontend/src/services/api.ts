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

  private async request<T = any>(method: string, path: string, data?: any, retry = true, extraHeaders?: Record<string, string>): Promise<{ data: T; status: number }> {
    const token = this.getToken()
    const isFormData = typeof FormData !== 'undefined' && data instanceof FormData
    const headers: Record<string, string> = {}
    // Let the browser set multipart Content-Type (with boundary) for FormData;
    // only force JSON for plain-object bodies.
    if (!isFormData) {
      headers['Content-Type'] = 'application/json'
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    if (extraHeaders) {
      Object.assign(headers, extraHeaders)
    }

    const options: RequestInit = { method, headers }
    if (data !== undefined && method !== 'GET') {
      options.body = isFormData ? data : JSON.stringify(data)
    }

    const response = await fetch(`${BASE_URL}${path}`, options)

    // Don't auto-retry on auth endpoints (prevents infinite loops)
    const isAuthEndpoint = path.startsWith('/api/auth/')

    // Handle 401 — try refresh once for non-auth endpoints
    if (response.status === 401 && retry && !isAuthEndpoint) {
      const refreshed = await useAuthStore.getState().refreshAuth()
      if (refreshed) {
        return this.request<T>(method, path, data, false, extraHeaders)
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
      return { data: (await response.json()) as T, status: response.status }
    }
    return { data: (await response.text()) as unknown as T, status: response.status }
  }

  // Generic over the response payload `T` (defaults to `any` so existing
  // untyped call sites keep compiling). Pass a type — `api.get<Foo>(path)` — to
  // get a typed `.data`; validate at the boundary with parseLoose (lib/validate)
  // when the shape matters. FormData bodies are sent as multipart automatically.
  get<T = any>(path: string) { return this.request<T>('GET', path) }
  post<T = any>(path: string, data?: any, headers?: Record<string, string>) { return this.request<T>('POST', path, data, true, headers) }
  put<T = any>(path: string, data?: any, headers?: Record<string, string>) { return this.request<T>('PUT', path, data, true, headers) }
  patch<T = any>(path: string, data?: any, headers?: Record<string, string>) { return this.request<T>('PATCH', path, data, true, headers) }
  delete<T = any>(path: string, headers?: Record<string, string>) { return this.request<T>('DELETE', path, undefined, true, headers) }
}

export const api = new ApiClient()

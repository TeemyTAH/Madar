const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/+$/, '')
const TOKEN_KEY = 'madar_access_token'

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  else sessionStorage.removeItem(TOKEN_KEY)
}

function errorMessage(payload, fallback) {
  if (typeof payload?.detail === 'string') return payload.detail
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg || JSON.stringify(item)).join('، ')
  }
  return fallback
}

export async function api(path, options = {}) {
  const { method = 'GET', body, headers = {}, signal } = options
  const requestHeaders = new Headers(headers)
  requestHeaders.set('Accept', 'application/json')

  const token = getToken()
  if (token) requestHeaders.set('Authorization', `Bearer ${token}`)

  let requestBody = body
  if (body !== undefined && !(body instanceof FormData) && !(body instanceof Blob)) {
    requestHeaders.set('Content-Type', 'application/json')
    requestBody = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: requestHeaders,
      body: requestBody,
      signal,
      credentials: 'same-origin',
    })
  } catch {
    throw new Error('تعذر الاتصال بالخادم. تأكد من تشغيل Madar API.')
  }

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => '')

  if (response.status === 401 && path !== '/auth/login' && path !== '/auth/bootstrap-admin') {
    setToken(null)
    window.dispatchEvent(new CustomEvent('madar:unauthorized'))
  }

  if (!response.ok) {
    throw new Error(errorMessage(payload, `فشل الطلب (${response.status})`))
  }
  return payload
}

export async function apiBlob(path) {
  const headers = new Headers()
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, { headers, credentials: 'same-origin' })
  } catch {
    throw new Error('تعذر تحميل الملف من الخادم.')
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(errorMessage(payload, `فشل تحميل الملف (${response.status})`))
  }
  return response.blob()
}

export async function downloadFile(path, fallbackName) {
  const blob = await apiBlob(path)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fallbackName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function apiImagePath(pageId, variant = 'original') {
  return `${API_BASE}/uploads/pages/${pageId}/image?variant=${variant}`
}

export async function healthCheck() {
  const healthUrl = API_BASE.startsWith('http')
    ? `${API_BASE.replace(/\/api\/v1$/, '')}/health`
    : '/health'
  const response = await fetch(healthUrl, { cache: 'no-store' })
  if (!response.ok) throw new Error('API health check failed')
  return response.json()
}

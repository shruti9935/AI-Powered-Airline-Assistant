// Small fetch wrapper — attaches the JWT and unwraps errors.
const BASE = '/api'

export function getToken() {
  return localStorage.getItem('token')
}

export function setToken(token) {
  if (token) localStorage.setItem('token', token)
  else localStorage.removeItem('token')
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, { ...options, headers })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    if (res.status === 401) setToken(null)
    const error = new Error(data.detail || `Request failed (${res.status})`)
    // Callers branch on the status code — the message is prose from the API
    // and never reliably contains it.
    error.status = res.status
    throw error
  }
  return data
}

export const api = {
  register: (email, password) =>
    request('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
  login: (email, password) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request('/auth/me'),
  chat: (message, language, conversationId) =>
    request('/chat', {
      method: 'POST',
      body: JSON.stringify({ message, language, conversation_id: conversationId ?? null }),
    }),
  history: () => request('/chat/history'),
  conversations: () => request('/conversations'),
  conversation: (id) => request(`/conversations/${id}`),
  escalate: (query_log_id, reason = 'user_marked_unhelpful') =>
    request('/escalate', { method: 'POST', body: JSON.stringify({ query_log_id, reason }) }),
}

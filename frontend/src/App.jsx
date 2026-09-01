import React, { useEffect, useState } from 'react'
import LoginForm from './components/LoginForm.jsx'
import ChatWindow from './components/ChatWindow.jsx'
import HistoryPanel from './components/HistoryPanel.jsx'
import { api, getToken, setToken } from './api.js'

export default function App() {
  // 'checking' until the stored token is verified — its mere presence proves
  // nothing, it may be expired or signed with an old secret.
  const [status, setStatus] = useState(getToken() ? 'checking' : 'anon')
  const [email, setEmail] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const [resumed, setResumed] = useState(null)

  useEffect(() => {
    if (status !== 'checking') return
    let cancelled = false
    api.me()
      .then((user) => { if (!cancelled) { setEmail(user.email); setStatus('authed') } })
      .catch(() => { if (!cancelled) { setToken(null); setStatus('anon') } })
    return () => { cancelled = true }
  }, [status])

  const logout = () => { setToken(null); setEmail(''); setResumed(null); setShowHistory(false); setStatus('anon') }
  const onAuthed = () => setStatus('checking')

  const resume = (conversation) => { setResumed(conversation); setShowHistory(false) }

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">✈️ SkyWings AI Assistant</span>
        {status === 'authed' && (
          <span className="topbar-actions">
            <button className="link" onClick={() => setShowHistory((v) => !v)}>
              {showHistory ? 'Back to chat' : 'History'}
            </button>
            <button className="link" onClick={logout}>Log out{email ? ` (${email})` : ''}</button>
          </span>
        )}
      </header>

      {status === 'checking' && <div className="card">Restoring your session…</div>}
      {status === 'anon' && <LoginForm onSuccess={onAuthed} />}
      {status === 'authed' && (showHistory
        ? <HistoryPanel onAuthError={logout} onOpen={resume} />
        : <ChatWindow onAuthError={logout} resumed={resumed} />)}
    </div>
  )
}

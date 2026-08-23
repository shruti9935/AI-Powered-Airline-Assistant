import React, { useState } from 'react'
import LoginForm from './components/LoginForm.jsx'
import ChatWindow from './components/ChatWindow.jsx'
import { getToken, setToken } from './api.js'

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()))

  const logout = () => { setToken(null); setAuthed(false) }

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">✈️ SkyWings AI Assistant</span>
        {authed && <button className="link" onClick={logout}>Log out</button>}
      </header>
      {authed
        ? <ChatWindow onAuthError={logout} />
        : <LoginForm onSuccess={() => setAuthed(true)} />}
    </div>
  )
}

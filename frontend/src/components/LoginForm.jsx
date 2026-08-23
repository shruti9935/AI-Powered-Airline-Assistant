import React, { useState } from 'react'
import { api, setToken } from '../api.js'

export default function LoginForm({ onSuccess }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const fn = mode === 'login' ? api.login : api.register
      const { access_token } = await fn(email, password)
      setToken(access_token)
      onSuccess()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card auth-card">
      <h2>{mode === 'login' ? 'Welcome back' : 'Create an account'}</h2>
      <form onSubmit={submit}>
        <input type="email" placeholder="Email" value={email} required
               onChange={(e) => setEmail(e.target.value)} />
        <input type="password" placeholder="Password (min 6 chars)" value={password}
               required minLength={6} onChange={(e) => setPassword(e.target.value)} />
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={busy}>
          {busy ? '…' : mode === 'login' ? 'Log in' : 'Register'}
        </button>
      </form>
      <button className="link" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>
        {mode === 'login' ? "New here? Register" : 'Already have an account? Log in'}
      </button>
    </div>
  )
}

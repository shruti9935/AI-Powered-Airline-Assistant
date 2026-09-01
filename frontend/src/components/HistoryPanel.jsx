import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function HistoryPanel({ onAuthError, onOpen }) {
  const [conversations, setConversations] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.conversations()
      .then((rows) => { if (!cancelled) setConversations(rows) })
      .catch((err) => {
        if (cancelled) return
        if (err.status === 401) return onAuthError()
        setError(err.message)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [onAuthError])

  const open = async (id) => {
    try {
      onOpen(await api.conversation(id))
    } catch (err) {
      if (err.status === 401) return onAuthError()
      setError(err.message)
    }
  }

  return (
    <div className="card history-card">
      <h2>Your conversations</h2>
      {loading && <p className="muted">Loading…</p>}
      {error && <div className="error">{error}</div>}
      {!loading && !error && conversations.length === 0 && (
        <p className="muted">No conversations yet — ask a question to start one.</p>
      )}
      <ul className="history-list">
        {conversations.map((c) => (
          <li key={c.id}>
            <button className="history-item" onClick={() => open(c.id)}>
              <span className="history-title">{c.title || `Conversation #${c.id}`}</span>
              <span className="muted">
                {c.turns} message{c.turns === 1 ? '' : 's'}
                {c.created_at ? ` · ${new Date(c.created_at).toLocaleString()}` : ''}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import LanguageSelector from './LanguageSelector.jsx'
import MessageBubble from './MessageBubble.jsx'

const GREETING = {
  role: 'bot',
  text: 'Hi! Ask me about baggage, check-in, refunds, delays, or special assistance — in English, हिन्दी, Español, or Français.',
}

export default function ChatWindow({ onAuthError, resumed }) {
  const [messages, setMessages] = useState([GREETING])
  const [input, setInput] = useState('')
  const [language, setLanguage] = useState('en')
  const [busy, setBusy] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const endRef = useRef(null)

  // Reopening a thread from the history panel restores it into the composer,
  // so follow-up questions continue the same conversation server-side.
  useEffect(() => {
    if (!resumed) return
    const restored = [GREETING]
    for (const turn of resumed.turns) {
      restored.push({ role: 'user', text: turn.query })
      restored.push({
        role: 'bot', text: turn.answer, confidence: turn.confidence,
        queryLogId: turn.query_log_id, escalated: turn.escalated, escalatedAuto: turn.escalated,
      })
    }
    setMessages(restored)
    setConversationId(resumed.id)
  }, [resumed])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleError = (err) => {
    if (err.status === 401) { onAuthError(); return true }
    return false
  }

  const send = async (e) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text }])
    setBusy(true)
    try {
      const res = await api.chat(text, language, conversationId)
      setConversationId(res.conversation_id)
      setMessages((m) => [...m, {
        role: 'bot',
        text: res.answer,
        sources: res.sources,
        confidence: res.confidence,
        escalated: res.escalated,
        escalatedAuto: res.escalated,
        department: res.escalation?.department,
        slaHours: res.escalation?.sla_hours,
        queryLogId: res.query_log_id,
      }])
      if (res.escalation?.message) {
        setMessages((m) => [...m, { role: 'bot', text: res.escalation.message }])
      }
    } catch (err) {
      if (handleError(err)) return
      setMessages((m) => [...m, { role: 'bot', text: '', error: err.message }])
    } finally {
      setBusy(false)
    }
  }

  // "Not helpful" — the manual half of the human-in-the-loop flow.
  const escalate = async (queryLogId) => {
    try {
      const res = await api.escalate(queryLogId)
      setMessages((m) => {
        const updated = m.map((msg) => msg.queryLogId === queryLogId
          ? { ...msg, escalated: true, escalatedAuto: false,
              department: res.department, slaHours: res.sla_hours }
          : msg)
        // The assistant confirms, in the passenger's language, who picked the
        // query up and when they will hear back.
        return res.message ? [...updated, { role: 'bot', text: res.message }] : updated
      })
    } catch (err) {
      if (handleError(err)) return
      setMessages((m) => m.map((msg) => msg.queryLogId === queryLogId
        ? { ...msg, error: err.message } : msg))
    }
  }

  const newChat = () => {
    setConversationId(null)
    setMessages([GREETING])
  }

  return (
    <div className="card chat-card">
      <div className="chat-head">
        <span>{conversationId ? `Conversation #${conversationId}` : 'New conversation'}</span>
        <button className="link" onClick={newChat} disabled={busy}>Start new chat</button>
      </div>
      <div className="messages">
        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} onEscalate={escalate} />
        ))}
        {busy && <div className="bubble bot typing">Thinking…</div>}
        <div ref={endRef} />
      </div>
      <form className="composer" onSubmit={send}>
        <LanguageSelector value={language} onChange={setLanguage} />
        <input value={input} onChange={(e) => setInput(e.target.value)}
               placeholder="Ask about your flight…" disabled={busy} />
        <button type="submit" disabled={busy || !input.trim()}>Send</button>
      </form>
    </div>
  )
}

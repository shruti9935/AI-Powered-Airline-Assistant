import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import LanguageSelector from './LanguageSelector.jsx'
import MessageBubble from './MessageBubble.jsx'

const GREETING = {
  role: 'bot',
  text: 'Hi! Ask me about baggage, check-in, refunds, delays, or special assistance — in English, हिन्दी, Español, or Français.',
}

export default function ChatWindow({ onAuthError }) {
  const [messages, setMessages] = useState([GREETING])
  const [input, setInput] = useState('')
  const [language, setLanguage] = useState('en')
  const [busy, setBusy] = useState(false)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (e) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text }])
    setBusy(true)
    try {
      const res = await api.chat(text, language)
      setMessages((m) => [...m, {
        role: 'bot',
        text: res.answer,
        sources: res.sources,
        confidence: res.confidence,
        escalated: res.escalated,
      }])
    } catch (err) {
      if (err.message.includes('401')) return onAuthError()
      setMessages((m) => [...m, { role: 'bot', text: '', error: err.message }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card chat-card">
      <div className="messages">
        {messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)}
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

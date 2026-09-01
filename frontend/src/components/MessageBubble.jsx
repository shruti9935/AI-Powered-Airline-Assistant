import React from 'react'
import EscalateBanner from './EscalateBanner.jsx'

export default function MessageBubble({ msg, onEscalate }) {
  if (msg.role === 'user') {
    return <div className="bubble user">{msg.text}</div>
  }
  const canEscalate = Boolean(onEscalate && msg.queryLogId && !msg.escalated)
  return (
    <div className="bubble bot">
      <div>{msg.text}</div>
      {msg.sources && msg.sources.length > 0 && (
        <div className="sources">
          Sources: {msg.sources.slice(0, 3).map((s) => s.section).join(' · ')}
          {typeof msg.confidence === 'number' && ` — confidence ${msg.confidence.toFixed(2)}`}
        </div>
      )}
      {msg.escalated && (
        <EscalateBanner auto={msg.escalatedAuto}
                        department={msg.department} slaHours={msg.slaHours} />
      )}
      {canEscalate && (
        <button className="link escalate-link" onClick={() => onEscalate(msg.queryLogId)}>
          Not helpful — talk to a human
        </button>
      )}
      {msg.error && <div className="error">{msg.error}</div>}
    </div>
  )
}

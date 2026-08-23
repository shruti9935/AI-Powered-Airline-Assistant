import React from 'react'

export default function EscalateBanner({ auto }) {
  return (
    <div className="escalated">
      {auto
        ? '📨 This query was escalated to the relevant airline department — a human agent will follow up by email.'
        : '📨 Escalated to a human agent.'}
    </div>
  )
}

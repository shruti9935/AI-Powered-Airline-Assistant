import React from 'react'

export default function EscalateBanner({ auto, department, slaHours }) {
  const team = department ? `${department} team` : 'relevant airline department'
  const within = slaHours ? ` They will contact you within ${slaHours} hours.` : ''
  return (
    <div className="escalated">
      {auto
        ? `📨 This query was escalated to the ${team}.${within}`
        : `📨 Escalated to the ${team}.${within}`}
    </div>
  )
}

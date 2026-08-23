import React from 'react'

const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
]

export default function LanguageSelector({ value, onChange }) {
  return (
    <select className="lang" value={value} onChange={(e) => onChange(e.target.value)}
            title="Answer language">
      {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
    </select>
  )
}

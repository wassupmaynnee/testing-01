import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
// Canonical design tokens — the dashboard's palette is the single source of
// truth; tailwind.config.js consumes its --rgb-* variables. Imported before
// index.css so the app's own base/component layers win any overlap.
import '../../web/tokens.css'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

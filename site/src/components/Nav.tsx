import { useState } from 'react'
import { NAV_LINKS } from '../data/content'
import Button from './ui/Button'
import Wordmark from './ui/Wordmark'

export default function Nav() {
  const [open, setOpen] = useState(false)

  return (
    <header className="sticky top-0 z-50">
      <div className="glass border-x-0 border-t-0">
        <nav
          aria-label="Primary"
          className="mx-auto flex max-w-content items-center justify-between gap-5 px-5 py-3 sm:px-8 lg:px-12"
        >
          <a href="#top" className="text-xl sm:text-2xl" aria-label="Clippify home">
            <Wordmark />
          </a>

          {/* Desktop links */}
          <ul className="hidden items-center gap-8 md:flex">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  className="text-sm font-medium text-text-dim transition-colors hover:text-text"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>

          {/* Desktop actions */}
          <div className="hidden items-center gap-3 md:flex">
            <Button variant="ghost" href="#" className="px-4 py-2">
              Sign in
            </Button>
            <Button variant="accent" href="#" className="px-4 py-2">
              Open app
            </Button>
          </div>

          {/* Mobile toggle */}
          <button
            type="button"
            className="btn btn-ghost px-3 py-2 md:hidden"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? 'Close menu' : 'Open menu'}
            onClick={() => setOpen((v) => !v)}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" fill="none">
              {open ? (
                <path
                  d="M6 6l12 12M18 6L6 18"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              ) : (
                <path
                  d="M4 7h16M4 12h16M4 17h16"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              )}
            </svg>
          </button>
        </nav>

        {/* Mobile menu */}
        {open && (
          <div id="mobile-menu" className="border-t border-white/10 md:hidden">
            <ul className="mx-auto flex max-w-content flex-col gap-1 px-5 py-4 sm:px-8">
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <a
                    href={link.href}
                    onClick={() => setOpen(false)}
                    className="block rounded-lg px-3 py-3 text-base font-medium text-text-dim transition-colors hover:bg-white/5 hover:text-text"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
              <li className="mt-2 flex flex-col gap-3">
                <Button variant="ghost" href="#" onClick={() => setOpen(false)}>
                  Sign in
                </Button>
                <Button variant="accent" href="#" onClick={() => setOpen(false)}>
                  Open app
                </Button>
              </li>
            </ul>
          </div>
        )}
      </div>
    </header>
  )
}

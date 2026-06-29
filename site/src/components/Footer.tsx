import { NAV_LINKS } from '../data/content'
import Wordmark from './ui/Wordmark'

export default function Footer() {
  return (
    <footer className="border-t border-white/10 py-10">
      <div className="mx-auto flex max-w-content flex-col items-center justify-between gap-6 px-5 sm:px-8 lg:flex-row lg:px-12">
        <a href="#top" className="text-lg" aria-label="Clippify home">
          <Wordmark />
        </a>

        <nav aria-label="Footer">
          <ul className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  className="text-sm text-text-faint transition-colors hover:text-text-dim"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <p className="text-sm text-text-faint">© 2026 Clippify · GPL-3.0</p>
      </div>
    </footer>
  )
}

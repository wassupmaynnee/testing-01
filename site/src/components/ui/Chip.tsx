import type { ReactNode } from 'react'

interface ChipProps {
  children: ReactNode
  className?: string
}

/** Small uppercase pill — orange text on a faint orange tint with an orange border. */
export default function Chip({ children, className = '' }: ChipProps) {
  return <span className={`chip ${className}`}>{children}</span>
}

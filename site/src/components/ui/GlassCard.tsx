import type { HTMLAttributes, ReactNode } from 'react'

interface GlassCardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  className?: string
}

/** Frosted-glass surface — the core card primitive of the design system. */
export default function GlassCard({ children, className = '', ...rest }: GlassCardProps) {
  return (
    <div className={`glass rounded-card ${className}`} {...rest}>
      {children}
    </div>
  )
}

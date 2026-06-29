import type { AnchorHTMLAttributes, ReactNode } from 'react'

interface ButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  variant?: 'accent' | 'ghost'
  children: ReactNode
  className?: string
}

/**
 * Anchor-based button (this is a static marketing page, so every CTA is a link).
 * accent = orange gradient pill; ghost = glass surface.
 */
export default function Button({
  variant = 'accent',
  children,
  className = '',
  ...rest
}: ButtonProps) {
  const variantClass = variant === 'accent' ? 'btn-accent' : 'btn-ghost'
  return (
    <a className={`btn ${variantClass} ${className}`} {...rest}>
      {children}
    </a>
  )
}

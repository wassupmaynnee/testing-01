interface WordmarkProps {
  className?: string
}

/** Text wordmark: "Clip" in white + "pify" in accent orange. */
export default function Wordmark({ className = '' }: WordmarkProps) {
  return (
    <span className={`font-display font-extrabold tracking-display ${className}`}>
      <span className="text-text">Clip</span>
      <span className="text-accent">pify</span>
    </span>
  )
}

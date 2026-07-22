'use client'

import { useState } from 'react'

interface Props {
  src: string
  alt: string
  className?: string
}

export default function CommunityImage({ src, alt, className }: Props) {
  const [failed, setFailed] = useState(false)
  if (failed) return null
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} className={className} onError={() => setFailed(true)} />
}

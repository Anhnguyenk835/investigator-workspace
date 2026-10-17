/** A link from a connected source is data a third party may have influenced. Only web
 *  addresses are ever made clickable; anything else (javascript:, data:, file:) is dropped. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null
  } catch {
    return null
  }
}

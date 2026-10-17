export const REVEAL_EVENT = 'workspace:reveal'

function flash(id: string): boolean {
  const el = document.getElementById(id)
  if (!el) return false
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: true })
  el.setAttribute('data-flash', '')
  window.setTimeout(() => el.removeAttribute('data-flash'), 2400)
  return true
}

/**
 * Scrolls a workspace record into view, focuses it and flashes an outline.
 * If the record lives in a tab that is not showing, the workspace is asked to open that tab first.
 * Resolves false when the record is still not on the page (for example, hidden by a filter).
 */
export async function revealAndFlash(id: string): Promise<boolean> {
  if (flash(id)) return true
  window.dispatchEvent(new CustomEvent(REVEAL_EVENT, { detail: id }))
  await new Promise((r) => setTimeout(r, 80))
  return flash(id)
}

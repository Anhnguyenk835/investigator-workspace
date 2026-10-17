/** Reads a Server-Sent Events response body (used for POST streams, which EventSource cannot do). */
export interface SseMessage {
  event: string
  data: unknown
}

function parseBlock(block: string): SseMessage | undefined {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith(':') || line === '') continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  if (data.length === 0) return undefined
  try {
    return { event, data: JSON.parse(data.join('\n')) as unknown }
  } catch {
    return undefined // a frame that is not JSON is ignored rather than ending the stream
  }
}

export async function* readSse(res: Response): AsyncGenerator<SseMessage> {
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let end = buffer.indexOf('\n\n')
      while (end !== -1) {
        const message = parseBlock(buffer.slice(0, end))
        buffer = buffer.slice(end + 2)
        if (message) yield message
        end = buffer.indexOf('\n\n')
      }
    }
    const rest = parseBlock(buffer)
    if (rest) yield rest
  } finally {
    reader.releaseLock()
  }
}

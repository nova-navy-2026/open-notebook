// Consumes a chat SSE body (newline-delimited `data: {...}` events) and invokes
// the given handlers for each delta/complete/error. Returns the final content.
// Shared by the send and regenerate paths so both parse the stream identically.

export interface ChatStreamHandlers {
  onDelta?: (accumulated: string) => void
  onComplete?: (full: string) => void
  onContextStats?: (data: unknown) => void
}

export async function consumeChatStream(
  body: ReadableStream<Uint8Array>,
  handlers: ChatStreamHandlers,
): Promise<string> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let content = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''
    for (const evt of events) {
      const line = evt.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.type === 'delta') {
          content += data.content || ''
          handlers.onDelta?.(content)
        } else if (data.type === 'complete') {
          content = data.content || content
          handlers.onComplete?.(content)
        } else if (data.type === 'context_stats') {
          handlers.onContextStats?.(data.data)
        } else if (data.type === 'error') {
          throw new Error(data.message || 'Stream error')
        }
      } catch (e) {
        if (!(e instanceof SyntaxError)) throw e
      }
    }
  }
  return content
}

import { navigationApi } from '@/lib/api/navigation'
import {
  formatRouteResponse,
  parseRouteRequest,
} from '@/lib/utils/chat-agents'
import {
  logChatAgentEvent,
  previewMessage,
  type ChatAgentRunContext,
} from '@/lib/chat-agents/logger'

export async function runRouteAgent(
  message: string,
  context?: ChatAgentRunContext,
  routeOverride?: { from?: unknown; to?: unknown },
): Promise<string | null> {
  const route = typeof routeOverride?.from === 'string' && typeof routeOverride?.to === 'string'
    ? { from: routeOverride.from.trim(), to: routeOverride.to.trim() }
    : parseRouteRequest(message)
  if (!route || !route.from || !route.to) return null

  const startedAt = performance.now()
  logChatAgentEvent({
    surface: context?.surface ?? 'global_chat',
    agent: 'route',
    event: 'selected',
    status: 'selected',
    context,
    message_preview: previewMessage(message),
    details: { from: route.from, to: route.to },
  })

  try {
    const result = await navigationApi.route({
      location_a: route.from,
      location_b: route.to,
      surface: context?.surface,
      run_id: context?.runId,
      session_id: context?.sessionId,
      notebook_id: context?.notebookId,
      model_id: context?.modelId,
    })
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'route',
      event: 'tool_call',
      status: 'success',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: {
        from: route.from,
        to: route.to,
        distance_km: result.distance_km,
        duration_min: result.duration_min,
      },
    })
    return formatRouteResponse(result, route.from, route.to)
  } catch (error) {
    logChatAgentEvent({
      surface: context?.surface ?? 'global_chat',
      agent: 'route',
      event: 'tool_call',
      status: 'failure',
      context,
      duration_ms: Math.round(performance.now() - startedAt),
      details: { error: error instanceof Error ? error.message : String(error) },
    })
    throw error
  }
}

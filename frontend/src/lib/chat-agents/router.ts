import { chatAgentLogsApi } from '@/lib/api/chat-agent-logs'
import type { ChatAgentRouteResponse } from '@/lib/api/chat-agent-logs'
import type { ChatAgentRunContext } from '@/lib/chat-agents/logger'

export async function routeChatAgentWithGemma({
  message,
  file,
  visualFollowUp,
  deepResearchEnabled,
  context,
}: {
  message: string
  file?: File
  visualFollowUp?: boolean
  deepResearchEnabled?: boolean
  context: ChatAgentRunContext
}): Promise<ChatAgentRouteResponse | null> {
  try {
    return await chatAgentLogsApi.route({
      surface: context.surface,
      message,
      has_file: Boolean(file),
      file_type: file?.type,
      file_name: file?.name,
      visual_follow_up: Boolean(visualFollowUp),
      deep_research_enabled: Boolean(deepResearchEnabled),
    })
  } catch (error) {
    console.debug('Gemma chat-agent router failed; falling back locally:', error)
    return null
  }
}

export function routedAgentIsTextInstruction(agent?: string): boolean {
  return Boolean(agent && [
    'table_extraction',
    'document_comparison',
    'checklist_procedure',
    'entity_extraction',
    'timeline',
    'report_builder',
  ].includes(agent))
}

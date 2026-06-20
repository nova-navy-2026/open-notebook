import { describe, expect, it } from 'vitest'
import {
  formatRouteResponse,
  formatTranscriptionResponse,
  parseMessageOrdinalFromEnd,
  parseRouteRequest,
  selectTargetAssistantMessage,
  wantsDiarization,
} from './chat-agents'
import { formatDeepResearchProgress } from '../chat-agents/deep-research-agent'
import type { NotebookChatMessage } from '@/lib/types/api'

describe('chat agent helpers', () => {
  it('parses Portuguese route requests with accents', () => {
    expect(parseRouteRequest('Qual a distância de Lisboa até Porto?')).toEqual({
      from: 'Lisboa',
      to: 'Porto',
    })
    expect(parseRouteRequest('Mostra o itinerário de Base Naval para Arsenal')).toEqual({
      from: 'Base Naval',
      to: 'Arsenal',
    })
    expect(parseRouteRequest('Mostra o itinerário de Base A para Arsenal')).toEqual({
      from: 'Base A',
      to: 'Arsenal',
    })
  })

  it('formats navigation estimated_time responses', () => {
    expect(formatRouteResponse({
      distance_km: 42.36,
      estimated_time: '0h48',
      route_preference: 'fastest',
      source: 'osrm',
    }, 'A', 'B')).toContain('- Tempo estimado: 0h48')
  })

  it('detects diarization requests', () => {
    expect(wantsDiarization('Transcreve e identifica os falantes')).toBe(true)
    expect(wantsDiarization('Transcreve o áudio')).toBe(false)
  })

  it('formats transcript segments when dialog is not provided', () => {
    expect(formatTranscriptionResponse({
      text: 'fallback',
      language: 'pt',
      segments: [
        { start: 0, end: 2.4, speaker: 'SPEAKER_00', text: 'Olá.' },
        { start: 2.5, end: 5, speaker: 'SPEAKER_01', text: 'Recebido.' },
      ],
    })).toContain('[0:00-0:02] SPEAKER_00: Olá.')
  })

  it('formats deep research messages with the readable model name', () => {
    const content = formatDeepResearchProgress(
      'Investiga segurança marítima',
      {
        reportType: 'research_report',
        tone: 'Objective',
        modelId: 'model:abc123',
        modelName: 'AMALIA-9B',
      },
      'job-1',
    )

    expect(content).toContain('- Modelo: AMALIA-9B')
    expect(content).not.toContain('- Modelo: model:abc123')
  })

  it('parses which message from the end the user wants', () => {
    expect(parseMessageOrdinalFromEnd('guarda isto como nota')).toBe(1)
    expect(parseMessageOrdinalFromEnd('guarda a última resposta como nota')).toBe(1)
    expect(parseMessageOrdinalFromEnd('guarda a penúltima resposta como nota')).toBe(2)
    expect(parseMessageOrdinalFromEnd('guarda a antepenúltima como nota')).toBe(3)
    expect(parseMessageOrdinalFromEnd('save the third to last message')).toBe(3)
    expect(parseMessageOrdinalFromEnd('save the 2nd to last as a note')).toBe(2)
    expect(parseMessageOrdinalFromEnd('guarda a terceira a contar do fim')).toBe(3)
    expect(parseMessageOrdinalFromEnd('guarda a 4ª resposta a contar do final')).toBe(4)
  })

  it('selects the target assistant message counted from the end', () => {
    const messages: NotebookChatMessage[] = [
      { id: 'h1', type: 'human', content: 'q1', timestamp: '' },
      { id: 'a1', type: 'ai', content: 'A1', timestamp: '' },
      { id: 'h2', type: 'human', content: 'q2', timestamp: '' },
      { id: 'a2', type: 'ai', content: 'A2', timestamp: '' },
      { id: 'h3', type: 'human', content: 'q3', timestamp: '' },
      { id: 'a3', type: 'ai', content: 'A3', timestamp: '' },
    ]
    expect(selectTargetAssistantMessage('guarda como nota', messages)?.id).toBe('a3')
    expect(selectTargetAssistantMessage('guarda a penúltima como nota', messages)?.id).toBe('a2')
    expect(selectTargetAssistantMessage('save the third to last as a note', messages)?.id).toBe('a1')
    // out of range clamps to the oldest assistant message
    expect(selectTargetAssistantMessage('guarda a 9ª a contar do fim', messages)?.id).toBe('a1')
  })
})

import { describe, expect, it } from 'vitest'
import {
  formatRouteResponse,
  formatTranscriptionResponse,
  parseRouteRequest,
  wantsDiarization,
} from './chat-agents'
import { formatDeepResearchProgress } from '../chat-agents/deep-research-agent'

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
})

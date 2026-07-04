import { describe, it, expect } from 'vitest'
import {
  parseSourceReferences,
  convertReferencesToMarkdownLinks,
} from './source-references'

describe('navy citation parsing', () => {
  it('parses a whole-bracket navy ref with raw-filename payload', () => {
    const refs = parseSourceReferences('[navy:PEETNA 3253 - Logística I.pdf:p12:s3]')
    expect(refs).toHaveLength(1)
    expect(refs[0].type).toBe('navy')
    expect(refs[0].id).toBe('PEETNA 3253 - Logística I.pdf:p12:s3')
  })

  it('splits two navy refs sharing one bracket', () => {
    const refs = parseSourceReferences('[navy:doc a.pdf:p3:s1, navy:doc b.pdf:p7:s9]')
    expect(refs.map((r) => r.id)).toEqual(['doc a.pdf:p3:s1', 'doc b.pdf:p7:s9'])
  })

  it('handles a navy ref followed by another ref type in the same bracket', () => {
    const refs = parseSourceReferences('[navy:doc a.pdf:p3, source:abc123]')
    expect(refs.map((r) => [r.type, r.id])).toEqual([
      ['navy', 'doc a.pdf:p3'],
      ['source', 'abc123'],
    ])
  })

  it('handles a navy ref preceded by another ref type in the same bracket', () => {
    const refs = parseSourceReferences('[source:abc123, navy:doc a.pdf:p3]')
    expect(refs.map((r) => [r.type, r.id])).toEqual([
      ['source', 'abc123'],
      ['navy', 'doc a.pdf:p3'],
    ])
  })

  it('keeps the historical [[navy:X]](#href) shape for whole-bracket refs', () => {
    const out = convertReferencesToMarkdownLinks('[navy:x (y).pdf:p2:s5]')
    expect(out).toBe(
      '[[navy:x (y).pdf:p2:s5]](#ref-navy-x%20%28y%29.pdf%3Ap2%3As5)'
    )
  })

  it('links each ref of a mixed bracket separately', () => {
    const out = convertReferencesToMarkdownLinks('[source:abc123, navy:doc a.pdf:p3]')
    expect(out).toContain('[source:abc123](#ref-source-abc123)')
    expect(out).toContain('[navy:doc a.pdf:p3](#ref-navy-doc%20a.pdf%3Ap3)')
  })

  it('ignores brackets without navy refs', () => {
    expect(parseSourceReferences('[just a heading]')).toHaveLength(0)
  })
})

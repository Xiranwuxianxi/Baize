import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { _useLang, t } from './i18n'
import en from './locales/en'

afterEach(() => _useLang('zh'))

function sources(dir: string): string {
  return readdirSync(dir).map((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return name === 'locales' ? '' : sources(full)
    return /\.(jsx|tsx|ts)$/.test(name) && !/\.test\./.test(name) ? readFileSync(full, 'utf8') : ''
  }).join('\n')
}

describe('i18n', () => {
  it('shows Chinese by default and falls back to it when a translation is missing', () => {
    expect(t('消息')).toBe('消息')
    _useLang('en')
    expect(t('消息')).toBe('Chats')
    expect(t('这句还没有翻译')).toBe('这句还没有翻译')
  })

  it('fills placeholders', () => {
    _useLang('en')
    expect(t('发给{name}…', { name: '老周' })).toBe('Message 老周…')
    expect(t('不选则由{name}安排', { name: 'Ada' })).toBe('None selected: Ada decides')
  })

  it('every English entry still matches text in the source (no stale translations)', () => {
    const code = sources(join(import.meta.dirname, '..'))
    const stale = Object.keys(en).filter((zh) => !code.includes(zh))
    expect(stale).toEqual([])
  })

  it('every placeholder in a translation exists in its source text', () => {
    for (const [zh, english] of Object.entries(en)) {
      for (const v of english.match(/\{\w+\}/g) || []) expect(zh).toContain(v)
    }
  })
})

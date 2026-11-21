import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setToken, wsUrl } from './api'

const store: Record<string, string> = {}

beforeEach(() => {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v },
  })
  vi.stubGlobal('location', { protocol: 'https:', host: 'example.test:18760' })
})
afterEach(() => vi.unstubAllGlobals())

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('api', () => {
  it('puts the access token in a header, never in the URL', async () => {
    setToken('口令 123')
    const fetchMock = mockFetch(200, { ok: true })
    await api('POST', '/lessons', { text: 'x' })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/lessons')
    expect(url).not.toContain('token')
    expect((init.headers as Record<string, string>)['X-Access-Token']).toBe(encodeURIComponent('口令 123'))
    expect(init.body).toBe(JSON.stringify({ text: 'x' }))
  })

  it('turns error responses into ApiError with the server message and status', async () => {
    mockFetch(429, { detail: '口令输错次数太多，请 15 分钟后再试' })
    const err = await api('GET', '/state').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(429)
    expect(err.message).toBe('口令输错次数太多，请 15 分钟后再试')
  })

  it('falls back to a readable message when the body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('oops', { status: 502 })))
    await expect(api('GET', '/state')).rejects.toThrow('请求失败（HTTP 502）')
  })

  it('builds a secure WebSocket URL on https', () => {
    expect(wsUrl()).toBe('wss://example.test:18760/ws')
  })
})

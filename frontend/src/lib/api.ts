// 和后端打交道的边界层：所有请求都从这里发出，口令只放在请求头里，从不出现在网址中。

const TOKEN_KEY = 'mac_token'

export const getToken = (): string => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t: string): void => localStorage.setItem(TOKEN_KEY, t)

/** 接口返回非 2xx 时抛出的错误：message 是给用户看的中文说明，status 是 HTTP 状态码。 */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

const authHeader = (): Record<string, string> => ({ 'X-Access-Token': encodeURIComponent(getToken()) })

async function errorFrom(res: Response, fallback: string): Promise<ApiError> {
  const data: { detail?: unknown } = await res.json().catch(() => ({}))
  return new ApiError(typeof data.detail === 'string' ? data.detail : `${fallback}（HTTP ${res.status}）`, res.status)
}

export type Method = 'GET' | 'POST' | 'PUT' | 'DELETE'

/** 调用 JSON 接口。path 不带 /api 前缀，例如 api('GET', '/state')。 */
export async function api<T = any>(method: Method, path: string, body?: unknown): Promise<T> {
  const res = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...authHeader() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw await errorFrom(res, '请求失败')
  return res.json().catch(() => ({}) as T)
}

/** 按当前访问的域名 / 端口拼 WebSocket 地址，手机经局域网 IP 访问时同样可用。 */
export const wsUrl = (): string => (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws'

/** 在新标签页里查看一个需要口令的文件：口令放在请求头里取回内容，再用临时地址打开。 */
export async function openAuthed(path: string): Promise<void> {
  const win = window.open('', '_blank') // 先同步开窗口，异步之后再开会被浏览器拦截
  try {
    const res = await fetch('/api' + path, { headers: authHeader() })
    if (!res.ok) throw await errorFrom(res, '打不开')
    const url = URL.createObjectURL(await res.blob())
    if (win) win.location.href = url
    else window.location.assign(url)
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    win?.close()
    throw e
  }
}

/** 下载一个需要口令的文件（备份等）。 */
export async function downloadAuthed(path: string, fallbackName: string): Promise<void> {
  const res = await fetch('/api' + path, { headers: authHeader() })
  if (!res.ok) throw await errorFrom(res, '下载失败')
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] || fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

/** 上传原始文件内容（恢复备份等）。 */
export async function uploadRaw<T = any>(path: string, file: Blob): Promise<T> {
  const res = await fetch('/api' + path, { method: 'POST', headers: authHeader(), body: file })
  if (!res.ok) throw await errorFrom(res, '上传失败')
  return res.json()
}

/** 取回一个需要口令的文件，返回临时地址（用完记得 URL.revokeObjectURL）。图片缩略图等用。 */
export async function blobUrl(path: string): Promise<string> {
  const res = await fetch('/api' + path, { headers: authHeader() })
  if (!res.ok) throw await errorFrom(res, '打不开')
  return URL.createObjectURL(await res.blob())
}

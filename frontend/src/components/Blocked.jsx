import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'

// 口令输错太多次被暂时锁住的地址：能看到是谁，也能手动解除
export default function Blocked({ notify, locked }) {
  const [info, setInfo] = useState(null)
  const load = useCallback(() => api('GET', '/security/blocked').then(setInfo).catch(() => {}), [])
  useEffect(() => { load(); const t = setInterval(load, 30_000); return () => clearInterval(t) }, [load])
  if (!info) return null
  const unblock = async (ip) => {
    try { setInfo({ ...info, ...(await api('POST', '/security/unblock', ip ? { ip } : {})) }); notify(ip ? `已解除 ${ip}` : '已全部解除') } catch (e) { notify(e.message) }
  }
  return (
    <div className="rounded-xl bg-sunken px-4 py-3 text-[13px] leading-relaxed text-muted">
      <div>防爆破：同一个地址 {info.window_minutes} 分钟内输错 {info.limit} 次口令，会被锁 {info.block_minutes} 分钟。这台电脑自己不会被锁。</div>
      {info.blocked.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {info.blocked.map((b) => (
            <li key={b.ip} className="flex items-center gap-3">
              <span className="font-mono text-ink">{b.ip}</span>
              <span className="text-xs text-faint">还要锁 {Math.ceil(b.seconds / 60)} 分钟</span>
              <button type="button" disabled={locked} onClick={() => unblock(b.ip)} className="ml-auto rounded-md px-2 py-0.5 text-xs text-accent-ink hover:bg-surface disabled:opacity-50">解除</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

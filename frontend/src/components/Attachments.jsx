// 消息里的附件：图片显示缩略图（口令放在请求头里取回），其他文件显示名字和大小，点开查看
import { useEffect, useState } from 'react'
import { blobUrl, openAuthed } from '../lib/api'
import { sizeText } from '../lib/attach'
import { Icon } from './ui.jsx'

const fileUrl = (conv, path) => `/files?conv=${encodeURIComponent(conv)}&path=${encodeURIComponent(path)}`

function Thumb({ conv, a, onOpen }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let url = ''
    let live = true
    blobUrl(fileUrl(conv, a.path)).then((u) => { url = u; if (live) setSrc(u); else URL.revokeObjectURL(u) }).catch(() => {})
    return () => { live = false; if (url) URL.revokeObjectURL(url) }
  }, [conv, a.path])
  return (
    <button type="button" onClick={onOpen} title={a.name} className="block h-24 w-24 overflow-hidden rounded-xl bg-sunken ring-1 ring-black/5 transition-transform duration-150 active:scale-[0.98] md:h-28 md:w-28">
      {src ? <img src={src} alt={a.name} className="h-full w-full object-cover" /> : <span className="skeleton block h-full w-full" />}
    </button>
  )
}

export function FileChip({ a, onClick, onRemove, busy, error }) {
  return (
    <span className={'inline-flex h-9 max-w-[240px] items-center gap-2 rounded-xl border px-2.5 text-xs ' + (error ? 'border-danger/40 text-danger' : 'border-line bg-surface text-ink')}>
      <Icon name={a.kind === 'image' ? 'image' : 'file'} size={15} className="shrink-0 text-muted" />
      <button type="button" onClick={onClick} disabled={!onClick} className="min-w-0 truncate text-left disabled:cursor-default">{a.name}</button>
      <span className="shrink-0 text-faint">{busy ? '上传中…' : error ? '失败' : a.size ? sizeText(a.size) : ''}</span>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={'移除 ' + a.name} className="-mr-1 shrink-0 rounded p-0.5 text-faint hover:bg-sunken hover:text-ink">
          <Icon name="x" size={13} />
        </button>
      )}
    </span>
  )
}

export default function Attachments({ conv, items, notify, align = 'end' }) {
  if (!items?.length) return null
  const open = (a) => openAuthed(fileUrl(conv, a.path)).catch((e) => notify?.(e.message))
  const pics = items.filter((a) => a.kind === 'image')
  const rest = items.filter((a) => a.kind !== 'image')
  return (
    <div className={'flex flex-col gap-1.5 ' + (align === 'end' ? 'items-end' : 'items-start')}>
      {pics.length > 0 && <div className="flex flex-wrap justify-end gap-1.5">{pics.map((a) => <Thumb key={a.path} conv={conv} a={a} onOpen={() => open(a)} />)}</div>}
      {rest.length > 0 && <div className="flex flex-wrap justify-end gap-1.5">{rest.map((a) => <FileChip key={a.path} a={a} onClick={() => open(a)} />)}</div>}
    </div>
  )
}

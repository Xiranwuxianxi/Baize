import { useEffect, useRef } from 'react'
import { Icon } from './ui.jsx'

// 右键菜单：在鼠标位置弹出，点别处、按 Esc、滚动都会关闭
export default function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    const close = (e) => { if (!ref.current?.contains(e.target)) onClose() }
    const key = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', key)
    window.addEventListener('scroll', onClose, true)
    window.addEventListener('resize', onClose)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', key)
      window.removeEventListener('scroll', onClose, true)
      window.removeEventListener('resize', onClose)
    }
  }, [onClose])
  // 别超出窗口
  const left = Math.min(x, window.innerWidth - 188)
  const top = Math.min(y, window.innerHeight - items.length * 36 - 16)
  return (
    <ul ref={ref} role="menu" style={{ left, top }} className="animate-fade fixed z-[70] w-44 overflow-hidden rounded-xl border border-line bg-surface p-1 shadow-float">
      {items.map((it) => (
        <li key={it.label} role="none">
          <button type="button" role="menuitem" onClick={() => { onClose(); it.onClick() }}
            className={'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors duration-100 ' + (it.danger ? 'text-danger hover:bg-danger-soft' : 'text-ink hover:bg-sunken')}>
            <Icon name={it.icon} size={15} className={it.danger ? '' : 'text-muted'} />{it.label}
          </button>
        </li>
      ))}
    </ul>
  )
}

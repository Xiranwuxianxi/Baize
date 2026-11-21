// 输入区：点名按钮、@ 自动补全、附件（选择 / 粘贴 / 拖进来）、发送 / 停止
import { useEffect, useRef, useState } from 'react'
import { FileChip } from '../../components/Attachments.jsx'
import { Avatar, Btn, Chip, IconBtn } from '../../components/ui.jsx'
import { t } from '../../lib/i18n'

export default function Composer({ agents, lead, text, setText, targets, setTargets, inputRef, running, online, onSubmit, onStop, blocked, sendLabel, canNudge, files = [], onAddFiles, onRemoveFile }) {
  const picker = useRef(null)
  const [dragging, setDragging] = useState(false)
  const onPaste = (e) => {
    const list = [...(e.clipboardData?.files || [])]
    if (list.length && onAddFiles) { e.preventDefault(); onAddFiles(list) }
  }
  const onDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    const list = [...(e.dataTransfer?.files || [])]
    if (list.length && onAddFiles) onAddFiles(list)
  }
  const multi = agents.length > 1
  const empty = !text.trim() && !files.some((f) => f.info)
  const toggleTarget = (id) => setTargets((t) => (t.includes(id) ? t.filter((x) => x !== id) : [...t, id]))

  // 输入框随内容长高，最多 160px
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [text, inputRef])

  // @ 补全：光标前是「@若干字」时弹出成员列表
  const [mention, setMention] = useState(null) // { q, start, i }
  const mentionList = mention ? agents.filter((a) => a.name.toLowerCase().includes(mention.q.toLowerCase())) : []
  const submit = () => { if (onSubmit()) setMention(null) }
  const onType = (e) => {
    const v = e.target.value
    setText(v)
    const pos = e.target.selectionStart
    const m = /@([^\s@]{0,20})$/.exec(v.slice(0, pos))
    setMention(m && agents.length ? { q: m[1], start: pos - m[0].length, i: 0 } : null)
  }
  const pickMention = (a) => {
    const end = mention.start + 1 + mention.q.length
    setText(text.slice(0, mention.start) + '@' + a.name + ' ' + text.slice(end))
    setMention(null)
    setTargets((t) => (t.includes(a.id) ? t : [...t, a.id]))
    requestAnimationFrame(() => {
      const el = inputRef.current
      if (el) { el.focus(); const p = mention.start + a.name.length + 2; el.setSelectionRange(p, p) }
    })
  }
  const onKey = (e) => {
    if (mention && mentionList.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const d = e.key === 'ArrowDown' ? 1 : -1
        setMention({ ...mention, i: (mention.i + d + mentionList.length) % mentionList.length })
        return
      }
      if ((e.key === 'Enter' || e.key === 'Tab') && !e.nativeEvent.isComposing) {
        e.preventDefault()
        pickMention(mentionList[mention.i] || mentionList[0])
        return
      }
      if (e.key === 'Escape') { setMention(null); return }
    }
    // 电脑上 Enter 发送、Shift+Enter 换行；触屏设备 Enter 换行，点按钮发送
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !matchMedia('(pointer: coarse)').matches) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="shrink-0 px-3 pt-1 pb-[max(0.75rem,env(safe-area-inset-bottom))] md:px-8 md:pb-5">
      <div className="mx-auto max-w-[820px]">
        {multi && (
          <div className="no-bar mb-2 flex items-center gap-1.5 overflow-x-auto">
            <span className="shrink-0 text-xs text-faint">{t('@ 点名')}</span>
            {agents.map((a) => (
              <Chip key={a.id} on={targets.includes(a.id)} onClick={() => toggleTarget(a.id)} className="h-7 pr-2.5 pl-0.5 text-xs">
                <Avatar agent={a} size={20} />{a.name}
              </Chip>
            ))}
            {!targets.length && <span className="shrink-0 pl-1 text-xs text-faint">{lead ? t('不选则由{name}安排', { name: lead.name }) : t('不选则全员发言')}</span>}
          </div>
        )}
        {files.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {files.map((f) => <FileChip key={f.id} a={f.info || { name: f.name, kind: f.kind }} busy={f.busy} error={f.error} onRemove={() => onRemoveFile(f.id)} />)}
          </div>
        )}
        <div onDragOver={(e) => { if (onAddFiles && e.dataTransfer?.types?.includes('Files')) { e.preventDefault(); setDragging(true) } }} onDragLeave={() => setDragging(false)} onDrop={onDrop}
          className={(dragging ? 'border-accent! ' : '') + "relative flex items-end gap-2 rounded-[20px] border border-line/70 bg-raised p-1.5 shadow-[0_10px_30px_-18px_rgb(var(--shadow)/0.35)] transition-[border-color,box-shadow] duration-200 focus-within:border-accent focus-within:shadow-[0_0_0_4px_var(--accent-soft),0_10px_30px_-18px_rgb(var(--shadow)/0.35)]"}>
          {mention && mentionList.length > 0 && (
            <ul role="listbox" aria-label={t('选择要点名的智能体')} className="absolute bottom-full left-1.5 z-20 mb-2 w-64 overflow-hidden rounded-xl border border-line bg-surface p-1 shadow-float">
              {mentionList.map((a, i) => (
                <li key={a.id} role="option" aria-selected={i === mention.i}>
                  <button type="button" onMouseDown={(e) => { e.preventDefault(); pickMention(a) }} onMouseEnter={() => setMention({ ...mention, i })}
                    className={'flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm ' + (i === mention.i ? 'bg-accent-soft text-accent-ink' : 'text-ink')}>
                    <Avatar agent={a} size={24} />
                    <span className="min-w-0 flex-1 truncate">{a.name}</span>
                    <span className="max-w-[45%] truncate text-xs text-faint">{a.description || ''}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {onAddFiles && (
            <>
              <input ref={picker} type="file" multiple hidden onChange={(e) => { onAddFiles([...e.target.files]); e.target.value = '' }} />
              <IconBtn icon="clip" label={t('添加图片或文件（也可以直接粘贴、拖进来）')} size={38} onClick={() => picker.current?.click()} className="shrink-0" />
            </>
          )}
          <textarea
            ref={inputRef}
            onPaste={onPaste}
            rows={1}
            value={text}
            onChange={onType}
            onBlur={() => setTimeout(() => setMention(null), 120)}
            onKeyDown={onKey}
            aria-label={t('消息内容')}
            placeholder={agents.length ? (lead ? t('发给{name}…（输入 @ 点名成员）', { name: lead.name }) : multi ? t('发给所有人…（输入 @ 点名）') : t('发给{name}…', { name: agents[0].name })) : t('先为这个会话新建智能体')}
            className="block max-h-[160px] min-h-[38px] flex-1 resize-none bg-transparent px-2.5 py-2 text-[16px] leading-snug text-ink outline-none placeholder:text-faint"
          />
          {running ? (
            <Btn kind="outline" icon="stop" onClick={onStop} className="h-[38px] shrink-0">{t('停止')}</Btn>
          ) : (
            <Btn kind="primary" disabled={!!blocked} title={blocked || sendLabel} onClick={submit} className="h-[38px] shrink-0 px-4">{empty && canNudge ? t('继续') : t('发送')}</Btn>
          )}
        </div>
        {!online && <p role="status" className="mt-2 text-center text-xs text-danger">{t('与服务器的连接已断开，正在自动重连…')}</p>}
      </div>
    </div>
  )
}

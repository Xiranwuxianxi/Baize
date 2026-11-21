import { useEffect, useRef, useState } from 'react'
import { Btn, Modal, inputCls } from './ui.jsx'

// 应用内的确认 / 输入框，替代浏览器自带的 confirm() / prompt() / alert()。
// 一些内嵌浏览器（桌面应用里的网页面板、部分手机 WebView）会直接吞掉原生弹窗并当作「取消」，导致删除等操作点了没反应。
//
//   if (!(await ask('删除技能「x」？'))) return
//   const name = await ask('新的会话标题', { input: '旧标题' })   // 取消时返回 null
let show = null

export function ask(text, opts = {}) {
  if (!show) return Promise.resolve(opts.input !== undefined ? null : false)
  return new Promise((resolve) => show({ text, ...opts, resolve }))
}

export function DialogHost() {
  const [d, setD] = useState(null)
  const [value, setValue] = useState('')
  const inputRef = useRef(null)
  useEffect(() => {
    show = (next) => { setValue(next.input ?? ''); setD(next) }
    return () => { show = null }
  }, [])
  useEffect(() => { if (d && d.input !== undefined) setTimeout(() => inputRef.current?.select(), 30) }, [d])
  if (!d) return null
  const isInput = d.input !== undefined
  const danger = d.danger ?? /删除|清空|清除/.test(d.text)
  const finish = (result) => { d.resolve(result); setD(null) }
  // 短句直接做标题；长句用简短标题（确认删除 / 请确认），完整内容放正文
  const [first, ...rest] = String(d.text).split('\n')
  const short = !isInput && first.length <= 16
  const title = d.title || (isInput || short ? first : danger ? '确认删除' : '请确认')
  const body = d.title ? d.text : isInput || short ? rest.join('\n').trim() : String(d.text).trim()
  return (
    <Modal title={title} onClose={() => finish(isInput ? null : false)}
      footer={<>
        {d.cancel !== false && <Btn kind="ghost" onClick={() => finish(isInput ? null : false)}>取消</Btn>}
        <Btn kind={danger ? 'danger' : 'primary'} autoFocus={!isInput} className={danger ? 'border border-danger/40' : ''}
          onClick={() => finish(isInput ? value.trim() || null : true)}>{d.ok || (danger ? '删除' : '确定')}</Btn>
      </>}>
      {body && <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted [overflow-wrap:anywhere]">{body}</p>}
      {isInput && (
        <input ref={inputRef} className={inputCls} value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) finish(value.trim() || null) }} />
      )}
    </Modal>
  )
}

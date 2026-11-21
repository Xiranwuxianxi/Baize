import { ask } from '../components/Dialog.jsx'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { Btn, Empty, Field, Icon, IconBtn, MobileBar, Modal, Page, Tag, inputCls } from '../components/ui.jsx'
import ManagerBox, { SearchInput } from '../components/ManagerBox.jsx'

const BLANK = { name: '', description: '', instructions: '' }

// 技能：一段可复用的做事方法（SKILL.md 格式），勾选给哪些智能体，就附加到它们的设定里
function SkillModal({ initial, onClose, onSaved, notify }) {
  const [f, setF] = useState(initial || BLANK)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const importFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const raw = await file.text()
    const m = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(raw.replace(/\r\n/g, '\n').trim())
    const meta = Object.fromEntries((m ? m[1] : '').split('\n').map((l) => l.split(/:(.*)/s).map((x) => (x || '').trim().replace(/^["']|["']$/g, ''))).filter((x) => x[0]))
    setF((s) => ({ ...s, name: meta.name || s.name || file.name.replace(/\.md$/i, ''), description: meta.description || s.description, instructions: (m ? m[2] : raw).trim() }))
  }
  const save = async () => {
    setBusy(true)
    try {
      await (f.id ? api('PUT', '/skills/' + f.id, f) : api('POST', '/skills', f))
      onSaved()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal wide title={f.id ? '编辑技能' : '新建技能'} sub="技能是一段可复用的做事方法。在智能体设置里勾选后，它会按这里写的方式工作。" onClose={onClose}
      footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn kind="primary" disabled={busy || !f.instructions.trim()} onClick={save}>{f.id ? '保存更改' : '添加技能'}</Btn></>}>
      <div className="flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" accept=".md,.markdown,.txt" className="hidden" onChange={importFile} />
        <Btn icon="file" onClick={() => fileRef.current?.click()}>从 SKILL.md 文件导入</Btn>
        <span className="text-xs text-faint">支持带 name / description 开头块的 SKILL.md，也可以直接粘贴到下面</span>
      </div>
      <Field label="名称"><input className={inputCls} value={f.name} onChange={set('name')} placeholder="写周报" /></Field>
      <Field label="一句话说明" hint="让你自己和智能体一眼看出它什么时候用。"><input className={inputCls} value={f.description} onChange={set('description')} placeholder="按公司模板整理一周工作" /></Field>
      <Field label="内容" hint="具体的步骤、格式要求、注意事项。勾选了这个技能的智能体每次发言都会带上它，越长越耗 token。">
        <textarea className={inputCls + ' font-mono text-sm leading-relaxed'} rows={12} value={f.instructions} onChange={set('instructions')} placeholder={'# 步骤\n1. …'} />
      </Field>
    </Modal>
  )
}

const originOf = (k) => k.origin || (k.source ? 'external' : 'custom')
const FILTERS = [['all', '全部'], ['external', '外部安装'], ['custom', '自己写的'], ['update', '可升级']]

export default function Skills({ data, notify, askManager, manager }) {
  const [list, setList] = useState(null)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [url, setUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [upgrading, setUpgrading] = useState('')
  const [modal, setModal] = useState(null)
  const load = useCallback(() => api('GET', '/skills').then((r) => setList(r.skills)).catch((e) => notify(e.message)), [notify])
  // 管家在后台装好技能后会推送刷新：技能数量一变就重新拉列表
  const skillCount = (data.skills || []).length
  useEffect(() => { load() }, [load, skillCount])
  // 打开页面时顺便检查外部技能有没有新版本（6 小时内不重复查）
  useEffect(() => { api('POST', '/skills/check-updates').then((r) => { if (r.updates) load() }).catch(() => {}) }, [load])

  const addUrl = async () => {
    setAdding(true)
    try {
      const sk = await api('POST', '/skills/from-url', { url: url.trim() })
      notify(`已添加技能「${sk.name}」`)
      setUrl('')
      load()
    } catch (e) {
      notify(e.message)
    } finally {
      setAdding(false)
    }
  }
  const upgrade = async (sk) => {
    setUpgrading(sk.id)
    try {
      await api('POST', `/skills/${sk.id}/upgrade`)
      notify(`「${sk.name}」已升级到最新版本`)
      load()
    } catch (e) {
      notify(e.message)
    } finally {
      setUpgrading('')
    }
  }
  const remove = async (sk) => {
    if (!await ask(`删除技能「${sk.name}」？用到它的智能体会不再带上它。`)) return
    await api('DELETE', '/skills/' + sk.id).catch((e) => notify(e.message))
    load()
  }
  const users = (id) => data.agents.filter((a) => (a.skills || []).includes(id)).map((a) => a.name)
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const counts = { all: (list || []).length, external: 0, custom: 0, update: 0 }
  for (const k of list || []) { counts[originOf(k)]++; if (k.update_available) counts.update++ }
  const shown = (list || [])
    .filter((k) => filter === 'all' || (filter === 'update' ? k.update_available : originOf(k) === filter))
    .filter((k) => words.every((w) => (k.name + ' ' + (k.description || '') + ' ' + k.instructions.slice(0, 300)).toLowerCase().includes(w)))

  return (
    <>
      <MobileBar title="技能"><IconBtn icon="plus" label="新建技能" size={40} onClick={() => setModal({})} /></MobileBar>
      <Page title="技能" lead="可复用的做事方法。在智能体设置里勾选，它就会按技能里写的方式工作。"
        action={<Btn icon="plus" onClick={() => setModal({})} className="hidden md:inline-flex">自己写一个</Btn>}>
        <ManagerBox askManager={askManager} manager={manager} onDone={load}
          placeholder="贴技能网址（SKILL.md、GitHub 技能目录），或说你想要什么技能"
          examples={['帮我找找有没有写周报的技能', '整理一下现有技能，看看哪些重复了']} />
        {counts.update > 0 && filter !== 'update' && (
          <button type="button" onClick={() => setFilter('update')} className="mb-4 flex w-full items-center gap-2.5 rounded-xl bg-accent-soft px-4 py-2.5 text-left text-[13px] text-accent-ink transition-colors duration-150 hover:brightness-95">
            <Icon name="upgrade" size={16} weight="fill" />有 {counts.update} 个外部技能发布了新版本<span className="ml-auto text-xs underline">查看</span>
          </button>
        )}
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="flex gap-0.5 rounded-xl bg-sunken p-1">
            {FILTERS.map(([id, name]) => (id !== 'update' || counts.update > 0) && (
              <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}
                className={'rounded-lg px-2.5 py-1 text-[13px] transition-colors duration-150 ' + (filter === id ? 'bg-surface font-medium text-ink shadow-xs' : 'text-muted hover:text-ink')}>
                {name}<span className="ml-1 font-mono text-[11px] text-faint">{counts[id]}</span>
              </button>
            ))}
          </div>
          <SearchInput value={q} onChange={setQ} placeholder="搜索名称和说明" />
        </div>
        {list == null ? <div className="skeleton h-3 w-40" /> : list.length === 0 ? (
          <Empty icon="sparkle" title="还没有技能" text="交给管家装一个，或者自己写一个。">
            <Btn kind="primary" icon="plus" onClick={() => setModal({})}>自己写一个</Btn>
          </Empty>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-raised">
            {shown.length === 0 && <li className="px-5 py-6 text-sm text-faint">没有符合条件的技能</li>}
            {shown.map((sk) => {
              const used = users(sk.id)
              const ext = originOf(sk) === 'external'
              return (
                <li key={sk.id} className="group flex items-start gap-4 px-5 py-4 transition-colors duration-150 hover:bg-sunken/40">
                  <span className={'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ' + (ext ? 'bg-accent-soft text-accent-ink' : 'bg-sunken text-muted')}>
                    <Icon name={ext ? 'link' : 'edit'} size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[15px] font-semibold text-ink">{sk.name}</span>
                      <Tag tone={ext ? 'accent' : 'neutral'}>{ext ? '外部安装' : '自己写的'}</Tag>
                      {sk.update_available && <Tag tone="ok"><Icon name="upgrade" size={11} weight="fill" />有新版本</Tag>}
                      {used.length > 0 && <span className="text-xs text-faint">· {used.join('、')} 在用</span>}
                    </div>
                    <p className="mt-1 line-clamp-2 text-[13px] text-muted">{sk.description || sk.instructions.slice(0, 80)}</p>
                    {sk.source && <a href={sk.source} target="_blank" rel="noreferrer" className="mt-1 block truncate font-mono text-[11px] text-faint hover:text-accent-ink">{sk.source}</a>}
                  </div>
                  {sk.update_available && <Btn kind="primary" icon="upgrade" disabled={upgrading === sk.id} onClick={() => upgrade(sk)} className="h-8 px-3 text-[13px]">{upgrading === sk.id ? '升级中…' : '升级'}</Btn>}
                  <IconBtn icon="edit" label="编辑" onClick={() => setModal(sk)} />
                  <IconBtn icon="trash" label="删除" kind="danger" onClick={() => remove(sk)} />
                </li>
              )
            })}
          </ul>
        )}
        <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (url.trim()) addUrl() }}>
          <input className={inputCls + ' h-10 min-w-0 flex-1 font-mono text-sm'} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="不想经过管家？在这里直接贴技能网址添加" />
          <Btn icon="link" disabled={adding || !url.trim()} type="submit" className="h-10">{adding ? '读取中…' : '添加'}</Btn>
        </form>
      </Page>
      {modal && <SkillModal initial={modal.id ? modal : null} notify={notify} onClose={() => setModal(null)} onSaved={() => { setModal(null); load() }} />}
    </>
  )
}

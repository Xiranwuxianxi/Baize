import { t } from '../lib/i18n'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { toAvatar } from '../lib/image'
import ExternalModal from './ExternalModal.jsx'
import Memories from './Memories.jsx'
import { Avatar, Btn, Chip, Field, GLYPHS, HUES, HUE_NAMES, Icon, IconBtn, Modal, ModelPicker, inputCls } from './ui.jsx'

export const TEMPLATES = [
  { name: '产品经理', avatar: 'ph:Target', color: 'persimmon', description: '梳理需求，定义范围与优先级', system_prompt: '你是一位资深产品经理。面对任何问题，先澄清目标用户与核心场景，再给出范围、优先级和验收标准。表达简洁，结论先行。' },
  { name: '架构师', avatar: 'ph:Code', color: 'slate', description: '给出技术方案与取舍', system_prompt: '你是一位经验丰富的软件架构师。针对需求给出可落地的技术方案，说明关键取舍、风险与替代方案，必要时给出示例代码。' },
  { name: '批判者', avatar: 'ph:Scales', color: 'rose', description: '专门挑毛病、找漏洞', system_prompt: '你的职责是批判性审视他人的观点与方案：指出漏洞、隐含假设和被忽略的风险，并提出改进建议。对事不对人，言之有据。' },
  { name: '总结者', avatar: 'ph:BookOpen', color: 'pine', description: '汇总各方观点，形成结论', system_prompt: '你负责在讨论后做总结：归纳各方共识与分歧，给出明确的结论和下一步行动清单。保持中立、条理清晰。' },
  { name: '总管', avatar: 'ph:Crown', color: 'teal', chief: true, description: '接待用户、拆解任务、调度专业智能体并汇总结论', system_prompt: '你是团队的总管，做事干练。接到需求先判断自己能否直接完成：能就直接回答；需要专业能力时，把工作拆成清晰的小任务交给合适的智能体，拿到结果后审阅、取舍，给用户一个明确的结论。' },
]

function Toggle({ on, set, title, text }) {
  return (
    <label className={'flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors duration-150 ' + (on ? 'border-accent bg-accent-soft' : 'border-line bg-raised hover:border-line-strong')}>
      <input type="checkbox" checked={on} onChange={(e) => set(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" />
      <span>
        <span className="block text-sm font-medium text-ink">{t(title)}</span>
        <span className="mt-1 block text-xs leading-relaxed text-muted [overflow-wrap:anywhere]">{typeof text === 'string' ? t(text) : text}</span>
      </span>
    </label>
  )
}


const BLANK = { think: false, memory: true, skills: [], mcps: [], external: false, ext_kind: '', chief: false, no_tools: false, auto_approve: false, name: '', avatar: '', avatar_image: '', color: 'teal', description: '', system_prompt: '', provider_id: '', model: '', temperature: '', max_tokens: '' }

// conv 有值且是新建时：建好直接加入该会话，可选择是否同时加入全局
export default function AgentModal({ data, initial, conv, reload, onClose, onSaved, notify }) {
  if (initial?.external) return <ExternalModal data={data} initial={initial} onClose={onClose} onSaved={onSaved} notify={notify} reload={reload} />
  return <ModelAgentModal data={data} initial={initial} conv={conv} reload={reload} onClose={onClose} onSaved={onSaved} notify={notify} />
}

function ModelAgentModal({ data, initial, conv, reload, onClose, onSaved, notify }) {
  const [f, setF] = useState(() => ({
    ...BLANK,
    provider_id: data.providers[0]?.id || '',
    ...initial,
    temperature: initial?.temperature ?? '',
    max_tokens: initial?.max_tokens ?? '',
  }))
  const [busy, setBusy] = useState('')
  const [toGlobal, setToGlobal] = useState(false)
  const fileRef = useRef(null)
  const onPick = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow picking the same file again
    if (!file) return
    try {
      const image = await toAvatar(file)
      setF((s) => ({ ...s, avatar_image: image }))
    } catch (err) {
      notify(err.message)
    }
  }
  const inConv = !!conv && !initial?.id
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const provider = data.providers.find((p) => p.id === f.provider_id)
  const local = data.env?.local || {}
  const [tab, setTab] = useState('basic')
  const [glyphs, setGlyphs] = useState(false)
  const [memCount, setMemCount] = useState(null)
  useEffect(() => {
    if (initial?.id) api('GET', `/agents/${initial.id}/memories`).then((r) => setMemCount(r.memories.length)).catch(() => {})
  }, [initial?.id])

  const save = async () => {
    if (!f.name.trim()) { setTab('basic'); return notify('先给智能体起个名字') }
    setBusy('save')
    try {
      if (f.id) await api('PUT', '/agents/' + f.id, f)
      else {
        const r = inConv ? await api('POST', `/conversations/${conv.id}/agents`, { ...f, global: toGlobal }) : await api('POST', '/agents', f)
        const saved = r.agent || r
        if (saved.external) { // 留在窗口里，让用户马上能复制连接指令
          setF({ ...saved, temperature: '', max_tokens: '' })
          await reload()
          notify('已创建。复制下面的连接指令，粘贴给它')
          return
        }
      }
      onSaved()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy('')
    }
  }
  const fetchModels = async (pid = f.provider_id, quiet = false) => {
    setBusy('models')
    try {
      const r = await api('POST', `/providers/${pid}/models`)
      await reload()
      if (!quiet) notify(`已拉取 ${r.models.length} 个模型`)
    } catch (e) {
      notify('拉取模型失败：' + e.message)
    } finally {
      setBusy('')
    }
  }
  // 换渠道：旧模型属于旧渠道，清掉；新渠道还没拉过模型就顺手拉一次，直接给出列表
  const changeProvider = (e) => {
    const pid = e.target.value
    const next = data.providers.find((p) => p.id === pid)
    setF((s) => ({ ...s, provider_id: pid, model: next?.default_model || '' }))
    if (next && !(next.models || []).length) fetchModels(pid, true)
  }

  const abilities = (f.skills || []).length + (f.mcps || []).length + (f.manager ? 1 : 0)
  const TABS = [['basic', '身份'], ['model', '模型'], ['abilities', '能力', abilities || null], ['memory', '记忆', f.memory === false ? '关' : memCount]]

  return (
    <Modal
      wide
      title={f.id ? '编辑智能体' : inConv ? '为这个会话新建智能体' : '新建智能体'}
      sub={inConv ? `创建后直接加入「${conv.title}」。` : '名字、性格和模型都由你决定。'}
      onClose={onClose}
      footer={<>
        {inConv && (
          <label className="mr-auto flex cursor-pointer items-center gap-2 text-[13px] text-ink" title="不勾选则只属于这个会话，会话删除时一并删除；之后也可以在会话设置里再加入全局。">
            <input type="checkbox" checked={toGlobal} onChange={(e) => setToGlobal(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
            同时加入全局
          </label>
        )}
        <Btn kind="ghost" onClick={onClose}>取消</Btn>
        <Btn kind="primary" disabled={!!busy} onClick={save}>{f.id ? '保存更改' : '创建智能体'}</Btn>
      </>}
    >
      {/* 分页：所有设置一眼可见，不用往下翻才发现还有东西 */}
      <div className="no-bar -mt-1 flex gap-1 overflow-x-auto rounded-xl bg-sunken p-1" role="tablist" aria-label="智能体设置">
        {TABS.map(([id, name, n]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
            className={'flex min-w-[64px] flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-[13px] transition-colors duration-150 ' + (tab === id ? 'bg-surface font-medium text-ink shadow-xs' : 'text-muted hover:text-ink')}>
            {t(name)}{n != null && n !== 0 && <span className="font-mono text-xs text-faint">{n}</span>}
          </button>
        ))}
      </div>

      {tab === 'basic' && (<>
        {!f.id && (
          <div>
            <div className="mb-2 text-[13px] font-medium text-ink">从模板开始，或者自己设定</div>
            <div className="flex flex-wrap gap-1.5">
              <Chip on={!TEMPLATES.some((t) => t.name === f.name)}
                onClick={() => setF((s) => ({ ...s, name: '', avatar: '', avatar_image: '', color: 'teal', description: '', system_prompt: '', chief: false }))}>
                <Icon name="edit" size={14} />自己设定
              </Chip>
              {TEMPLATES.map((t) => (
                <Chip key={t.name} on={f.name === t.name} onClick={() => setF((s) => ({ ...s, ...t }))} className="pl-1">
                  <Avatar agent={t} size={22} />{t.name}
                </Chip>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-start gap-4">
          <div className="flex shrink-0 flex-col items-center gap-1.5">
            <Avatar agent={f} size={64} />
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={onPick} />
            <button type="button" onClick={() => fileRef.current?.click()} className="rounded-md px-2 py-0.5 text-xs text-muted hover:bg-sunken hover:text-ink">{f.avatar_image ? '换图片' : '上传图片'}</button>
          </div>
          <div className="min-w-0 flex-1 space-y-3">
            <Field label="名称"><input className={inputCls} value={f.name} onChange={set('name')} placeholder="小橙" maxLength={40} /></Field>
            <div className="flex flex-wrap items-center gap-2">
              {Object.keys(HUES).map((k) => (
                <button key={k} type="button" aria-label={HUE_NAMES[k]} title={HUE_NAMES[k]} aria-pressed={!f.avatar_image && f.color === k} onClick={() => setF((s) => ({ ...s, color: k, avatar_image: '' }))}
                  className={'av h-6 w-6 rounded-full transition-transform duration-150 hover:scale-110 active:scale-95 ' + (!f.avatar_image && f.color === k ? 'outline-2 outline-offset-2 outline-ink' : '')} style={{ '--h': HUES[k] }} />
              ))}
              <button type="button" onClick={() => setGlyphs((v) => !v)} aria-expanded={glyphs}
                className="ml-1 flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted hover:bg-sunken hover:text-ink">
                换图标<Icon name="chevron" size={12} className={'transition-transform duration-200 ' + (glyphs ? 'rotate-180' : '')} />
              </button>
              {f.avatar_image && <button type="button" onClick={() => setF((s) => ({ ...s, avatar_image: '' }))} className="rounded-md px-2 py-1 text-xs text-muted hover:bg-sunken hover:text-ink">移除图片</button>}
            </div>
            {glyphs && (
              <div className="flex flex-wrap gap-1 rounded-xl bg-sunken p-1.5">
                <button type="button" aria-pressed={!f.avatar_image && !f.avatar} onClick={() => setF((s) => ({ ...s, avatar: '', avatar_image: '' }))}
                  className={'h-8 rounded-[9px] px-2.5 text-xs font-medium transition-colors duration-150 ' + (!f.avatar_image && !f.avatar ? 'bg-ink text-surface' : 'text-muted hover:bg-surface')}>首字</button>
                {Object.entries(GLYPHS).map(([k, G]) => {
                  const on = !f.avatar_image && f.avatar === 'ph:' + k
                  return (
                    <button key={k} type="button" aria-label={k} aria-pressed={on} onClick={() => setF((s) => ({ ...s, avatar: 'ph:' + k, avatar_image: '' }))}
                      className={'flex h-8 w-8 items-center justify-center rounded-[9px] transition-colors duration-150 ' + (on ? 'bg-ink text-surface' : 'text-muted hover:bg-surface hover:text-ink')}>
                      <G size={17} weight={on ? 'fill' : 'regular'} />
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <Field label="一句话简介" hint="领头人靠这句话判断该把什么任务派给它。">
          <input className={inputCls} value={f.description} onChange={set('description')} placeholder="它负责什么？" maxLength={200} />
        </Field>
        <Field label="角色设定" hint="它的身份、语气、专长和做事边界（系统提示词）。">
          <textarea className={inputCls + ' leading-relaxed'} rows={5} value={f.system_prompt} onChange={set('system_prompt')} placeholder="你是一位……" />
        </Field>
        {!inConv && !f.conv_id && (
          <Toggle on={!!f.chief} set={(v) => setF((s) => ({ ...s, chief: v }))} title="设为总智能体"
            text="每个新会话默认由它接待，它可以按需把其他智能体拉进会话一起做事。同一时间只能有一个。" />
        )}
      </>)}

      {tab === 'model' && (<>
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="模型渠道" hint={data.providers.length ? undefined : '还没有渠道，先到「渠道」页添加一个。'}>
            <select className={inputCls} value={f.provider_id} onChange={changeProvider}>
              <option value="">未选择</option>
              {data.providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          <Field label="模型" hint={provider?.default_model ? '留空则使用渠道默认：' + provider.default_model : undefined}>
            <div className="flex gap-2">
              <div className="min-w-0 flex-1">
                <ModelPicker key={f.provider_id} value={f.model} onChange={(v) => setF((s) => ({ ...s, model: v }))} models={provider?.models || []}
                  emptyLabel={provider?.default_model ? `使用渠道默认（${provider.default_model}）` : '请选择模型'} placeholder={busy === 'models' ? '正在拉取模型列表…' : '点右侧按钮拉取，或手动输入模型 ID'} />
              </div>
              <IconBtn icon="refresh" label={provider ? '从渠道拉取模型列表' : '先选择模型渠道'} kind="outline" size={42} disabled={!provider || !!busy} onClick={() => fetchModels()} className="shrink-0" />
            </div>
          </Field>
        </div>
        <Toggle on={!!f.think} set={(v) => setF((s) => ({ ...s, think: v }))} title="深度思考"
          text="先推理再回答，复杂问题更准，但慢很多。默认关闭。只对支持思考开关的模型有效（有的模型总在思考，比如 GLM-5.3）。" />
        <details className="group rounded-xl border border-line bg-raised" open={!!(f.temperature || f.max_tokens)}>
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-[13px] text-muted select-none hover:text-ink">
            高级：温度、最大输出<Icon name="chevron" size={14} className="transition-transform duration-200 group-open:rotate-180" />
          </summary>
          <div className="grid gap-5 border-t border-line px-4 py-4 md:grid-cols-2">
            <Field label="温度" hint="0–2，留空用模型默认值。">
              <input className={inputCls} type="number" min="0" max="2" step="0.1" value={f.temperature} onChange={set('temperature')} placeholder="默认" />
            </Field>
            <Field label="最大输出 Token" hint="建议留空。想限制长度再填：群聊 8192–32768 足够；开了思考别低于 8192。填超了会自动压到模型上限。">
              <input className={inputCls} type="number" min="1" step="1" value={f.max_tokens} onChange={set('max_tokens')} placeholder="自动（推荐）" />
            </Field>
          </div>
        </details>
      </>)}

      {tab === 'abilities' && (<>
        {[['skills', '技能', data.skills || [], '「技能」'], ['mcps', 'MCP 工具', data.mcp || [], '「MCP」']].map(([key, label, items, page]) => (
          <div key={key}>
            <div className="mb-2 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="font-medium text-ink">{label}</span>
              <span className="text-right text-xs text-faint">{items.length ? '点一下就能给它用上' : `还没有，到${page}页添加`}</span>
            </div>
            {items.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {items.map((it) => {
                  const on = (f[key] || []).includes(it.id)
                  return (
                    <Chip key={it.id} on={on} title={it.description || ''} onClick={() => setF((s) => ({ ...s, [key]: on ? s[key].filter((x) => x !== it.id) : [...(s[key] || []), it.id] }))}>
                      {on && <Icon name="check" size={13} weight="bold" />}{it.name}{key === 'mcps' && <span className="text-xs text-faint">{it.error ? '连接失败' : `${it.tools} 个工具`}</span>}
                    </Chip>
                  )
                })}
              </div>
            )}
          </div>
        ))}
        <Toggle on={!!f.manager} set={(v) => setF((s) => ({ ...s, manager: v }))} title="管理技能和 MCP"
          text="它可以读你给的网址、搜索、添加或删除技能和 MCP。添加和删除前都会先请你确认。" />
        <Toggle
          on={!f.no_tools} set={(v) => setF((s) => ({ ...s, no_tools: !v, auto_approve: v ? s.auto_approve : false }))}
          title="可以请求本地操作"
          text={local.usable
            ? `它可以请求执行命令、读写文件（${local.in_docker ? 'Docker 容器内' : '这台电脑'}），每一步都会先问你。关掉后它永远不会提出操作请求。`
            : '本地操作的总开关还没开（在「设置」里）。这里决定开启之后它能不能提出请求。'}
        />
        {!f.no_tools && (
          <Toggle on={!!f.auto_approve} set={(v) => setF((s) => ({ ...s, auto_approve: v }))} title="永久允许，不再询问"
            text="它的本地操作直接执行，不再弹出审批卡片。只对你完全信任的智能体打开，随时可以撤销。" />
        )}
      </>)}

      {tab === 'memory' && (<>
        <Toggle on={f.memory !== false} set={(v) => setF((s) => ({ ...s, memory: v }))} title="记忆"
          text="它会记住以后的会话还用得上的东西：你的偏好和背景、项目的关键事实、定下的决定、摸索出的有效做法。只属于它自己，跨会话保留；只在相关时才带上，不怎么增加用量。" />
        {f.memory !== false && f.id && <Memories agentId={f.id} notify={notify} onCount={setMemCount} />}
        {f.memory !== false && !f.id && <p className="rounded-xl border border-dashed border-line-strong px-4 py-4 text-[13px] text-faint">创建后，它记下的东西会出现在这里，可以查看和修改。</p>}
      </>)}

      {f.managed && <p className="rounded-lg bg-sunken px-3 py-2 text-xs leading-relaxed text-muted">这个智能体由配置文件声明。在这里的修改会在下次启动时被 config.yaml 覆盖。</p>}
    </Modal>
  )
}

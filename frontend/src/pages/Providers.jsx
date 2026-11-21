import { ask } from '../components/Dialog.jsx'
import { useState } from 'react'
import { motion } from 'motion/react'
import { api } from '../lib/api'
import { Btn, Chip, Empty, Field, Icon, IconBtn, MobileBar, Modal, ModelPicker, Page, Tag, inputCls, rise } from '../components/ui.jsx'

const BLANK = { name: '', protocol: 'openai', base_url: '', default_model: '', api_key: '', headers: '' }
const SHORT = { openai: 'OpenAI 兼容', openai_responses: 'Responses', anthropic: 'Anthropic', gemini: 'Gemini', ollama: 'Ollama' }
const isLocal = (url) => /^https?:\/\/(localhost|127\.|0\.0\.0\.0|192\.168\.|10\.|\[::1\])/i.test(url || '')

function ProviderModal({ data, initial, onClose, onSaved, notify }) {
  const editing = !!initial?.id
  const [f, setF] = useState(() =>
    initial
      ? { ...BLANK, ...initial, api_key: '', headers: Object.keys(initial.extra_headers || {}).length ? JSON.stringify(initial.extra_headers, null, 2) : '' }
      : BLANK
  )
  const [busy, setBusy] = useState(false)
  const [models, setModels] = useState(initial?.models || [])
  const [pulling, setPulling] = useState(false)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const proto = data.protocols.find((p) => p.id === f.protocol)
  // 不用先保存：直接用表单里填的地址和密钥去拉取
  const pull = async () => {
    setPulling(true)
    try {
      const body = { id: initial?.id, name: f.name, protocol: f.protocol, base_url: f.base_url }
      if (!editing || f.api_key) body.api_key = f.api_key
      const r = await api('POST', '/providers/preview-models', body)
      setModels(r.models)
      if (!r.models.length) notify('连接成功，但这个地址没有返回任何模型')
      else if (!f.default_model) setF((s) => ({ ...s, default_model: r.models[0] }))
    } catch (e) {
      notify('拉取失败：' + e.message)
    } finally {
      setPulling(false)
    }
  }

  const save = async () => {
    let extra = {}
    if (f.headers.trim()) {
      try {
        extra = JSON.parse(f.headers)
        if (!extra || typeof extra !== 'object' || Array.isArray(extra)) throw new Error()
      } catch {
        return notify('自定义请求头需要是 JSON 对象，例如 {"X-Title": "demo"}')
      }
    }
    const body = { name: f.name, protocol: f.protocol, base_url: f.base_url, default_model: f.default_model, extra_headers: extra, num_ctx: f.num_ctx ?? '' }
    if (!editing || f.api_key) body.api_key = f.api_key // 编辑时留空 = 不改动已保存的密钥
    setBusy(true)
    try {
      const saved = await (editing ? api('PUT', '/providers/' + initial.id, body) : api('POST', '/providers', body))
      // 把刚才拉取到的模型列表记到渠道上，新建智能体时就能直接选
      if (models.length) await api('POST', `/providers/${saved.id}/models`).catch(() => {})
      onSaved()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      wide
      title={editing ? '编辑渠道' : '添加模型渠道'}
      sub="渠道是模型的来源：一个云端服务，或一台本地推理服务。"
      onClose={onClose}
      footer={<><Btn kind="ghost" onClick={onClose}>取消</Btn><Btn kind="primary" disabled={busy} onClick={save}>{editing ? '保存更改' : '添加渠道'}</Btn></>}
    >
      {!editing && (
        <div>
          <div className="mb-2 text-[13px] font-medium text-ink">从预设开始</div>
          <div className="flex flex-wrap gap-1.5">
            {data.presets.map((p) => (
              <Chip key={p.name} on={f.name === p.name} onClick={() => setF((s) => ({ ...s, name: p.name, protocol: p.protocol, base_url: p.base_url }))}>
                {p.local && <span className="h-1.5 w-1.5 rounded-full bg-ok" />}{p.name}
              </Chip>
            ))}
          </div>
          <p className="mt-2.5 flex items-center gap-1.5 text-xs text-faint"><span className="h-1.5 w-1.5 rounded-full bg-ok" />绿点为本机运行的模型服务</p>
        </div>
      )}
      <div className="grid gap-5 md:grid-cols-2">
        <Field label="渠道名称"><input className={inputCls} value={f.name} onChange={set('name')} placeholder="我的本地 Ollama" /></Field>
        <Field label="连接协议" hint={proto?.hint}>
          <select className={inputCls} value={f.protocol} onChange={set('protocol')}>
            {data.protocols.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
      </div>
      <Field label="接口地址" hint="本地模型填本机地址，例如 http://localhost:11434。留空则使用该协议的官方地址。">
        <input className={inputCls + ' font-mono text-sm'} value={f.base_url} onChange={set('base_url')} placeholder="https://" inputMode="url" autoCapitalize="off" spellCheck={false} />
      </Field>
      <Field
        label="API Key"
        hint={(editing && initial.key_set ? `已保存（${initial.key_hint}），留空表示不修改。` : '本地模型通常不需要。') + '密钥只存在本机后端，不会回传浏览器；也可填 env:变量名 从环境变量读取。'}
      >
        <input className={inputCls + ' font-mono text-sm'} type="password" value={f.api_key} onChange={set('api_key')} placeholder={editing && initial.key_set ? '••••••••' : 'sk-…  或  env:OPENAI_API_KEY'} autoComplete="off" />
      </Field>
      <Field
        label="默认模型"
        hint={models.length ? `已拉取 ${models.length} 个模型，直接在上面选。智能体没有单独指定模型时使用它。` : '填好地址和密钥后点「拉取模型」，就可以直接从列表里选，不用手动输入。'}
      >
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <ModelPicker value={f.default_model} onChange={(v) => setF((s) => ({ ...s, default_model: v }))} models={models} emptyLabel="请选择默认模型" placeholder="先拉取模型，或手动输入模型 ID" />
          </div>
          <Btn icon="refresh" disabled={pulling} onClick={pull} className="h-[42px] shrink-0">{pulling ? '正在拉取…' : models.length ? '重新拉取' : '拉取模型'}</Btn>
        </div>
      </Field>
      {f.protocol === 'ollama' && (
        <Field label="上下文长度" hint={`Ollama 加载模型时的上下文窗口，单位是 token。留空用默认的 ${data.env?.ollama_ctx || 8192}。Ollama 自己的默认值只有 4096，多智能体对话很容易把它占满，导致模型只思考、写不出正文。调大更稳，但更占内存；改动后模型会重新加载一次。`}>
          <input className={inputCls + ' font-mono text-sm'} type="number" min="2048" step="1024" value={f.num_ctx ?? ''} onChange={set('num_ctx')} placeholder={String(data.env?.ollama_ctx || 8192)} />
        </Field>
      )}
      <Field label="自定义请求头（可选）" hint="JSON 对象，用于自建网关或代理的额外鉴权头。">
        <textarea className={inputCls + ' font-mono text-sm'} rows={2} value={f.headers} onChange={set('headers')} placeholder='{"X-Title": "my-app"}' spellCheck={false} />
      </Field>
    </Modal>
  )
}

function ProviderCard({ p, i, data, reload, notify, onEdit }) {
  const [busy, setBusy] = useState('')
  const [showModels, setShowModels] = useState(false)
  const [mq, setMq] = useState('')
  const setDefault = async (m) => {
    try {
      await api('PUT', '/providers/' + p.id, { name: p.name, protocol: p.protocol, base_url: p.base_url, default_model: m, extra_headers: p.extra_headers, num_ctx: p.num_ctx ?? '' })
      notify('默认模型已改为 ' + m)
      reload()
    } catch (e) {
      notify(e.message)
    }
  }
  const [result, setResult] = useState(null)
  const used = data.agents.filter((a) => a.provider_id === p.id).length

  const run = async (kind) => {
    setBusy(kind)
    setResult(null)
    try {
      if (kind === 'models') {
        const r = await api('POST', `/providers/${p.id}/models`)
        setResult({ ok: true, text: `已拉取 ${r.models.length} 个模型` })
        reload()
      } else {
        const r = await api('POST', `/providers/${p.id}/test`, {})
        setResult({ ok: true, text: `连接正常 · ${r.model} · ${r.ms} ms`, reply: r.reply })
      }
    } catch (e) {
      setResult({ ok: false, text: e.message })
    } finally {
      setBusy('')
    }
  }
  const remove = async () => {
    if (!await ask(`删除渠道「${p.name}」？${used ? `有 ${used} 个智能体正在使用它，删除后它们将无法发言。` : ''}`)) return
    await api('DELETE', '/providers/' + p.id).catch((e) => notify(e.message))
    reload()
  }

  const rows = [
    ['地址', p.base_url || '官方默认地址', true],
    ['密钥', p.key_set ? p.key_hint || '已设置' : '未设置'],
    ['默认模型', p.default_model || '未设置', !!p.default_model],
    ['可选模型', p.models?.length ? `${p.models.length} 个` : '尚未拉取'],
    ...(p.protocol === 'ollama' ? [['上下文长度', `${p.num_ctx || data.env?.ollama_ctx || 8192} token${p.num_ctx ? '' : '（默认）'}`]] : []),
    ['使用中', used ? `${used} 个智能体` : '暂无'],
  ]
  return (
    <motion.div {...rise(i)} className="flex flex-col rounded-[20px] border border-line bg-raised p-5 shadow-card md:p-6">
      <div className="flex items-start gap-3.5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] bg-sunken text-ink"><Icon name="plug" size={22} weight="duotone" /></span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[17px] font-semibold tracking-tight text-ink">{p.name}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Tag tone="accent">{SHORT[p.protocol] || p.protocol}</Tag>
            {p.managed && <Tag>配置文件</Tag>}
            {isLocal(p.base_url) && <Tag tone="ok"><span className="h-1.5 w-1.5 rounded-full bg-ok" />本机</Tag>}
          </div>
        </div>
        <div className="-mt-1 -mr-2 flex">
          <IconBtn icon="edit" label="编辑渠道" onClick={onEdit} />
          <IconBtn icon="trash" label="删除渠道" kind="danger" onClick={remove} />
        </div>
      </div>
      <dl className="mt-5 divide-y divide-line border-y border-line text-[13px]">
        {rows.map(([k, v, mono]) => (
          <div key={k} className="flex items-center justify-between gap-4 py-2.5">
            <dt className="shrink-0 text-faint">{k}</dt>
            {k === '可选模型' && p.models?.length ? (
              <dd><button type="button" aria-expanded={showModels} onClick={() => setShowModels(!showModels)} className="inline-flex items-center gap-1 font-medium text-accent-ink hover:underline">
                {v}<Icon name="up" size={13} weight="bold" className={'transition-transform duration-200 ' + (showModels ? '' : 'rotate-180')} />
              </button></dd>
            ) : (
              <dd className={'min-w-0 truncate text-right text-ink ' + (mono ? 'font-mono text-xs' : '')}>{v}</dd>
            )}
          </div>
        ))}
      </dl>
      {showModels && (
        <div className="mt-3">
          {p.models.length > 8 && (
            <input className={inputCls + ' mb-2 h-9 text-sm'} value={mq} onChange={(e) => setMq(e.target.value)} placeholder={`在 ${p.models.length} 个模型里搜索`} />
          )}
          <ul className="scroll max-h-64 divide-y divide-line overflow-y-auto rounded-xl border border-line">
            {p.models.filter((m) => m.toLowerCase().includes(mq.trim().toLowerCase())).map((m) => (
              <li key={m} className="group/m flex items-center gap-2 px-3 py-1.5 text-xs">
                <span className="min-w-0 flex-1 truncate font-mono text-ink" title={m}>{m}</span>
                {m === p.default_model ? <Tag tone="accent">默认</Tag> : (
                  <button type="button" onClick={() => setDefault(m)} className="shrink-0 rounded px-1.5 py-0.5 text-muted opacity-0 transition-opacity group-hover/m:opacity-100 hover:bg-sunken hover:text-ink focus-visible:opacity-100">设为默认</button>
                )}
                <button type="button" title="复制模型 ID" onClick={() => navigator.clipboard?.writeText(m).then(() => notify('已复制 ' + m))} className="shrink-0 text-faint hover:text-ink"><Icon name="copy" size={13} /></button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {result && (
        <motion.div role="status" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={'mt-4 rounded-xl px-3.5 py-3 text-xs leading-relaxed [overflow-wrap:anywhere] ' + (result.ok ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger')}>
          <div className="flex items-start gap-2 font-medium"><Icon name={result.ok ? 'check' : 'warn'} size={15} weight="bold" className="mt-px" /><span className="min-w-0">{result.text}</span></div>
          {result.reply && <div className="mt-1 line-clamp-2 pl-[23px] opacity-80">模型回复：{result.reply}</div>}
        </motion.div>
      )}
      <div className="mt-5 flex gap-2">
        <Btn icon="bolt" disabled={!!busy} onClick={() => run('test')} className="flex-1">{busy === 'test' ? '正在请求模型…' : '测试连接'}</Btn>
        <Btn icon="refresh" disabled={!!busy} onClick={() => run('models')} className="flex-1">{busy === 'models' ? '正在拉取…' : '拉取模型'}</Btn>
      </div>
    </motion.div>
  )
}

export default function Providers({ data, reload, notify }) {
  const [modal, setModal] = useState(null) // null | {} | provider
  return (
    <>
      <MobileBar title="模型渠道">
        <IconBtn icon="plus" label="添加渠道" size={40} onClick={() => setModal({})} />
      </MobileBar>
      <Page
        eyebrow={`CHANNELS · ${String(data.providers.length).padStart(2, '0')}`}
        title="模型渠道"
        lead="接入云端服务或本机模型。支持 OpenAI 兼容、Responses、Anthropic、Gemini、Ollama 五种连接协议。"
        action={data.providers.length > 0 && <Btn kind="primary" icon="plus" onClick={() => setModal({})} className="hidden md:inline-flex">添加渠道</Btn>}
      >
        {data.providers.length === 0 ? (
          <Empty icon="plug" title="还没有模型渠道" text="智能体需要通过渠道调用模型。可以接入云端服务，也可以接入本机的 Ollama、LM Studio。">
            <Btn kind="primary" icon="plus" onClick={() => setModal({})}>添加第一个渠道</Btn>
          </Empty>
        ) : (
          <div className="grid gap-5 lg:grid-cols-2">
            {data.providers.map((p, i) => (
              <ProviderCard key={p.id} p={p} i={i} data={data} reload={reload} notify={notify} onEdit={() => setModal(p)} />
            ))}
          </div>
        )}
      </Page>
      {modal && (
        <ProviderModal
          data={data}
          initial={modal.id ? modal : null}
          notify={notify}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); reload() }}
        />
      )}
    </>
  )
}

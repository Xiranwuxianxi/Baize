import { t, LANGS, getLang, setLang } from '../lib/i18n'
import { ask } from '../components/Dialog.jsx'
import { useCallback, useEffect, useState } from 'react'
import { api, setToken } from '../lib/api'
import { Avatar, Btn, Icon, MobileBar, Page, Tag, inputCls } from '../components/ui.jsx'
import Records from '../components/Records.jsx'
import Lessons from '../components/Lessons.jsx'
import Usage from '../components/Usage.jsx'
import Blocked from '../components/Blocked.jsx'
import Backup from '../components/Backup.jsx'

const TABS = [['usage', '用量'], ['network', '访问与网络'], ['local', '本地操作与文件'], ['team', '智能体协作'], ['lessons', '经验与记忆'], ['data', '数据与记录']]

const size = (n) => (n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB')
const when = (ts) => {
  const d = new Date(ts * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function Section({ title, text, children }) {
  return (
    <section className="grid gap-4 border-b border-line py-7 last:border-0 md:grid-cols-[200px_minmax(0,1fr)] md:gap-10">
      <div>
        <h2 className="text-[15px] font-semibold text-ink">{t(title)}</h2>
        {text && <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{t(text)}</p>}
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </section>
  )
}

function Switch({ on, disabled, onChange, label }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className={'relative h-7 w-12 shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50 ' + (on ? 'bg-accent' : 'bg-line-strong')}>
      <span className={'absolute top-0.5 left-0.5 h-6 w-6 rounded-full bg-white shadow-xs transition-transform duration-200 ease-out-expo ' + (on ? 'translate-x-5' : '')} />
    </button>
  )
}

function Row({ title, text, children }) {
  return (
    <div className="flex items-start gap-4 rounded-xl border border-line bg-raised p-4">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-ink">{typeof title === 'string' ? t(title) : title}</div>
        {text && <div className="mt-1 text-[13px] leading-relaxed text-muted [overflow-wrap:anywhere]">{text}</div>}
      </div>
      {children}
    </div>
  )
}

export default function Settings({ data, reload, notify, openConv }) {
  const [s, setS] = useState(null)
  const [busy, setBusy] = useState(false)
  const [path, setPath] = useState('')
  const [pw, setPw] = useState('')
  const [adv, setAdv] = useState({ timeout: '', max_steps: '' })
  const [tab, setTab] = useState(() => localStorage.getItem('mac_settings_tab') || 'network')
  useEffect(() => { localStorage.setItem('mac_settings_tab', tab) }, [tab])

  const take = useCallback((view) => {
    setS(view)
    setPath(view.local.workspace)
    setAdv({ timeout: view.local.timeout, max_steps: view.local.max_steps })
  }, [])
  const load = useCallback(() => api('GET', '/settings').then(take).catch((e) => notify(e.message)), [take, notify])
  useEffect(() => { load() }, [load, data.agents])

  if (!s) return <><MobileBar title="设置" /><div className="p-8"><div className="skeleton h-3 w-48" /></div></>

  const local = s.local
  const locked = !s.can_admin
  const save = async (patch, done) => {
    setBusy(true)
    try {
      take(await api('PUT', '/settings', patch))
      if (done) notify(done)
      reload()
      return true
    } catch (e) {
      notify(e.message)
      return false
    } finally {
      setBusy(false)
    }
  }
  const setLocal = (patch, done) => save({ local: patch }, done)
  const savePassword = async () => {
    const next = pw.trim()
    if (!next) return notify('先输入要设置的口令')
    setBusy(true)
    try {
      const view = await api('PUT', '/settings', { token: next })
      setToken(next) // 本机立刻改用新口令，不会被自己挡在外面
      take(view)
      setPw('')
      notify('访问口令已设置。其他设备打开时需要输入它')
      reload()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  const clearPassword = async () => {
    if (!await ask(s.lan_open && local.enabled ? '清除访问口令？清除后，本地操作只对这台电脑上的浏览器开放，其他设备只能查看。' : '清除访问口令？')) return
    setBusy(true)
    try {
      const view = await api('PUT', '/settings', { token: '' })
      setToken('')
      take(view)
      notify('访问口令已清除')
      reload()
    } catch (e) {
      notify(e.message)
    } finally {
      setBusy(false)
    }
  }
  const revoke = async (a) => {
    try { take(await api('POST', `/agents/${a.id}/revoke`)); reload(); notify(`已撤销对${a.name}的永久授权`) } catch (e) { notify(e.message) }
  }
  const openFolder = () => api('POST', '/settings/open-workspace').catch((e) => notify(e.message))
  const copy = (text) => navigator.clipboard?.writeText(text).then(() => notify('已复制路径'))
  const blocked = local.enabled && !local.usable

  return (
    <>
      <MobileBar title="设置" />
      <Page title="设置" lead="改动立即生效，不需要重启。" action={
        <label className="flex items-center gap-2 whitespace-nowrap text-[13px] text-muted">
          {t('界面语言')}
          <select className={inputCls + ' h-9 w-auto py-1 text-[13px]'} value={getLang()} onChange={(e) => setLang(e.target.value)} aria-label={t('界面语言')}>
            {LANGS.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
      }>
        {locked && (
          <div role="alert" className="mb-6 flex items-start gap-3 rounded-xl border border-line bg-raised p-4 text-[13px] leading-relaxed text-muted">
            <Icon name="shield" size={18} className="mt-0.5 text-accent-ink" />
            <span>这台设备现在只能查看，不能修改。为了安全，权限类设置只能在运行本程序的那台电脑上修改；在那台电脑上设置访问口令之后，输入过口令的设备也可以修改。</span>
          </div>
        )}

        <nav className="mb-2 flex gap-1 overflow-x-auto no-bar border-b border-line" aria-label="设置分类">
          {TABS.map(([id, name]) => (
            <button key={id} type="button" aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}
              className={'relative shrink-0 px-3.5 pb-3 pt-1 text-sm transition-colors duration-150 ' + (tab === id ? 'font-medium text-ink' : 'text-muted hover:text-ink')}>
              {t(name)}
              {tab === id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
            </button>
          ))}
        </nav>

        {tab === 'local' && (
        <Section title="本地操作" text="让智能体在征得你同意后执行命令、读写文件。">
          <Row
            title="允许智能体请求本地操作"
            text={
              !local.enabled ? '关闭时，智能体不知道自己可以操作这台电脑，也不会提出请求。'
              : blocked ? '已打开，但暂时不会生效，原因见下方。'
              : local.in_docker ? '已开启。程序运行在 Docker 容器里，智能体只能操作容器内的环境和挂载的工作区，管不了宿主机。'
              : `已开启。智能体可以请求操作这台电脑（${local.system}）。`
            }
          >
            <Switch on={local.enabled} disabled={locked || busy} label="允许智能体请求本地操作" onChange={(v) => setLocal({ enabled: v }, v ? '已开启本地操作' : '已关闭本地操作')} />
          </Row>
          {blocked && (
            <div role="alert" className="rounded-xl bg-danger-soft p-4 text-[13px] leading-relaxed text-danger">
              <b className="font-medium">还差一步才能生效。</b> {local.reason}
            </div>
          )}
          {local.remote_locked && (
            <div role="status" className="flex items-start gap-3 rounded-xl border border-line bg-raised p-4 text-[13px] leading-relaxed text-muted">
              <Icon name="shield" size={18} className="mt-0.5 shrink-0 text-accent-ink" />
              <span>还没有设置访问口令，所以目前<b className="font-medium text-ink">只有这台电脑上的浏览器</b>可以发消息和审批操作，手机等其他设备暂时只能查看。想在其他设备上也能用，在下面设置一个访问口令即可。</span>
            </div>
          )}
          <div>
            <div className="mb-2 text-[13px] font-medium text-ink">没有预先授权时</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {[['ask', '每次都问我', '每个操作弹出卡片，由你选择不允许、允许一次、允许五次或永久允许。'], ['auto', '全部自动允许', '不再询问，直接执行。只在你完全信任当前任务时使用。']].map(([id, name, hint]) => (
                <button key={id} type="button" aria-pressed={local.approval === id} disabled={locked || busy} onClick={() => setLocal({ approval: id })}
                  className={'rounded-xl border p-3.5 text-left transition-colors duration-150 disabled:opacity-60 ' + (local.approval === id ? 'border-accent bg-accent-soft' : 'border-line bg-raised hover:border-line-strong')}>
                  <span className="block text-sm font-medium text-ink">{name}</span>
                  <span className="mt-1 block text-xs leading-relaxed text-muted">{hint}</span>
                </button>
              ))}
            </div>
          </div>
        </Section>
        )}

        {tab === 'local' && (
        <Section title="工作区" text="所有会话里智能体创建、读取的文件都放在这个文件夹，命令也在这里执行。">
          <div>
            <label className="mb-2 block text-[13px] font-medium text-ink" htmlFor="ws-path">文件夹位置</label>
            <div className="flex flex-wrap gap-2">
              <input id="ws-path" className={inputCls + ' min-w-0 flex-1 font-mono text-sm'} value={path} disabled={locked} onChange={(e) => setPath(e.target.value)} spellCheck={false} />
              <Btn kind="primary" disabled={locked || busy || path.trim() === local.workspace} onClick={() => setLocal({ workspace: path }, '工作区已更改，之后的文件会放到新位置')}>保存位置</Btn>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-faint">
              <span>填完整路径；文件夹不存在会自动创建。已有的文件不会被搬过去。</span>
              <button type="button" onClick={() => copy(local.workspace)} className="inline-flex items-center gap-1 text-accent-ink hover:underline"><Icon name="copy" size={13} />复制路径</button>
              {!local.in_docker && s.is_local && <button type="button" onClick={openFolder} className="inline-flex items-center gap-1 text-accent-ink hover:underline"><Icon name="folder" size={13} />在文件管理器中打开</button>}
            </div>
          </div>
          <div>
            <div className="mb-2 flex items-baseline justify-between text-[13px]">
              <span className="font-medium text-ink">用什么执行命令</span>
              <span className="text-xs text-faint">当前：{local.shell_name}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {[['auto', '自动（有 bash 就用 bash）'], ['bash', 'bash'], ...(local.system === 'Windows' ? [['powershell', 'PowerShell'], ['cmd', 'cmd']] : [])].map(([id, name]) => (
                <button key={id} type="button" aria-pressed={local.shell === id} disabled={locked || busy} onClick={() => setLocal({ shell: id })}
                  className={'rounded-full border px-3 py-1.5 text-[13px] transition-colors duration-150 disabled:opacity-60 ' + (local.shell === id ? 'border-accent bg-accent-soft font-medium text-accent-ink' : 'border-line bg-raised text-muted hover:border-line-strong')}>{name}</button>
              ))}
            </div>
            {local.system === 'Windows' && !local.bash_found && <p className="mt-2 text-xs leading-relaxed text-faint">没有找到 Git Bash，`curl … | bash` 这类命令需要它。装上 Git for Windows 后会自动使用。</p>}
          </div>
          <Row title="允许读写工作区之外的文件" text="关闭时，智能体读写文件的路径不能跳出工作区。注意：这只约束读写文件，一条被你允许的命令仍然可以访问电脑上的其他位置。">
            <Switch on={local.allow_outside_workspace} disabled={locked || busy} label="允许读写工作区之外的文件" onChange={(v) => setLocal({ allow_outside_workspace: v })} />
          </Row>
          <div>
            <div className="mb-2 flex items-baseline justify-between text-[13px]">
              <span className="font-medium text-ink">工作区里的文件</span>
              <button type="button" onClick={load} className="text-xs text-muted hover:text-ink">刷新</button>
            </div>
            {s.files.length === 0 ? (
              <p className="rounded-xl border border-dashed border-line-strong px-4 py-5 text-[13px] text-faint">还没有文件。智能体写入的文件会出现在这里。</p>
            ) : (
              <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-raised">
                {s.files.map((f) => (
                  <li key={f.path} className="flex items-center gap-3 px-3.5 py-2 text-[13px]">
                    <Icon name="file" size={15} className="text-faint" />
                    <button type="button" title={'复制完整路径：' + f.full} onClick={() => copy(f.full)} className="min-w-0 flex-1 truncate text-left font-mono text-xs text-ink hover:text-accent-ink">{f.path}</button>
                    <span className="shrink-0 font-mono text-[11px] text-faint">{size(f.size)}</span>
                    <span className="hidden shrink-0 font-mono text-[11px] text-faint sm:inline">{when(f.at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Section>
        )}

        {tab === 'usage' && (
        <Section title="省 token" text="多智能体每次发言都要把对话重发给模型，这是最大的开销。开启后只发必要的部分，回答质量基本不受影响。">
          <Row title="省 token 模式" text={s.thrifty
            ? '已开启：较早的消息只发开头、历史有总量上限；技能和团队经验只在和问题相关时才发全文；系统提示保持不变，方便接口缓存；被派活的成员只看最近几条。'
            : '已关闭：每次都把完整的历史、全部技能和经验发给模型，用量会明显增加。'}>
            <Switch on={s.thrifty} disabled={locked || busy} label="省 token 模式" onChange={(v) => save({ thrifty: v }, v ? '已开启省 token' : '已关闭省 token')} />
          </Row>
        </Section>
        )}
        {tab === 'usage' && (
        <Section title="用量统计" text="按天、按模型、按智能体统计 token。每个会话的用量可以在会话设置的「用量」里查看。">
          <Usage notify={notify} locked={locked} onOpenConv={openConv} />
        </Section>
        )}

        {tab === 'team' && (
        <Section title="领头智能体" text="新建会话时自动拉进来的那一位。你只和它说话，它负责安排其他智能体。">
          <select className={inputCls} value={s.chief_id} disabled={locked || busy} onChange={(e) => save({ chief_id: e.target.value }, e.target.value ? '已设为永久领头智能体' : '已取消领头智能体')}>
            <option value="">不设置（新会话需要自己挑选成员）</option>
            {data.agents.filter((a) => !a.conv_id).map((a) => <option key={a.id} value={a.id}>{a.name}{a.description ? ' — ' + a.description : ''}</option>)}
          </select>
          <div>
            <div className="mb-2 text-[13px] font-medium text-ink">领头智能体新建或移除智能体时</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {[['ask', '先问我', '弹出卡片，写明它想新建谁、角色设定是什么，或想移除谁，由你同意。'], ['auto', '完全放开', '不再询问，直接新建或移除。']].map(([id, name, hint]) => (
                <button key={id} type="button" aria-pressed={s.team === id} disabled={locked || busy} onClick={() => save({ team: id })}
                  className={'rounded-xl border p-3.5 text-left transition-colors duration-150 disabled:opacity-60 ' + (s.team === id ? 'border-accent bg-accent-soft' : 'border-line bg-raised hover:border-line-strong')}>
                  <span className="block text-sm font-medium text-ink">{name}</span>
                  <span className="mt-1 block text-xs leading-relaxed text-muted">{hint}</span>
                </button>
              ))}
            </div>
          </div>
        </Section>
        )}

        {tab === 'lessons' && (
        <Section title="共享经验库" text="智能体犯错、被你纠正或操作失败后，会把教训记成一句话，分享给整个团队，之后谁都不再犯同样的错。">
          <Row title="启用共享经验库" text={s.lessons ? '已启用。每个智能体发言时都会带上这些经验，并会自己补充新的。' : '已关闭。智能体不会记录新经验，已有的也不会发给模型。'}>
            <Switch on={s.lessons} disabled={locked || busy} label="启用共享经验库" onChange={(v) => save({ lessons: v })} />
          </Row>
          {s.lessons && (<>
            <div className="rounded-xl bg-sunken p-3.5 text-[13px] leading-relaxed text-muted">
              <b className="font-medium text-ink">自动判断的标准</b>（四条都满足才记）：
              ① 你刚纠正过它、给了规定，或它的操作刚失败；② 写的是具体内容（名称、数字、格式、命令），不是「要注意细节」这类空话；③ 不是「我……」开头的自述；④ 和已有的经验不重复。
            </div>
            <Row title="新经验先给我确认" text={s.lessons_review ? '符合标准的经验也会先标成「待确认」，在聊天里或下面点「采纳」后才生效。' : '符合标准的经验直接生效，聊天里会提示，可以一键撤销。'}>
              <Switch on={s.lessons_review} disabled={locked || busy} label="新经验先给我确认" onChange={(v) => save({ lessons_review: v })} />
            </Row>
          </>)}
          <Lessons notify={notify} locked={locked} />
        </Section>
        )}
        {tab === 'lessons' && (
        <Section title="智能体记忆" text="和经验库不同：记忆只属于一个智能体，记的是你的偏好、项目背景、定下的决定这类以后还用得上的信息。外部智能体有自己的记忆系统，不在这里管。">
          <Row title="允许智能体记忆" text={s.memory
            ? '已开启。每个智能体的记忆在「智能体」页点开它的设置就能查看、修改、置顶或删除，也可以单独关掉某一个的记忆。'
            : '已关闭。智能体不会记录新的记忆，已有的记忆也不会发给模型（保留着，重新开启后恢复）。'}>
            <Switch on={s.memory !== false} disabled={locked || busy} label="允许智能体记忆" onChange={(v) => save({ memory: v })} />
          </Row>
        </Section>
        )}

        {tab === 'data' && (
        <Section title="数据存放位置" text="你的数据和程序代码分开放：项目文件夹里只有代码，复制、打包、发布它都不会带上你的数据。">
          <Row title="你的数据" text={s.home}>
            {s.is_local && !s.in_docker && <Btn kind="outline" icon="folder" onClick={() => api('POST', '/settings/open-data').catch((e) => notify(e.message))} className="h-8 shrink-0 px-3 text-[13px]">打开</Btn>}
          </Row>
          <p className="text-xs leading-relaxed text-faint">里面有数据库（data）、工作区（workspace，除非你改过位置），以及你自己的 config.yaml、.env。想换位置：设置环境变量 MAC_HOME 指向新文件夹，把这个文件夹整个搬过去即可。</p>
        </Section>
        )}
        {tab === 'data' && (
        <Section title="备份与恢复" text="换电脑、升级之前导出一份。恢复时会先把现在的数据另存起来，不怕恢复错。">
          <Backup notify={notify} reload={reload} locked={locked} />
        </Section>
        )}
        {tab === 'data' && (
        <Section title="聊天记录" text="勾选不需要的会话并删除。删除后数据库会自动压缩，不会越用越臃肿。">
          <Records notify={notify} reload={reload} locked={locked} />
        </Section>
        )}

        {tab === 'local' && (
        <Section title="已永久授权" text="在审批卡片上选过「永久允许」的智能体。它们的操作不再询问，直到你在这里撤销。">
          {s.grants.length === 0 ? (
            <p className="rounded-xl border border-dashed border-line-strong px-4 py-5 text-[13px] text-faint">没有被永久授权的智能体。</p>
          ) : (
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-raised">
              {s.grants.map((g) => {
                const a = data.agents.find((x) => x.id === g.id) || g
                return (
                  <li key={g.id} className="flex items-center gap-3 px-3.5 py-2.5">
                    <Avatar agent={a} size={30} />
                    <span className="min-w-0 flex-1 truncate text-sm text-ink">{g.name}</span>
                    <Tag tone="accent">永久允许</Tag>
                    <Btn kind="ghost" disabled={locked} onClick={() => revoke(g)} className="h-8 px-2.5 text-[13px]">撤销</Btn>
                  </li>
                )
              })}
            </ul>
          )}
        </Section>
        )}

        {tab === 'network' && (
        <Section title="局域网访问" text="开启后，同一个 Wi‑Fi 或网线下的手机、平板、其他电脑可以用下面的网址打开这个控制台。默认关闭。">
          <Row
            title="允许局域网内的设备访问"
            text={s.in_docker ? '程序运行在 Docker 容器里，访问由端口映射和访问口令控制，这里的开关不起作用。' : s.lan ? '已开启。其他设备打开下面任一网址即可。' : '关闭时只有这台电脑能打开控制台，其他设备会看到「局域网访问没有开启」。'}
          >
            <Switch on={s.lan} disabled={locked || busy || s.in_docker} label="允许局域网内的设备访问" onChange={(v) => save({ lan: v }, v ? '已开启局域网访问' : '已关闭局域网访问')} />
          </Row>
          {!s.lan_bind_ok && <p className="rounded-xl bg-danger-soft p-3.5 text-[13px] text-danger">服务目前只监听本机（host 是 127.0.0.1），局域网设备连不上。把配置里的 host 改回 0.0.0.0 并重启后才能用。</p>}
          {s.lan && s.lan_bind_ok && (
            <div>
              <div className="mb-2 text-[13px] font-medium text-ink">访问网址</div>
              <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-raised">
                {s.lan_urls.map((u, i) => (
                  <li key={u} className="flex items-center gap-3 px-3.5 py-2.5 text-[13px]">
                    <a href={u} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate font-mono text-accent-ink hover:underline">{u}</a>
                    {i === 0 && <Tag tone="accent">最可能是这个</Tag>}
                    <button type="button" onClick={() => copy(u)} className="shrink-0 text-xs text-muted hover:text-ink">复制</button>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs leading-relaxed text-faint">电脑上有虚拟网卡（WSL、热点、VPN）时会列出多个地址，手机用和它连的是同一个网络的那个。打不开时检查系统防火墙是否放行了端口。</p>
              {!s.token_set && <p className="mt-2 rounded-xl bg-sunken p-3 text-[13px] leading-relaxed text-muted">建议同时设置下面的访问口令，否则同一网络里的任何人都能打开它。</p>}
            </div>
          )}
        </Section>
        )}

        {tab === 'network' && (
        <Section title="访问口令" text="设置后，任何设备打开这个控制台都要先输入口令。">
          <Row
            title={s.token_set ? '已设置访问口令' : '没有访问口令'}
            text={s.token_set ? '可以在下面换一个，或者清除。' : s.lan_open ? '控制台对局域网开放。同一网络里的设备都能打开它并使用你保存的模型密钥。' : '控制台只接受本机访问。'}
          >
            {s.token_set && <Btn kind="ghost" disabled={locked || busy} onClick={clearPassword}>清除</Btn>}
          </Row>
          <div className="flex flex-wrap gap-2">
            <input className={inputCls + ' min-w-0 flex-1'} type="password" value={pw} disabled={locked} onChange={(e) => setPw(e.target.value)} placeholder={s.token_set ? '输入新的口令' : '输入要设置的口令'} aria-label="访问口令" autoComplete="new-password" />
            <Btn kind="primary" disabled={locked || busy || !pw.trim()} onClick={savePassword}>{s.token_set ? '更换口令' : '设置口令'}</Btn>
          </div>
          {s.token_set && <Blocked notify={notify} locked={locked} />}
        </Section>
        )}

        {tab === 'local' && (
        <Section title="执行限制" text="防止单个操作卡住或没完没了。">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-2 block text-[13px] font-medium text-ink">单条命令最长执行（秒）</span>
              <input className={inputCls} type="number" min="5" max="600" value={adv.timeout} disabled={locked} onChange={(e) => setAdv({ ...adv, timeout: e.target.value })} />
            </label>
            <label className="block">
              <span className="mb-2 block text-[13px] font-medium text-ink">一次发言里最多连续操作（轮）</span>
              <input className={inputCls} type="number" min="1" max="20" value={adv.max_steps} disabled={locked} onChange={(e) => setAdv({ ...adv, max_steps: e.target.value })} />
            </label>
          </div>
          <Btn disabled={locked || busy || (String(adv.timeout) === String(local.timeout) && String(adv.max_steps) === String(local.max_steps))} onClick={() => setLocal({ timeout: adv.timeout, max_steps: adv.max_steps }, '执行限制已保存')}>保存限制</Btn>
        </Section>
        )}
      </Page>
    </>
  )
}

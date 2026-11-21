import { ask } from '../components/Dialog.jsx'
import { useState } from 'react'
import { motion } from 'motion/react'
import { api } from '../lib/api'
import AgentModal from '../components/AgentModal.jsx'
import ExternalModal from '../components/ExternalModal.jsx'
import { Avatar, Btn, Empty, Icon, IconBtn, MobileBar, Page, Tag, monoTag, rise } from '../components/ui.jsx'

export default function Agents({ data, reload, notify, onChat }) {
  const [modal, setModal] = useState(null)
  const [ext, setExt] = useState(false)
  const agents = data.agents.filter((a) => !a.conv_id) // 只属于某个会话的智能体不在这里出现

  const remove = async (a) => {
    if (!await ask(`删除智能体「${a.name}」？已有的聊天记录会保留。`)) return
    await api('DELETE', '/agents/' + a.id).catch((e) => notify(e.message))
    reload()
  }
  const duplicate = async (a) => {
    await api('POST', '/agents', { ...a, name: a.name + ' 副本' }).catch((e) => notify(e.message))
    reload()
  }

  return (
    <>
      <MobileBar title="智能体">
        <IconBtn icon="plus" label="新建智能体" size={40} onClick={() => setModal({})} />
      </MobileBar>
      <Page
        eyebrow={`AGENTS · ${String(agents.length).padStart(2, '0')}`}
        title="智能体"
        lead="每个智能体有自己的名字、角色设定和模型。数量不限，可以随时拉进同一个会话协作。"
        action={<div className="flex flex-wrap gap-2"><Btn icon="link" onClick={() => setExt(true)}>接入外部智能体</Btn>{agents.length > 0 && <Btn kind="primary" icon="plus" onClick={() => setModal({})}>新建智能体</Btn>}</div>}
      >
        {agents.length === 0 ? (
          <Empty icon="agents" title="还没有智能体" text="起个名字，写下它的角色设定，再给它选一个模型，一个智能体就诞生了。">
            <div className="flex flex-wrap gap-2"><Btn kind="primary" icon="plus" onClick={() => setModal({})}>创建第一个智能体</Btn><Btn icon="link" onClick={() => setExt(true)}>接入外部智能体</Btn></div>
          </Empty>
        ) : (
          <ul className="overflow-hidden rounded-[20px] border border-line bg-raised shadow-card">
            {agents.map((a, i) => {
              const p = data.providers.find((x) => x.id === a.provider_id)
              const model = a.model || p?.default_model
              return (
                <motion.li key={a.id} {...rise(i)} className="group relative grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-3 border-b border-line px-4 py-4 transition-colors duration-150 last:border-0 hover:bg-sunken/50 md:grid-cols-[auto_minmax(0,14rem)_minmax(0,1fr)_auto] md:px-6 md:py-5">
                  <Avatar agent={a} size={46} />
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5"><span className="truncate text-[15px] font-semibold tracking-tight text-ink">{a.name}</span>{a.chief && <Tag tone="accent"><Icon name="crown" size={11} weight="fill" />总智能体</Tag>}{a.external && <Tag tone={(data.ext_online || []).includes(a.id) ? 'ok' : 'neutral'}><span className={'h-1.5 w-1.5 rounded-full ' + ((data.ext_online || []).includes(a.id) ? 'bg-ok' : 'bg-line-strong')} />{a.ext_kind || '外部'} · {(data.ext_online || []).includes(a.id) ? '已连接' : '未连接'}</Tag>}{a.auto_approve && <Tag tone="accent"><Icon name="shield" size={11} weight="fill" />永久允许操作</Tag>}{a.no_tools && <Tag>禁止本地操作</Tag>}{a.managed && <Tag>配置文件</Tag>}</div>
                    <div className="mt-0.5 truncate text-[13px] text-muted">{a.description || '暂无简介'}</div>
                    <div className="mt-2 flex min-w-0 items-center gap-1.5">
                      {a.external ? (
                        <span className="text-xs text-faint">外部智能体 · 点「编辑」查看连接方式</span>
                      ) : p ? (
                        <><span className="shrink-0 text-xs text-faint">{p.name}</span><span className={monoTag}>{model || '未指定模型'}</span>
                          {(data.memory_counts || {})[a.id] > 0 && a.memory !== false && <span title="它自己记下的长期记忆" className="inline-flex shrink-0 items-center gap-1 text-xs text-faint"><Icon name="brain" size={12} />{data.memory_counts[a.id]}</span>}
                          {(a.skills || []).length + (a.mcps || []).length > 0 && <span title="勾选的技能和 MCP 工具" className="inline-flex shrink-0 items-center gap-1 text-xs text-faint"><Icon name="sparkle" size={12} />{(a.skills || []).length + (a.mcps || []).length}</span>}</>
                      ) : (
                        <span className="rounded-md bg-danger-soft px-1.5 py-0.5 text-xs text-danger">未绑定模型渠道，暂时无法发言</span>
                      )}
                    </div>
                  </div>
                  <p className="col-span-2 line-clamp-2 text-[13px] leading-[1.7] text-muted md:col-span-1 md:border-l md:border-line md:pl-6">
                    {a.external ? <span className="text-faint">用它自己的身份、能力和记忆工作，不需要在这里设定角色。</span>
                      : a.system_prompt || <span className="text-faint">还没有角色设定。点「编辑」写下它的身份和说话方式。</span>}
                  </p>
                  <div className="col-span-2 flex items-center gap-0.5 md:col-span-1">
                    <Btn kind="outline" icon="chat" onClick={() => onChat(a)}>对话</Btn>
                    <span className="flex-1 md:w-2 md:flex-none" />
                    <IconBtn icon="edit" label="编辑" onClick={() => setModal(a)} />
                    <IconBtn icon="copy" label="复制一个副本" onClick={() => duplicate(a)} />
                    <IconBtn icon="trash" label="删除" kind="danger" onClick={() => remove(a)} />
                  </div>
                </motion.li>
              )
            })}
          </ul>
        )}
      </Page>
      {ext && <ExternalModal data={data} notify={notify} reload={reload} onClose={() => { setExt(false); reload() }} onSaved={() => { setExt(false); reload() }} />}
      {modal && (
        <AgentModal
          data={data}
          initial={modal.id ? modal : null}
          reload={reload}
          notify={notify}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); reload() }}
        />
      )}
    </>
  )
}

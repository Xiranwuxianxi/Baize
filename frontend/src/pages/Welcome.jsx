import { memo } from 'react'
import { motion } from 'motion/react'
import { Avatar, Btn, Icon } from '../components/ui.jsx'

const TEAM = [
  { name: '产品经理', avatar: 'ph:Target', color: 'persimmon', note: '梳理范围', x: 16 },
  { name: '架构师', avatar: 'ph:Code', color: 'slate', note: '给出方案', x: 50 },
  { name: '批判者', avatar: 'ph:Scales', color: 'rose', note: '排查风险', x: 84 },
]
const LINKS = ['M220 150 C 220 215, 70 205, 70 262', 'M220 150 L 220 262', 'M220 150 C 220 215, 370 205, 370 262']

// 首页右侧的示意图：领头人把任务分给成员。常驻动画放在 memo 叶子组件里。
const Diagram = memo(function Diagram() {
  const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
  return (
    <div className="relative mx-auto aspect-[11/10] w-full max-w-[440px] select-none" aria-hidden="true">
      <svg viewBox="0 0 440 400" className="absolute inset-0 h-full w-full" fill="none">
        <path d="M220 46 L 220 92" stroke="var(--line-strong)" strokeWidth="1.5" strokeDasharray="3 5" strokeLinecap="round" />
        {LINKS.map((d, i) => (
          <g key={d}>
            <path d={d} stroke="var(--line-strong)" strokeWidth="1.5" strokeLinecap="round" />
            {!still && (
              <circle r="3.5" fill="var(--accent)">
                <animateMotion dur="2.6s" begin={i * 0.5 + 's'} repeatCount="indefinite" path={d} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.4 0 0.2 1" />
                <animate attributeName="opacity" dur="2.6s" begin={i * 0.5 + 's'} repeatCount="indefinite" values="0;1;1;0" keyTimes="0;0.15;0.8;1" />
              </circle>
            )}
          </g>
        ))}
      </svg>
      <div className="absolute top-[4%] left-1/2 -translate-x-1/2 rounded-full bg-ink px-3.5 py-1.5 text-xs font-medium text-surface shadow-xs">你的一句话需求</div>
      <div className="absolute top-[23%] left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-2xl border border-line bg-raised py-2.5 pr-4 pl-2.5 shadow-card">
        <Avatar agent={{ name: '领头人', avatar: 'ph:Crown', color: 'amber' }} size={40} />
        <div>
          <div className="flex items-center gap-1.5 text-sm font-semibold text-ink">领头人<Icon name="crown" size={13} weight="fill" className="text-accent" /></div>
          <div className="text-xs whitespace-nowrap text-muted">拆解任务 · 分派 · 汇总</div>
        </div>
      </div>
      {TEAM.map((a, i) => (
        <div key={a.name} className="absolute top-[66%] -translate-x-1/2" style={{ left: a.x + '%' }}>
          <div className="animate-drift flex w-[112px] flex-col items-center rounded-2xl border border-line bg-raised px-2 py-3.5 shadow-card" style={{ animationDelay: i * -2.1 + 's' }}>
            <Avatar agent={a} size={40} />
            <div className="mt-2 text-[13px] font-semibold text-ink">{a.name}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-muted">
              <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-accent" style={{ animationDelay: i * -0.8 + 's' }} />{a.note}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
})

// 首次使用的三步引导
export default function Welcome({ data, go, newConv }) {
  const agents = data.agents.filter((a) => !a.conv_id)
  const steps = [
    { done: data.providers.length > 0, title: '接入模型渠道', text: '云端服务或本机的 Ollama、LM Studio 都可以。', act: '添加渠道', run: () => go('providers') },
    { done: agents.some((a) => a.chief), title: '设一位总智能体', text: '用「总管」模板建一个，并多建几个专业智能体供它调度。', act: '创建智能体', run: () => go('agents') },
    { done: data.conversations.length > 0, title: '开始会话', text: '新会话默认由总智能体接待，它会按需把专业智能体拉进来。', act: '新建会话', run: newConv },
  ]
  const current = steps.findIndex((s) => !s.done)
  const ready = current < 0
  return (
    <div className="scroll flex-1 overflow-y-auto">
      <div className="mx-auto grid min-h-full max-w-[1120px] items-center gap-12 px-6 py-10 md:px-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,440px)] lg:gap-16">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}>
          <p className="font-mono text-xs tracking-wide text-faint">MULTI-AGENT CONSOLE</p>
          <h1 className="mt-3 text-4xl leading-[1.1] font-semibold tracking-tighter text-ink md:text-5xl">组建你自己的<br />智能体团队</h1>
          <p className="mt-5 max-w-[44ch] text-base leading-relaxed text-muted">想建多少建多少，每个智能体可以用不同的模型。你只需要和总智能体说话，它会把合适的专业智能体拉进来一起做事。</p>
          <ol className="mt-9 max-w-[520px] divide-y divide-line border-y border-line">
            {steps.map((s, i) => {
              const active = i === current
              return (
                <li key={s.title} className="flex items-center gap-4 py-4">
                  <span className={'flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-[13px] font-semibold ' + (s.done ? 'bg-ok-soft text-ok' : active ? 'bg-ink text-surface' : 'border border-line-strong text-faint')}>
                    {s.done ? <Icon name="check" size={15} weight="bold" /> : i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className={'text-[15px] font-semibold tracking-tight ' + (s.done || active ? 'text-ink' : 'text-muted')}>{s.title}</div>
                    <div className="mt-0.5 text-[13px] leading-relaxed text-muted">{s.text}</div>
                  </div>
                  {active && <Btn kind="primary" icon="arrow" onClick={s.run} className="shrink-0 flex-row-reverse">{s.act}</Btn>}
                </li>
              )
            })}
          </ol>
          {ready && <Btn kind="primary" size="lg" icon="plus" onClick={newConv} className="mt-8">新建会话</Btn>}
        </motion.div>
        <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.7, delay: 0.1, ease: [0.16, 1, 0.3, 1] }} className="hidden lg:block">
          <Diagram />
        </motion.div>
      </div>
    </div>
  )
}

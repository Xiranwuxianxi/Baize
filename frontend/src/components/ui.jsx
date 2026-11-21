import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { t } from '../lib/i18n'
import brandIcon from '../assets/baize.png'

// 字符串就翻译，其他（元素、数组）原样返回
const tr = (v) => (typeof v === 'string' ? t(v) : v)
import {
  ArrowBendDownRight, ArrowRight, ArrowUp, ArrowsClockwise, ArrowsSplit, BookOpen, Brain, ChartBar, ChatsCircle,
  ArrowCircleUp, Check, Code, Compass, Copy, Crown, Flask, Key, Lightbulb, Lightning, Link, List, ListNumbers, MagnifyingGlass,
  FolderOpen, GearSix, Megaphone, NotePencil, Palette, PenNib, PencilSimple, Plugs, Plus, Robot, Scales, ShieldCheck, SlidersHorizontal, Sparkle,
  CaretDown, Coins, DownloadSimple, UploadSimple, PushPin, SidebarSimple, Star, Stop, Target, Terminal, Trash, TreeStructure, CaretLeft, FileText, UserPlus, UsersThree, Warning, Wrench, X, Paperclip, ImageSquare,
} from '@phosphor-icons/react'

// ---------- 图标：统一走 Phosphor，界面里不使用 emoji ----------
const ICONS = {
  menu: List, plus: Plus, x: X, chat: ChatsCircle, agents: UsersThree, plug: Plugs, sliders: SlidersHorizontal,
  up: ArrowUp, stop: Stop, copy: Copy, trash: Trash, edit: PencilSimple, check: Check, refresh: ArrowsClockwise,
  bolt: Lightning, arrow: ArrowRight, brain: Brain, crown: Crown, warn: Warning, branch: ArrowBendDownRight,
  userPlus: UserPlus, sparkle: Sparkle, key: Key, lead: TreeStructure, parallel: ArrowsSplit, relay: ListNumbers,
  back: CaretLeft, search: MagnifyingGlass, terminal: Terminal, file: FileText, write: NotePencil, shield: ShieldCheck,
  star: Star, panel: SidebarSimple, folder: FolderOpen, gear: GearSix, wrench: Wrench, link: Link, lightbulb: Lightbulb, pin: PushPin, upgrade: ArrowCircleUp,
  chevron: CaretDown, coins: Coins, chart: ChartBar, download: DownloadSimple, upload: UploadSimple, clip: Paperclip, image: ImageSquare,
}

export function Icon({ name, size = 18, weight = 'regular', className = '' }) {
  const C = ICONS[name]
  return C ? <C size={size} weight={weight} aria-hidden="true" className={'shrink-0 ' + className} /> : null
}

export function Logo({ size = 30 }) {
  return (
    <img src={brandIcon} width={size} height={size} alt="白泽 Baize" draggable={false} className="inline-block shrink-0 object-contain" />
  )
}

// ---------- 智能体头像 ----------
export const HUES = { persimmon: 42, rose: 8, amber: 78, olive: 125, pine: 165, teal: 205, slate: 255, plum: 320 }
export const HUE_NAMES = { persimmon: '陶土', rose: '玫红', amber: '琥珀', olive: '橄榄', pine: '松绿', teal: '湖青', slate: '岩蓝', plum: '梅紫' }
export const hueOf = (agent) => HUES[agent?.color] ?? 42

// 头像字形：留空用名字首字；ph:Name 用图标
export const GLYPHS = {
  Robot, Brain, Lightbulb, MagnifyingGlass, Target, Wrench, ChartBar, PenNib, BookOpen, Scales, Flask, Palette,
  Crown, Code, ShieldCheck, Compass, Megaphone, Sparkle,
}

export function Avatar({ agent, size = 36, className = '', ring = false }) {
  if (agent?.avatar_image) {
    return <img src={agent.avatar_image} alt="" draggable={false} className={'inline-block shrink-0 object-cover select-none ' + (ring ? 'ring-2 ring-surface ' : '') + className} style={{ width: size, height: size, borderRadius: size * 0.31 }} />
  }
  const key = (agent?.avatar || '').startsWith('ph:') ? agent.avatar.slice(3) : ''
  const G = GLYPHS[key]
  const text = G ? null : (!key && agent?.avatar) || [...(agent?.name || '').trim()][0] || '?'
  return (
    <span
      className={'av inline-flex shrink-0 items-center justify-center font-semibold select-none ' + (ring ? 'ring-2 ring-surface ' : '') + className}
      style={{ '--h': hueOf(agent), width: size, height: size, fontSize: size * 0.43, borderRadius: size * 0.31, lineHeight: 1 }}
    >
      {G ? <G size={size * 0.54} weight="fill" aria-hidden="true" /> : text}
    </span>
  )
}

// IM 风格的会话头像：单聊显示对方头像，群聊把成员头像拼成四宫格
export function ConvAvatar({ agents, size = 44 }) {
  if (agents.length <= 1) return <Avatar agent={agents[0] || { name: '?', color: 'slate' }} size={size} />
  const cell = (size - 10) / 2
  return (
    <span className="grid shrink-0 grid-cols-2 place-items-center gap-0.5 bg-line p-[3px]" style={{ width: size, height: size, borderRadius: size * 0.28 }}>
      {agents.slice(0, 4).map((a) => <Avatar key={a.id} agent={a} size={cell} />)}
    </span>
  )
}

export function AvatarStack({ agents, size = 28, max = 4, more = true, className = '' }) {
  const extra = more ? agents.length - max : 0
  return (
    <span className={'flex shrink-0 ' + className} style={{ gap: 0 }}>
      {agents.slice(0, max).map((a, i) => <Avatar key={a.id} agent={a} size={size} ring className={i ? '-ml-2' : ''} />)}
      {extra > 0 && <span className="-ml-2 flex items-center justify-center rounded-[9px] bg-sunken font-mono text-[11px] text-muted ring-2 ring-surface" style={{ width: size, height: size }}>+{extra}</span>}
    </span>
  )
}

// ---------- 按钮 ----------
const KIND = {
  primary: 'bg-accent text-on-accent hover:bg-accent-strong shadow-[inset_0_1px_0_rgb(255_255_255/0.2),0_1px_2px_rgb(var(--shadow)/0.16)]',
  ink: 'bg-ink text-surface hover:opacity-90 shadow-xs',
  outline: 'border border-line bg-raised text-ink hover:border-line-strong hover:bg-sunken shadow-xs',
  ghost: 'text-muted hover:bg-sunken hover:text-ink',
  danger: 'text-danger hover:bg-danger-soft',
}
const base = 'inline-flex items-center justify-center gap-2 rounded-[10px] text-sm font-medium whitespace-nowrap transition-[background-color,border-color,color,transform,opacity] duration-150 active:scale-[0.98] disabled:opacity-45 disabled:active:scale-100 '

export function Btn({ kind = 'outline', icon, size = 'md', className = '', children, ...props }) {
  return (
    <button type="button" {...props} className={base + (size === 'lg' ? 'h-11 px-5 ' : 'h-9 px-3.5 ') + KIND[kind] + ' ' + className}>
      {icon && <Icon name={icon} size={16} weight="bold" />}
      {tr(children)}
    </button>
  )
}

export function IconBtn({ icon, label, kind = 'ghost', size = 36, weight, className = '', ...props }) {
  const cls = kind === 'danger' ? 'text-faint hover:bg-danger-soft hover:text-danger' : KIND[kind]
  return (
    <button type="button" aria-label={tr(label)} title={tr(label)} {...props} className={base + cls + ' ' + className} style={{ width: size, height: size }}>
      <Icon name={icon} size={size > 32 ? 18 : 16} weight={weight} />
    </button>
  )
}

export const inputCls =
  'w-full rounded-[10px] border border-line bg-raised px-3 py-2 text-[15px] text-ink shadow-xs outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-faint hover:border-line-strong focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]'

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-2 block text-[13px] font-medium text-ink">{tr(label)}</span>
      {children}
      {hint && <span className="mt-2 block text-xs leading-relaxed text-faint">{tr(hint)}</span>}
    </label>
  )
}

export function Chip({ on, className = '', ...props }) {
  return (
    <button
      type="button"
      aria-pressed={!!on}
      {...props}
      className={'inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors duration-150 active:scale-[0.98] ' + (on ? 'border-accent bg-accent-soft font-medium text-accent-ink' : 'border-line bg-raised text-muted hover:border-line-strong hover:text-ink') + ' ' + className}
    />
  )
}

export function Tag({ tone = 'neutral', className = '', children }) {
  const tones = { neutral: 'bg-sunken text-muted', accent: 'bg-accent-soft text-accent-ink', ok: 'bg-ok-soft text-ok', danger: 'bg-danger-soft text-danger' }
  return <span className={'inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] font-medium ' + tones[tone] + ' ' + className}>{children}</span>
}

export const monoTag = 'inline-flex max-w-full items-center truncate rounded-md border border-line bg-sunken px-1.5 py-0.5 font-mono text-[11.5px] text-muted'

// 手机上是底部抽屉，电脑上是居中对话框
export function Modal({ title, sub, onClose, children, footer, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="animate-fade fixed inset-0 z-50 flex items-end justify-center bg-[rgb(20_19_16/0.42)] backdrop-blur-[6px] md:items-center md:p-8" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <motion.div
        role="dialog" aria-modal="true" aria-label={tr(title)}
        initial={{ opacity: 0, y: 24, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        className={'flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-[24px] border border-line bg-surface shadow-float md:rounded-[22px] ' + (wide ? 'md:max-w-[660px]' : 'md:max-w-[480px]')}
      >
        <div className="mx-auto mt-2.5 h-1 w-9 shrink-0 rounded-full bg-line-strong md:hidden" />
        <div className="flex items-start gap-3 px-6 pt-4 pb-4 md:px-7 md:pt-6">
          <div className="min-w-0 flex-1">
            <h2 className="text-[19px] font-semibold tracking-tight text-ink">{tr(title)}</h2>
            {sub && <p className="mt-1 text-[13px] leading-relaxed text-muted">{tr(sub)}</p>}
          </div>
          <IconBtn icon="x" label="关闭" onClick={onClose} className="-mt-1 -mr-2" />
        </div>
        <div className="scroll flex-1 space-y-6 overflow-y-auto px-6 pt-1 pb-7 md:px-7">{children}</div>
        {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-sunken/60 px-6 py-3.5 pb-[max(0.875rem,env(safe-area-inset-bottom))] md:px-7">{footer}</div>}
      </motion.div>
    </div>
  )
}

export function Empty({ icon, title, text, children }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }} className="flex flex-col items-start rounded-[20px] border border-dashed border-line-strong px-7 py-10 md:px-10 md:py-14">
      <span className="mb-5 flex h-12 w-12 items-center justify-center rounded-[14px] bg-accent-soft text-accent-ink"><Icon name={icon} size={24} weight="duotone" /></span>
      <h2 className="text-xl font-semibold tracking-tight text-ink">{tr(title)}</h2>
      <p className="mt-2 mb-6 max-w-[46ch] text-sm leading-relaxed text-muted">{tr(text)}</p>
      {children}
    </motion.div>
  )
}

// 仅手机显示的顶栏（电脑上各页面有自己的页头）
export function MobileBar({ title, children }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-1 border-b border-line bg-surface px-1 md:hidden">
      <h1 className="min-w-0 flex-1 truncate pl-3 text-[15px] font-semibold tracking-tight text-ink">{tr(title)}</h1>
      {children}
    </header>
  )
}

export function Page({ eyebrow, title, lead, action, children }) {
  return (
    <div className="scroll flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1080px] px-5 py-7 md:px-12 md:py-12">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-5 md:mb-10">
          <div>
            {eyebrow && <p className="mb-2 font-mono text-xs tracking-wide text-faint">{eyebrow}</p>}
            <h1 className="text-[28px] leading-tight font-semibold tracking-tighter text-ink md:text-4xl">{tr(title)}</h1>
            <p className="mt-3 max-w-[52ch] text-[15px] leading-relaxed text-muted">{tr(lead)}</p>
          </div>
          {action}
        </div>
        {children}
      </div>
    </div>
  )
}

// 列表逐项入场
export const rise = (i = 0) => ({
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.45, delay: Math.min(i, 8) * 0.045, ease: [0.16, 1, 0.3, 1] },
})

const LABELS = { pick: (n) => `从已拉取的 ${n} 个模型里选`, manual: '手动输入模型 ID…' }

// 模型选择：拉取到模型列表时用下拉框直接选；也可以切换成手动输入
export function ModelPicker({ value, onChange, models = [], emptyLabel, placeholder }) {
  const [manual, setManual] = useState(false)
  const known = models.includes(value)
  if (!models.length || manual || (value && !known)) {
    return (
      <div>
        <input className={inputCls + ' font-mono text-sm'} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} autoCapitalize="off" spellCheck={false} />
        {models.length > 0 && (
          <button type="button" onClick={() => { setManual(false); if (!known) onChange('') }} className="mt-1.5 text-xs text-accent-ink hover:underline">{LABELS.pick(models.length)}</button>
        )}
      </div>
    )
  }
  return (
    <select className={inputCls + ' font-mono text-sm'} value={value} onChange={(e) => (e.target.value === '\u0000' ? setManual(true) : onChange(e.target.value))}>
      <option value="">{emptyLabel}</option>
      {models.map((m) => <option key={m} value={m}>{m}</option>)}
      <option value={'\u0000'}>{LABELS.manual}</option>
    </select>
  )
}

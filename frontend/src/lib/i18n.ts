// 界面多语言：gettext 风格，直接用中文原文当键，代码里写 t('消息') 即可，可读性不受影响。
// 没有翻译的文字原样显示中文，所以可以一个文件一个文件地逐步迁移。
import en from './locales/en'

export type Lang = 'zh' | 'en'
const KEY = 'mac_lang'
const DICTS: Record<Lang, Record<string, string>> = { zh: {}, en }

export const LANGS: { id: Lang; name: string }[] = [
  { id: 'zh', name: '中文' },
  { id: 'en', name: 'English（预览，部分界面）' },
]

function detect(): Lang {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch { /* 隐私模式等拿不到 localStorage：用默认 */ }
  return 'zh'
}

let current: Lang = detect()

export const getLang = (): Lang => current

/** 切换语言并刷新页面（界面文字都在渲染时取，刷新最简单可靠）。 */
export function setLang(lang: Lang): void {
  current = lang
  try { localStorage.setItem(KEY, lang) } catch { /* 同上 */ }
  location.reload()
}

/** 翻译一段界面文字。vars 用于 {name} 这样的占位符：t('发给{name}…', { name: a.name })。 */
export function t(zh: string, vars?: Record<string, string | number>): string {
  let text = DICTS[current][zh] ?? zh
  if (vars) for (const [k, v] of Object.entries(vars)) text = text.split('{' + k + '}').join(String(v))
  return text
}

/** 测试用：直接指定语言，不刷新页面。 */
export function _useLang(lang: Lang): void {
  current = lang
}

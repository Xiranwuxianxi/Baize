import { getLang } from '../lib/i18n'
import { Logo } from './ui.jsx'

export default function BrandAbout() {
  const english = getLang() === 'en'
  return (
    <section className="max-w-2xl py-8">
      <div className="flex items-center gap-5">
        <Logo size={88} />
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink">白泽 Baize</h2>
          <p className="mt-1 text-sm text-muted">{english ? 'Different minds. Shared purpose.' : '知各有所长，协众智成事。'}</p>
        </div>
      </div>
      <h3 className="mt-8 text-base font-semibold text-ink">{english ? 'Why Baize?' : '为什么叫白泽？'}</h3>
      <p className="mt-3 text-sm leading-7 text-muted">
        {english
          ? 'Baize (白泽) is a wise creature from Chinese mythology. Yunji Qiqian describes it as able to speak and understand the nature of things. The name reflects this project’s aim: understand the strengths of different AI agents and bring them together to work under human guidance. Baize is the name’s pinyin spelling.'
          : '白泽是中国传说中的智慧瑞兽。《云笈七签·轩辕本纪》记载它“能言，达于万物之情”。项目借用这一意象：理解不同智能体的专长，连接模型与工具，让它们在人的掌控下协作。Baize 是“白泽”的拼音形式，作为英文产品名。'}
      </p>
      <p className="mt-4 text-sm leading-7 text-muted">
        {english
          ? 'The logo is a modern interpretation of the guardian: an ivory face and paired horns on deep violet, with a flowing violet mark. It expresses knowledge, protection and cooperation.'
          : '标志以白色兽面、双角和流动的紫色额纹重新演绎白泽，深紫底色衬托白玉般的轮廓，表达智慧、守护与协作。'}
      </p>
      <div className="mt-6 flex gap-5 text-sm text-accent">
        <a href="https://www.shidianguji.com/book/HY1734/chapter/1mbco3z7b0xez" target="_blank" rel="noreferrer">{english ? 'Name source' : '命名出处'}</a>
        <a href="https://github.com/Xiranwuxianxi/Baize" target="_blank" rel="noreferrer">GitHub</a>
      </div>
    </section>
  )
}

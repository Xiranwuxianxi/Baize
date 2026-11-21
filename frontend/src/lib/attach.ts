// 消息附件：图片先在浏览器里缩小再上传（看图按像素计费，大图既慢又贵），其他文件原样上传。
import { uploadRaw } from './api'

export type Attachment = { name: string; path: string; kind: 'image' | 'text' | 'file'; mime: string; size: number }

const MAX_SIDE = 1568          // 主流看图模型的推荐上限，再大也会被模型自己缩小
const MAX_BYTES = 20 * 1024 * 1024
const RESIZABLE = /^image\/(png|jpeg|webp)$/

async function shrink(file: File): Promise<{ blob: Blob; name: string }> {
  if (!RESIZABLE.test(file.type)) return { blob: file, name: file.name }
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = () => reject(new Error('这张图片打不开，可能已损坏'))
      el.src = url
    })
    const scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight))
    if (scale === 1 && file.size < 1.5 * 1024 * 1024) return { blob: file, name: file.name }
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(img.naturalWidth * scale)
    canvas.height = Math.round(img.naturalHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return { blob: file, name: file.name }
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', 0.86))
    if (!blob) return { blob: file, name: file.name }
    return { blob, name: file.name.replace(/\.[^.]+$/, '') + '.jpg' }
  } finally {
    URL.revokeObjectURL(url)
  }
}

export async function uploadAttachment(convId: string, file: File): Promise<Attachment> {
  if (file.size > MAX_BYTES) throw new Error(`「${file.name}」超过 20 MB`)
  const { blob, name } = await shrink(file)
  return uploadRaw<Attachment>(`/conversations/${convId}/attachments?name=${encodeURIComponent(name || 'image.png')}`, blob)
}

export const sizeText = (n: number): string => (n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB')

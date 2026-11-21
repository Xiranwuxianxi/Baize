// 把用户选的图片裁成正方形并缩小，转成 data URL 存进智能体资料。
// 在浏览器里完成，不需要后端装图像库；160 像素的头像通常只有几 KB。

const ACCEPTED = /^image\/(png|jpeg|webp|gif)$/
const MAX_BYTES = 12 * 1024 * 1024

export async function toAvatar(file: File, size = 160): Promise<string> {
  if (!file || !ACCEPTED.test(file.type)) throw new Error('只支持 PNG、JPG、WebP、GIF 图片')
  if (file.size > MAX_BYTES) throw new Error('图片超过 12 MB，换一张小一点的')
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = () => reject(new Error('这张图片打不开，可能已损坏'))
      el.src = url
    })
    const side = Math.min(img.naturalWidth, img.naturalHeight) // 居中裁成正方形
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = size
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('浏览器不支持图片处理')
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, size, size)
    const webp = canvas.toDataURL('image/webp', 0.86)
    // 浏览器不支持 WebP 编码时 toDataURL 会悄悄退回 PNG，这时改用体积更小的 JPEG
    return webp.startsWith('data:image/webp') ? webp : canvas.toDataURL('image/jpeg', 0.86)
  } finally {
    URL.revokeObjectURL(url)
  }
}

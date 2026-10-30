// 压缩管线(功能设计 §2.5,U10/T12):EXIF 方向 → 长边 ≤1280 等比缩放 → 白底 → JPEG 0.8
const MAX_LONG_EDGE = 1280
const JPEG_QUALITY = 0.8

/** canvas.toBlob 的 Promise 包装(useCamera 截帧与压缩管线共用)。 */
export function canvasToBlob(
  canvas: HTMLCanvasElement,
  type = 'image/jpeg',
  quality = JPEG_QUALITY,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error('canvas toBlob failed'))),
      type,
      quality,
    )
  })
}

/** 任意来源图片 → 统一 JPEG File(唯一图片对象,预览与上传共用)。 */
export async function compressImage(blob: Blob, name: string): Promise<File> {
  // T12:from-image 让浏览器按 EXIF 方向摆正;旧浏览器不支持该选项时降级
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(blob, { imageOrientation: 'from-image' })
  } catch {
    bitmap = await createImageBitmap(blob)
  }

  const scale = Math.min(1, MAX_LONG_EDGE / Math.max(bitmap.width, bitmap.height))
  const w = Math.round(bitmap.width * scale)
  const h = Math.round(bitmap.height * scale)

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  // U10:先铺白底再绘制,PNG 透明通道转 JPEG 才不会变黑底
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, w, h)
  ctx.drawImage(bitmap, 0, 0, w, h)
  bitmap.close()

  const out = await canvasToBlob(canvas)
  return new File([out], name, { type: 'image/jpeg' })
}

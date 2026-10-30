// 摄像头能力:特性探测、取流、截帧、释放(功能设计 §2.2/§2.3,技术设计 §3.4)
import { canvasToBlob } from './useCompress'

export type StreamErrorKind = 'denied' | 'no_device' | 'unknown'

export class CameraError extends Error {
  readonly kind: StreamErrorKind

  constructor(kind: StreamErrorKind) {
    super(kind)
    this.kind = kind
  }
}

/** 一次性特性探测(功能设计 §2.2):只探测不调流,避免加载即弹权限框。 */
export function detectCameraAvailable(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    window.isSecureContext === true
  )
}

let stream: MediaStream | null = null

/** 打开视频流并绑到 <video>(U7 优先后置摄像头)。失败抛 CameraError(分类见 D3)。 */
export async function openStream(video: HTMLVideoElement): Promise<void> {
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
    })
  } catch (err) {
    const name = (err as DOMException)?.name
    if (name === 'NotAllowedError' || name === 'SecurityError') throw new CameraError('denied')
    if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'NotReadableError')
      throw new CameraError('no_device')
    throw new CameraError('unknown')
  }
  video.srcObject = stream
  await video.play()
}

/** 当前视频帧截为 JPEG Blob(原分辨率,压缩由 useCompress 负责)。 */
export async function captureFrame(video: HTMLVideoElement): Promise<Blob> {
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  canvas.getContext('2d')!.drawImage(video, 0, 0)
  return canvasToBlob(canvas, 'image/jpeg', 0.95)
}

/** 立即停止全部 track 释放摄像头(U8):截帧与关闭两条路径都调。 */
export function stopStream(): void {
  stream?.getTracks().forEach((t) => t.stop())
  stream = null
}

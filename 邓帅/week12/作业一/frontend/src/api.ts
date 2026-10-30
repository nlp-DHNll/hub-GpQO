// 识别请求:35s AbortController 兜底超时 ＋ 错误映射(技术设计 §3.5,功能设计 §6.2)
import type { ApiError, Level } from './types'

// 后端 30s 超时 + 网络余量(功能设计 §4)
const RECOGNIZE_TIMEOUT_MS = 35_000

// 已知错误码;白名单之外的码前端不做分支,统一走 E4 兜底
const KNOWN_CODES = new Set(['INVALID_FILE', 'MODEL_TIMEOUT', 'MODEL_UNPARSABLE'])

export class ApiRequestError extends Error {
  readonly apiError: ApiError

  constructor(apiError: ApiError) {
    super(apiError.code)
    this.apiError = apiError
  }
}

/**
 * 上传图片识别消防隐患等级。
 * 成功返回 level;失败抛 ApiRequestError:
 * - 后端非 2xx 且 error.code 在白名单内 → 原样透传 code
 * - 请求抛错 / 35s 兜底超时 / 未知码 → code: 'NETWORK'(E4)
 */
export async function recognize(file: File): Promise<Level> {
  const form = new FormData()
  form.append('image', file)

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), RECOGNIZE_TIMEOUT_MS)

  try {
    const resp = await fetch('/api/recognize', {
      method: 'POST',
      body: form,
      signal: controller.signal,
    })

    const body = await resp.json().catch(() => null)
    if (!resp.ok) {
      const code = body?.error?.code
      if (code && KNOWN_CODES.has(code)) {
        throw new ApiRequestError({ code, message: body.error.message })
      }
      throw new ApiRequestError({ code: 'NETWORK' })
    }

    // 200 信任后端契约直接取 level
    return body?.level as Level
  } catch (err) {
    if (err instanceof ApiRequestError) throw err
    // 网络/超时/中断 → E4
    throw new ApiRequestError({ code: 'NETWORK' })
  } finally {
    clearTimeout(timer)
  }
}

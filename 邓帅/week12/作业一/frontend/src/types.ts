// 类型与结果呈现常量(技术设计 §3.2;文案值以功能设计 §5.2/§7 为准源)

export type Level = 'high' | 'medium' | 'low' | 'none' | 'not_corridor'
export type Phase = 'empty' | 'preview' | 'recognizing' | 'result' | 'error'
export type ImageSource = 'camera' | 'album'

export interface ApiError {
  code: string
  message?: string
}

export interface ResultMeta {
  label: string
  color: string
  criterion: string | null
}

// not_corridor 的 criterion 为 null(结果页改展示 R5 引导文案)
export const RESULT_META: Record<Level, ResultMeta> = {
  high: {
    label: '高风险',
    color: '#F56C6C',
    criterion: '楼道中出现电动车、电瓶、飞线充电等可能起火的元素',
  },
  medium: {
    label: '中风险',
    color: '#E6A23C',
    criterion: '大量堆积物严重影响通行，或堆放大量纸箱、木质家具等易燃堵塞物',
  },
  low: {
    label: '低风险',
    color: '#F7D75B',
    criterion: '存在楼道堆物现象，但不严重',
  },
  none: {
    label: '无风险',
    color: '#67C23A',
    criterion: '楼道干净，无堆放物品',
  },
  not_corridor: {
    label: '非楼道',
    color: '#909399',
    criterion: null,
  },
}

// not_corridor 引导文案(S9)
export const NOT_CORRIDOR_TIP = '该图片不是楼道场景，请拍摄楼道照片'

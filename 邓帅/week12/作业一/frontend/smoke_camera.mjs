// M5 冒烟:拍照链路(fake 流)/降级(D2)/权限拒绝(D3)/四类错误文案与重试(E1–E4)/再拍一张回跳
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

mkdirSync('shots', { recursive: true })

const results = []
const log = (name, ok) => {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`)
}

const URL = 'http://localhost:5173'
const browser = await chromium.launch({
  channel: 'chrome',
  headless: true,
  // fake 摄像头设备 + 自动授权,供场景 A 真实取流
  args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
})

async function newPage() {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await page.goto(URL)
  return page
}

// —— 场景 A:摄像头拍照全链路(PRD 验收项 2 的自动化部分) ——
{
  const page = await newPage()
  await page.click('button:has-text("拍照")')
  await page.waitForSelector('video') // 取景层展开
  // 等视频真正渲染出帧(用户视角:看到画面才截帧)
  await page.waitForFunction(
    () => {
      const v = document.querySelector('video')
      return v && v.videoWidth > 0 && v.readyState >= 2
    },
    null,
    { timeout: 10000 },
  )
  log('A1 点拍照展开取景层', true)
  await page.screenshot({ path: 'shots/m5_a1_camera.png' })
  await page.click('button:has-text("截帧")')
  await page.waitForSelector('img[alt="待识别图片"]')
  log('A2 截帧后进入预览', true)
  const videoGone = (await page.$('video')) === null
  log('A3 取景层关闭且流释放(video 卸载)', videoGone)
  await page.click('button:has-text("确认识别")')
  await page.waitForSelector('.level-badge', { timeout: 60000 })
  log('A4 拍照图真识别出结果', true)
  await page.screenshot({ path: 'shots/m5_a4_result.png' })
  // 再拍一张回跳(U6):camera 来源 → 直接展开取景层(fake 流是绿屏,可能判 not_corridor →「重新拍摄」)
  await page.click('button:has-text("再拍一张"), button:has-text("重新拍摄")')
  await page.waitForSelector('video')
  log('A5 再拍一张直接调起取景层(U6)', true)
  await page.close()
}

// —— 场景 B:摄像头降级(近似手机 HTTP:覆盖 isSecureContext=false) ——
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  await context.addInitScript(() => {
    Object.defineProperty(window, 'isSecureContext', { value: false })
  })
  const page = await context.newPage()
  await page.goto(URL)
  await page.waitForSelector('h1')
  const cameraHidden = (await page.$('button:has-text("拍照")')) === null
  const albumVisible = !!(await page.$('button:has-text("相册上传")'))
  const d2 = await page.textContent('body')
  log('B1 非安全上下文:拍照入口隐藏', cameraHidden)
  log('B2 相册上传保留', albumVisible)
  log('B3 D2 降级说明出现', d2.includes('当前环境不支持摄像头，可通过相册选择照片'))
  await page.screenshot({ path: 'shots/m5_b_degrade.png' })
  await context.close()
}

// —— 场景 C:取流被拒(D3)→ 改用相册出口 ——
{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  await context.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw Object.assign(new Error('denied'), { name: 'NotAllowedError' })
    }
  })
  const page = await context.newPage()
  await page.goto(URL)
  await page.waitForSelector('button:has-text("拍照")')
  await page.click('button:has-text("拍照")')
  await page.waitForSelector('.stream-error')
  const d3 = await page.textContent('.stream-error')
  log('C1 权限被拒:取景层内 D3 提示', d3.includes('无法访问摄像头，请检查权限或改用相册上传'))
  await page.screenshot({ path: 'shots/m5_c3_denied.png' })
  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.click('button:has-text("改用相册上传")'),
  ])
  await chooser.setFiles('../test_images/nb_clean.jpg')
  await page.waitForSelector('img[alt="待识别图片"]')
  log('C2 改用相册出口:选图进入预览', true)
  const emptyEntryVisible = !!(await page.$('button:has-text("重选")'))
  log('C3 空态入口可见性不变(来源已切相册,按钮为重选)', emptyEntryVisible)
  await context.close()
}

// —— 场景 D:四类异常文案与重试(spec web 失败态,验收项 6 前端侧) ——
{
  const page = await newPage()
  const input = page.locator('input[type=file]')
  const cases = [
    { name: 'D1 504 MODEL_TIMEOUT → E2', body: { error: { code: 'MODEL_TIMEOUT', message: 'x' } }, status: 504, expect: '识别超时，请重试' },
    { name: 'D2 502 MODEL_UNPARSABLE → E3', body: { error: { code: 'MODEL_UNPARSABLE', message: 'x' } }, status: 502, expect: '识别失败，请重试或换一张照片' },
    { name: 'D3 未知错误码 → E4 兜底', body: { error: { code: 'WEIRD_CODE', message: 'x' } }, status: 500, expect: '网络异常，请检查连接后重试' },
  ]
  for (const c of cases) {
    await page.route('**/api/recognize', (route) =>
      route.fulfill({ status: c.status, contentType: 'application/json', body: JSON.stringify(c.body) }),
    )
    await input.setInputFiles('../test_images/nb_clean.jpg')
    await page.click('button:has-text("确认识别")')
    await page.waitForSelector('.error-panel')
    const text = await page.textContent('.error-panel')
    log(`${c.name}`, text.includes(c.expect))
    const imgKept = !!(await page.$('img[alt="待识别图片"]'))
    log(`${c.name} · 失败不清空图片`, imgKept)
  }
  await page.screenshot({ path: 'shots/m5_d_error.png' })
  // D4 断网(E4) + 重试成功:D3 结束仍处 error 态(图片保留),断网点重试 → E4,恢复后重试 → 结果
  await page.unrouteAll()
  await page.context().setOffline(true)
  await page.click('button:has-text("重试")')
  await page.waitForFunction(
    () => document.querySelector('.error-panel')?.textContent?.includes('网络异常，请检查连接后重试'),
    null,
    { timeout: 10000 },
  )
  log('D4 断网上传 → E4 文案', true)
  await page.context().setOffline(false)
  await page.waitForTimeout(500)
  await page.click('button:has-text("重试")')
  await page.waitForSelector('.level-badge', { timeout: 60000 })
  log('D4 恢复网络重试成功出结果', true)
  await page.screenshot({ path: 'shots/m5_d4_retry_ok.png' })
  await page.close()
}

await browser.close()
const failed = results.filter((r) => !r.ok)
console.log(failed.length ? `\n${failed.length} FAILED` : '\nALL PASS')
process.exit(failed.length ? 1 : 0)

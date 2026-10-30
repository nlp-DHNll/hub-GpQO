// M4 相册链路自动冒烟(PRD 验收项 4、5):手机 viewport 下跑系统 Chrome
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

mkdirSync('shots', { recursive: true })

const results = []
const log = (name, ok) => {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`)
}

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
await page.goto('http://localhost:5173')

// 1. 空态:标题 + 双入口(localhost 安全上下文,摄像头可用)
await page.waitForSelector('h1:has-text("楼道消防隐患识别")')
const hasBothEntries = !!(await page.$('button:has-text("拍照")')) &&
  !!(await page.$('button:has-text("相册上传")'))
log('空态:标题 + 拍照/相册双入口可见', hasBothEntries)
await page.screenshot({ path: 'shots/m4_1_empty.png' })

// 2. 点击「相册上传」真的打开文件选择器,选高风险图
const [chooser] = await Promise.all([
  page.waitForEvent('filechooser'),
  page.click('button:has-text("相册上传")'),
])
log('点击相册上传打开文件选择器', !!chooser)
await chooser.setFiles('../test_images/high_corridor_ebike.jpg')

// 3. 预览出现;预览阶段不上传(无遮罩)
await page.waitForSelector('img[alt="待识别图片"]')
log('预览图出现', true)
log('预览阶段无识别遮罩(预览不上传)', (await page.$('.loading-overlay')) === null)
await page.screenshot({ path: 'shots/m4_2_preview.png' })

// 4. 重选替换图片(直接换 landscape)后停留预览;再重复选同一张(U9)
const input = page.locator('input[type=file]')
await input.setInputFiles('../test_images/landscape1.jpg')
await page.waitForTimeout(600)
log('重选后停留预览态', !!(await page.$('button:has-text("确认识别")')))
await input.setInputFiles('../test_images/landscape1.jpg') // 同一张再选一次
await page.waitForTimeout(600)
log('重复选同一张仍触发 change(U9)', !!(await page.$('img[alt="待识别图片"]')))
await page.screenshot({ path: 'shots/m4_3_reselect.png' })

// 5. 取消回空态
await page.click('button:has-text("取消")')
await page.waitForSelector('button:has-text("相册上传")')
log('取消清空图片回空态', true)

// 6. 选图 → 确认识别 → 遮罩＋按钮禁用 → 真识别出结果
await input.setInputFiles('../test_images/high_corridor_ebike.jpg')
await page.click('button:has-text("确认识别")')
// 识别中:遮罩可见,预览页按钮全部禁用(U2,spec web「识别中不可中断」)
await page.waitForSelector('.loading-overlay')
const recognizingDisabled = await page.$$eval('.actions button', (btns) =>
  btns.every((b) => b.disabled),
)
log('识别中全部按钮禁用', recognizingDisabled)
await page.waitForSelector('.level-badge', { timeout: 60000 })
const badge = (await page.textContent('.level-badge')).trim()
log(`真识别出结果:${badge}`, badge === '高风险')
await page.screenshot({ path: 'shots/m4_4_result.png' })

await browser.close()
const failed = results.filter((r) => !r.ok)
console.log(failed.length ? `\n${failed.length} FAILED` : '\nALL PASS')
process.exit(failed.length ? 1 : 0)

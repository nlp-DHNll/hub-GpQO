/* ============================================================
   楼道消防安全隐患识别 · 前端逻辑
   摄像头取景 → 拍照 / 上传 → 调用后端识别 → 渲染分级结果
   ============================================================ */
'use strict';

const $ = (sel) => document.querySelector(sel);

/* 等级 → 配色 key */
const LEVEL_KEY = { '高风险': 'h', '中风险': 'm', '低风险': 'l', '无风险': 'n', '非楼道': 'x' };
const LEVEL_COLOR = { h: '#dc2626', m: '#ea580c', l: '#d97706', n: '#16a34a', x: '#64748b' };
const LEVEL_SHORT = { '高风险': '高风险', '中风险': '中风险', '低风险': '低风险', '无风险': '无风险', '非楼道': '非楼道' };

const state = {
  models: [],
  model: '',
  mock: false,
  stream: null,
  facing: 'environment',
  lastBlob: null,
  lastResult: null,
  voice: false,
  busy: false,
  timer: null,
};

/* ---------------------------------------------------------------- 初始化 */
document.addEventListener('DOMContentLoaded', init);

async function init() {
  bindEvents();
  await loadModels();
  await loadHealth();
  await loadHistory();

  /* 界面预览：URL 加 ?demo=h|m|l|n|x 可直接看某一档的渲染效果，不消耗模型额度 */
  const qs = new URLSearchParams(location.search);
  if (qs.has('demo')) {
    $('#stageTag').textContent = '界面预览';
    setHint('当前为界面预览模式（?demo=），不会调用模型。去掉地址栏参数即可正常使用。', 'warn');
    render(demoData(qs.get('demo') || 'h'));
    return;
  }
  await startCamera();
}

/* 仅供界面预览的样例数据 */
function demoData(key) {
  const table = {
    h: ['高风险', 88, ['电动自行车', '电瓶'], true, true],
    m: ['中风险', 58, ['纸箱堆', '旧家具'], true, true],
    l: ['低风险', 22, ['儿童车'], false, false],
    n: ['无风险', 4, [], false, false],
    x: ['非楼道', 0, [], false, false],
  };
  const [level, score, names, blocked, flammable] = table[key] || table.h;
  return {
    risk_level: level,
    risk_score: score,
    scene: key === 'x' ? '室内客厅' : '居民楼三层楼梯间',
    is_corridor: key !== 'x',
    blocked_passage: blocked,
    flammable_material: flammable,
    hazards: names.map((n, i) => ({
      name: n,
      category: ['电动车', '可燃堆积物'][i % 2],
      severity: i === 0 ? '高' : '中',
      location: i === 0 ? '画面右侧贴墙' : '楼梯拐角',
      reason: i === 0 ? '停放在疏散走道内，电池存在热失控引燃风险' : '成摞堆放在楼梯口，着火后会阻断唯一疏散路径',
    })),
    evidence:
      key === 'x'
        ? '画面主体为室内客厅，可见沙发与茶几，未出现公共楼道、楼梯间等疏散通道特征。'
        : '画面右侧贴墙停放一辆电动自行车，占用走道约三分之一宽度；楼梯拐角处堆放约四五个纸箱，紧邻踏步。',
    suggestion:
      key === 'x'
        ? '该画面不属于楼道场景，无需按楼道隐患处置。'
        : '立即将电动车移至室外集中充电点，清理楼梯口纸箱，恢复疏散通道畅通。',
    confidence: 0.9,
    meta: { model: 'preview', model_label: '界面预览样例', elapsed_ms: 1200, timestamp: '预览数据' },
  };
}

function bindEvents() {
  $('#btnShoot').addEventListener('click', capture);
  $('#btnSwitch').addEventListener('click', () => {
    state.facing = state.facing === 'environment' ? 'user' : 'environment';
    startCamera(state.facing);
  });
  $('#btnUpload').addEventListener('click', () => $('#fileInput').click());
  $('#fileInput').addEventListener('change', (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) handleFile(f);
    e.target.value = '';
  });

  $('#modelSelect').addEventListener('change', (e) => {
    state.model = e.target.value;
    $('#btnReanalyze').hidden = !state.lastBlob;
  });
  $('#btnReanalyze').addEventListener('click', () => {
    if (state.lastBlob) analyze(state.lastBlob);
  });

  $('#btnVoice').addEventListener('click', (e) => {
    state.voice = !state.voice;
    e.currentTarget.setAttribute('aria-pressed', String(state.voice));
    e.currentTarget.textContent = `语音播报：${state.voice ? '开' : '关'}`;
    if (state.voice) speak('语音播报已开启');
  });

  $('#btnCopy').addEventListener('click', async () => {
    if (!state.lastResult) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(state.lastResult, null, 2));
      flash('#btnCopy', '已复制');
    } catch {
      flash('#btnCopy', '复制失败');
    }
  });

  $('#btnSelfcheck').addEventListener('click', selfcheck);
  $('#btnClear').addEventListener('click', clearHistory);

  /* 桌面端：拖拽 / 粘贴 图片 */
  ['dragover', 'drop'].forEach((evt) =>
    document.addEventListener(evt, (e) => {
      e.preventDefault();
      if (evt === 'drop' && e.dataTransfer?.files?.[0]) handleFile(e.dataTransfer.files[0]);
    })
  );
  document.addEventListener('paste', (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'));
    if (item) handleFile(item.getAsFile());
  });
}

/* ---------------------------------------------------------------- 模型 & 状态 */
async function loadModels() {
  const sel = $('#modelSelect');
  try {
    const res = await fetch('/api/models');
    const j = await res.json();
    state.models = j.models || [];
    state.mock = !!j.mock_mode;

    sel.innerHTML = state.models
      .map((m) => {
        const mark = m.blocked ? ' · 不可用' : '';
        return `<option value="${m.id}" ${m.available ? '' : 'disabled'}>${m.label} · ${m.provider_label}${mark}</option>`;
      })
      .join('');

    const pick = j.default || (state.models[0] && state.models[0].id) || '';
    if (pick) sel.value = pick;
    state.model = sel.value;
    sel.disabled = state.mock;

    if (state.mock) {
      showBanner(
        '<strong>当前为演示模式</strong>：项目里没有检测到有效的模型 API Key，识别结果由内置样例返回，仅用于预览界面。' +
          '把 Key 填进 .env 的 <code>DASHSCOPE_API_KEY=sk-xxx</code>，重启服务即可切换为真实识别。',
        'warn'
      );
    } else {
      hideBanner();
    }
  } catch (err) {
    showBanner('无法连接后端服务，请确认 <code>python run.py</code> 已启动。', 'error');
  }
}

async function loadHealth() {
  try {
    const j = await (await fetch('/api/health')).json();
    const dot = $('#statusDot');
    dot.dataset.state = j.mock_mode ? 'mock' : 'ok';
    dot.title = j.mock_mode ? '演示模式（未配置 Key）' : `${j.models_ready} 个模型可用`;
    $('#footInfo').textContent =
      `可用模型 ${j.models_ready}/${j.models_total} · 图片压缩长边 ${j.max_side}px · 结果缓存 ${j.cache ? '开' : '关'}`;
  } catch {
    $('#statusDot').dataset.state = 'err';
  }
}

async function selfcheck() {
  const btn = $('#btnSelfcheck');
  if (state.mock) {
    showBanner('没有可用的 API Key，无法自检。请先在 .env 里填写 Key 并重启服务。', 'warn');
    return;
  }
  btn.disabled = true;
  btn.textContent = '自检中…';
  try {
    const j = await (await fetch('/api/selfcheck')).json();
    const rows = (j.results || []).map((r) =>
      r.ok
        ? `✅ ${r.model}：可用（${r.elapsed_ms}ms）`
        : `❌ ${r.model}：${escapeHtml(r.error || '失败')}`
    );
    showBanner(rows.join('<br>') || escapeHtml(j.hint || '没有可自检的模型'), rows.every((r) => r.startsWith('✅')) ? 'info' : 'error');
  } catch {
    showBanner('自检请求失败', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '连通自检';
  }
}

/* ---------------------------------------------------------------- 摄像头 */
async function startCamera(facing = state.facing) {
  const video = $('#video');
  stopCamera();

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $('#stageTag').textContent = '摄像头不可用';
    setHint(
      '当前页面无法直接调用摄像头（通常是因为用 http 打开，或浏览器不支持）。请点「相册」按钮，系统会打开手机相机拍照上传，效果一致。',
      'warn'
    );
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1440 } },
      audio: false,
    });
    state.stream = stream;
    video.srcObject = stream;
    await video.play().catch(() => {});
    showVideo();
    $('#stageTag').textContent = facing === 'user' ? '前置摄像头' : '后置摄像头';
    setHint('把楼道整体和地面堆物一起拍进画面，光线充足时判定更准。');
    video.onloadedmetadata = () => {
      $('#stageRes').textContent = `${video.videoWidth}×${video.videoHeight}`;
    };
  } catch (err) {
    const name = err && err.name;
    const map = {
      NotAllowedError: '摄像头权限被拒绝。请在浏览器地址栏的权限里允许摄像头，或直接用「相册」上传。',
      PermissionDeniedError: '摄像头权限被拒绝，可改用「相册」上传照片。',
      NotFoundError: '没有找到可用的摄像头，请改用「相册」上传。',
      NotReadableError: '摄像头被其他程序占用（比如视频会议），关掉后再试。',
      OverconstrainedError: '该设备不支持所选摄像头，试试「翻转」换成另一个。',
    };
    setHint(map[name] || `摄像头启动失败：${err.message || name}`, 'warn');
    $('#stageTag').textContent = '摄像头不可用';
  }
}

function stopCamera() {
  if (state.stream) {
    state.stream.getTracks().forEach((t) => t.stop());
    state.stream = null;
  }
}

function showVideo() {
  $('#stage').dataset.live = '1';
  $('#stageEmpty').hidden = true;
  $('#shotPreview').hidden = true;
  if ($('#shotPreview').src) {
    URL.revokeObjectURL($('#shotPreview').src);
    $('#shotPreview').removeAttribute('src');
  }
}

function showPreview(url) {
  $('#stage').dataset.live = '0';
  const img = $('#shotPreview');
  img.src = url;
  img.hidden = false;
  $('#stageEmpty').hidden = true;
}

/* ---------------------------------------------------------------- 取图 */
function capture() {
  const video = $('#video');
  /* 摄像头不可用（比如手机用 http 打开）时，快门直接调起系统相机 */
  if (!state.stream || !video.videoWidth) {
    setHint('正在调起系统相机（当前页面无法直接调用摄像头）…');
    $('#fileInput').click();
    return;
  }
  const maxSide = 1280;
  const scale = Math.min(1, maxSide / Math.max(video.videoWidth, video.videoHeight));
  const w = Math.round(video.videoWidth * scale);
  const h = Math.round(video.videoHeight * scale);

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  canvas.getContext('2d').drawImage(video, 0, 0, w, h);

  /* 快门白闪 */
  const stage = $('#stage');
  stage.style.transition = 'none';
  stage.style.filter = 'brightness(1.8)';
  requestAnimationFrame(() => {
    stage.style.transition = 'filter .28s ease-out';
    stage.style.filter = '';
  });

  canvas.toBlob((blob) => blob && handleBlob(blob), 'image/jpeg', 0.9);
}

function handleFile(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    setHint('请选择图片文件。', 'warn');
    return;
  }
  if (file.size > 15 * 1024 * 1024) {
    setHint('图片超过 15MB，请压缩或截图后再上传。', 'warn');
    return;
  }
  /* HEIC 等浏览器不能解码的格式，直接交给后端，后端会给出提示 */
  const url = URL.createObjectURL(file);
  showPreview(url);
  $('#stageTag').textContent = '已选图片';
  $('#stageRes').textContent = '';
  state.lastBlob = file;
  analyze(file);
}

function handleBlob(blob) {
  const url = URL.createObjectURL(blob);
  showPreview(url);
  $('#stageTag').textContent = '已拍摄';
  state.lastBlob = blob;
  analyze(blob);
}

/* ---------------------------------------------------------------- 识别 */
async function analyze(blob) {
  if (state.busy) return;
  state.busy = true;
  setBusyUI(true);
  showLoading();

  const fd = new FormData();
  fd.append('image', blob, 'corridor.jpg');
  fd.append('model', state.model || '');
  if (state.mock) fd.append('mock', '1');

  const t0 = performance.now();
  state.timer = setInterval(() => {
    $('#loadingTimer').textContent = ((performance.now() - t0) / 1000).toFixed(1) + 's';
  }, 100);

  try {
    const res = await fetch('/api/analyze', { method: 'POST', body: fd });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.detail || `请求失败（HTTP ${res.status}）`);
    if (!j.ok || !j.data) throw new Error('返回数据异常');
    state.lastResult = j.data;
    render(j.data);
    loadHistory();
  } catch (err) {
    renderError(err.message || String(err));
  } finally {
    state.busy = false;
    setBusyUI(false);
    clearInterval(state.timer);
    $('#scanLine').hidden = true;
  }
}

function setBusyUI(busy) {
  $('#btnShoot').disabled = busy;
  $('#btnReanalyze').disabled = busy;
}

function showLoading() {
  $('#emptyState').hidden = true;
  $('#resultBody').hidden = true;
  $('#loadingState').hidden = false;
  $('#loadingTimer').textContent = '0.0s';
  $('#scanLine').hidden = false;
  $('#btnCopy').hidden = true;
}

/* ---------------------------------------------------------------- 渲染 */
function render(d) {
  const card = $('#resultCard');
  const key = LEVEL_KEY[d.risk_level] || 'x';
  card.dataset.risk = key;

  $('#emptyState').hidden = true;
  $('#loadingState').hidden = true;
  $('#resultBody').hidden = false;
  $('#hazardBlock').hidden = false;
  $('#suggestBlock').hidden = false;

  $('#levelBadge').textContent = d.risk_level || '未知';
  $('#levelBadge').style.fontSize = '';

  const sceneBits = [];
  if (d.scene) sceneBits.push(d.scene);
  if (!d.is_corridor) sceneBits.push('判定为非楼道场景');
  $('#sceneText').textContent = sceneBits.join(' · ');

  const score = Math.max(0, Math.min(100, Number(d.risk_score) || 0));
  $('#scoreNum').textContent = score;
  const bar = $('#scoreBar');
  bar.style.width = '0%';
  requestAnimationFrame(() => {
    bar.style.width = Math.max(score, 2) + '%';
  });

  /* 判定要素 */
  const flags = [
    { on: d.is_corridor, label: d.is_corridor ? '楼道场景' : '非楼道场景', offLabel: '非楼道场景' },
    { on: d.blocked_passage, label: '通道受阻', offLabel: '通道通畅' },
    { on: d.flammable_material, label: '可燃物聚集', offLabel: '无可燃物聚集' },
  ];
  const conf = Math.round((Number(d.confidence) || 0) * 100);
  $('#flags').innerHTML =
    flags.map((f) => flagHtml(f.on, f.on ? f.label : f.offLabel)).join('') +
    `<span class="flag" data-on="${conf >= 80 ? 1 : 0}">${iconInfo()}置信度 ${conf}%</span>`;

  $('#evidenceText').textContent = d.evidence || '模型未给出依据描述。';

  const hazards = Array.isArray(d.hazards) ? d.hazards : [];
  $('#hazardCount').textContent = hazards.length ? `${hazards.length} 项` : '0 项';
  $('#hazardList').innerHTML = hazards.length
    ? hazards
        .map(
          (h) => `
        <div class="hazard">
          <span class="hazard-sev" data-sev="${escapeHtml(h.severity || '中')}">${escapeHtml((h.severity || '中').slice(0, 1))}</span>
          <div class="hazard-main">
            <div class="hazard-name">${escapeHtml(h.name || '隐患')}${h.category ? `<em>${escapeHtml(h.category)}</em>` : ''}</div>
            ${h.location ? `<div class="hazard-loc">位置：${escapeHtml(h.location)}</div>` : ''}
            ${h.reason ? `<div class="hazard-reason">${escapeHtml(h.reason)}</div>` : ''}
          </div>
        </div>`
        )
        .join('')
    : '<p class="hazard-reason" style="color:var(--ink-4)">未发现具名的隐患要素。</p>';

  $('#suggestText').textContent = d.suggestion || '—';

  const meta = d.meta || {};
  const bits = [];
  bits.push(`<span>模型 <b>${escapeHtml(meta.model_label || meta.model || '-')}</b></span>`);
  if (meta.fallback_from) bits.push(`<span>首选 ${escapeHtml(meta.fallback_from)} 不可用已兜底</span>`);
  if (meta.elapsed_ms != null) bits.push(`<span>耗时 <b>${(meta.elapsed_ms / 1000).toFixed(2)}s</b></span>`);
  if (meta.cached) bits.push('<span>命中缓存</span>');
  if (meta.mock) bits.push('<span>演示数据</span>');
  if (meta.image_size) bits.push(`<span>${meta.image_size[0]}×${meta.image_size[1]}</span>`);
  if (meta.timestamp) bits.push(`<span>${escapeHtml(meta.timestamp)}</span>`);
  $('#metaLine').innerHTML = bits.join('');

  $('#btnCopy').hidden = false;
  if (state.voice) {
    const txt = `${d.risk_level}。${d.evidence || ''} ${d.suggestion || ''}`;
    speak(txt);
  }
}

function flagHtml(on, label) {
  const svg = on
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  return `<span class="flag" data-on="${on ? 1 : 0}">${svg}${escapeHtml(label)}</span>`;
}

function iconInfo() {
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/></svg>';
}

function renderError(msg) {
  const card = $('#resultCard');
  card.dataset.risk = 'x';
  $('#emptyState').hidden = true;
  $('#loadingState').hidden = true;
  $('#resultBody').hidden = false;
  $('#hazardBlock').hidden = true;
  $('#suggestBlock').hidden = true;
  $('#btnCopy').hidden = true;

  $('#levelBadge').textContent = '识别失败';
  $('#levelBadge').style.fontSize = '20px';
  $('#sceneText').textContent = '';
  $('#scoreNum').textContent = '—';
  $('#scoreBar').style.width = '0%';
  $('#flags').innerHTML = '';
  $('#evidenceText').textContent = msg;
  $('#metaLine').innerHTML =
    '<span>检查 .env 里的 API Key 是否正确、模型名是否已开通，然后点「连通自检」定位问题</span>';
}

/* ---------------------------------------------------------------- 历史 */
async function loadHistory() {
  try {
    const j = await (await fetch('/api/history?limit=30')).json();
    const items = j.items || [];
    const list = $('#historyList');
    $('#historyCount').textContent = j.total ? `共 ${j.total} 条` : '';

    const stats = j.stats || {};
    $('#historyStats').innerHTML = Object.keys(LEVEL_KEY)
      .filter((k) => stats[k])
      .map(
        (k) =>
          `<span><i style="background:${LEVEL_COLOR[LEVEL_KEY[k]]}"></i>${k} ${stats[k]}</span>`
      )
      .join('');

    if (!items.length) {
      list.innerHTML = '<p class="history-empty">暂无记录</p>';
      return;
    }

    list.innerHTML = items
      .map((it) => {
        const lv = LEVEL_KEY[it.risk_level] || 'x';
        const thumb = it.image
          ? `<img src="/uploads/${encodeURIComponent(it.image)}" alt="" loading="lazy" />`
          : '';
        return `
        <button class="hitem" data-id="${escapeHtml(it.id)}" type="button">
          <div class="hitem-thumb">${thumb}<span class="hbadge" data-lv="${lv}">${escapeHtml(it.risk_level || '—')}</span></div>
          <div class="hitem-body">
            <div class="hitem-time">${escapeHtml((it.ts || '').slice(5, 16))}</div>
            <div class="hitem-ev">${escapeHtml(it.evidence || it.scene || '')}</div>
          </div>
        </button>`;
      })
      .join('');

    list.querySelectorAll('.hitem').forEach((btn) => {
      btn.addEventListener('click', () => {
        const it = items.find((x) => x.id === btn.dataset.id);
        if (!it) return;
        if (it.image) showPreview(`/uploads/${encodeURIComponent(it.image)}`);
        render({
          risk_level: it.risk_level,
          risk_score: it.risk_score,
          scene: it.scene,
          is_corridor: it.risk_level !== '非楼道',
          hazards: it.hazards || [],
          blocked_passage: (it.hazards || []).some((h) => h.category === '堵塞通道'),
          flammable_material: (it.hazards || []).some((h) => h.category === '可燃堆积物'),
          evidence: it.evidence,
          suggestion: it.suggestion,
          confidence: 0.85,
          meta: { model_label: it.model_label, model: it.model, elapsed_ms: it.elapsed_ms, timestamp: it.ts, mock: it.mock },
        });
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
  } catch {
    /* 历史失败不影响主流程 */
  }
}

async function clearHistory() {
  if (!confirm('清空全部识别记录？（图片文件保留在 uploads 目录）')) return;
  await fetch('/api/history', { method: 'DELETE' });
  loadHistory();
}

/* ---------------------------------------------------------------- 小工具 */
function setHint(text, kind) {
  const el = $('#hint');
  el.textContent = text;
  el.dataset.kind = kind || '';
  el.hidden = false;
}

function showBanner(html, kind) {
  const el = $('#banner');
  el.innerHTML = html;
  el.dataset.kind = kind || 'info';
  el.hidden = false;
}

function hideBanner() {
  $('#banner').hidden = true;
}

function flash(sel, text) {
  const el = $(sel);
  const old = el.textContent;
  el.textContent = text;
  setTimeout(() => (el.textContent = old), 1400);
}

function speak(text) {
  if (!('speechSynthesis' in window) || !text) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.slice(0, 160));
  u.lang = 'zh-CN';
  u.rate = 1.05;
  window.speechSynthesis.speak(u);
}

function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

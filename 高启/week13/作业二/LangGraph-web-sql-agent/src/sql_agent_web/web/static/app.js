const form = document.querySelector('#query-form');
const textarea = document.querySelector('#question');
const sendButton = document.querySelector('#send-button');
const messages = document.querySelector('#messages');
const welcome = document.querySelector('#welcome');
const modelName = document.querySelector('#model-name');

function addMessage(className, label, text) {
  const article = document.createElement('article');
  article.className = `message ${className}`;
  const heading = document.createElement('div');
  heading.className = 'message-label';
  heading.textContent = label;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  article.append(heading, bubble);
  messages.append(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return article;
}

function addThinking() {
  const article = document.createElement('article');
  article.className = 'message assistant';
  article.innerHTML = '<div class="message-label">LANGGRAPH AGENT</div><div class="bubble thinking"><i></i><i></i><i></i><span>正在分析问题并执行安全查询</span></div>';
  messages.append(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return article;
}

function addAnswer(result) {
  const article = document.createElement('article');
  article.className = 'message assistant';
  const label = document.createElement('div');
  label.className = 'message-label';
  label.textContent = 'LANGGRAPH AGENT';

  const card = document.createElement('section');
  card.className = 'answer-card';
  const head = document.createElement('div');
  head.className = 'answer-head';
  head.innerHTML = '<span class="spark">✦</span><span>查询结果</span>';
  const body = document.createElement('div');
  body.className = 'answer-body';
  body.textContent = result.answer || '查询已完成。';
  card.append(head, body);

  const meta = document.createElement('div');
  meta.className = 'meta-row';
  const values = [
    ['数据表', (result.tables || []).join(', ') || '—'],
    ['返回行数', result.row_count ?? 0],
    ['SQL 修复', result.repair_attempts ?? 0],
  ];
  if (result.truncated) values.push(['结果', '已截断']);
  for (const [key, value] of values) {
    const chip = document.createElement('span');
    chip.className = 'meta-chip';
    const bold = document.createElement('b');
    bold.textContent = `${key}：`;
    chip.append(bold, document.createTextNode(String(value)));
    meta.append(chip);
  }
  card.append(meta);

  if (result.sql) {
    const details = document.createElement('details');
    details.className = 'details';
    const summary = document.createElement('summary');
    summary.textContent = '查看生成的 SQL';
    const code = document.createElement('pre');
    code.className = 'sql-block';
    code.textContent = result.sql;
    const copy = document.createElement('button');
    copy.className = 'copy-sql';
    copy.type = 'button';
    copy.textContent = '复制 SQL';
    copy.addEventListener('click', async () => {
      await navigator.clipboard.writeText(result.sql);
      copy.textContent = '已复制';
      setTimeout(() => { copy.textContent = '复制 SQL'; }, 1200);
    });
    details.append(summary, code, copy);
    card.append(details);
  }

  if (result.error) {
    const error = document.createElement('div');
    error.className = 'error-note';
    error.textContent = `处理提示：${result.error}`;
    card.append(error);
  }
  const caveats = (result.caveats || []).filter(Boolean);
  if (caveats.length) {
    const note = document.createElement('div');
    note.className = 'error-note';
    note.textContent = caveats.join('；');
    card.append(note);
  }

  article.append(label, card);
  messages.append(article);
  article.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

async function submitQuestion(question) {
  const cleaned = question.trim();
  if (!cleaned || sendButton.disabled) return;
  welcome.hidden = true;
  addMessage('user', '你', cleaned);
  textarea.value = '';
  textarea.style.height = 'auto';
  sendButton.disabled = true;
  const thinking = addThinking();

  try {
    const response = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: cleaned }),
    });
    const payload = await response.json();
    thinking.remove();
    if (!response.ok) {
      addMessage('assistant', '服务提示', payload.detail || '请求失败，请稍后重试。');
      return;
    }
    addAnswer(payload);
  } catch (error) {
    thinking.remove();
    addMessage('assistant', '连接错误', '无法连接到后端服务。请确认服务正在运行后重试。');
  } finally {
    sendButton.disabled = false;
    textarea.focus();
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  submitQuestion(textarea.value);
});

textarea.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

textarea.addEventListener('input', () => {
  textarea.style.height = 'auto';
  textarea.style.height = `${Math.min(textarea.scrollHeight, 130)}px`;
});

document.querySelectorAll('.example').forEach((button) => {
  button.addEventListener('click', () => submitQuestion(button.dataset.question || ''));
});

fetch('/api/health')
  .then((response) => response.json())
  .then((data) => { if (data.model) modelName.textContent = data.model; })
  .catch(() => { modelName.textContent = '后端未连接'; });

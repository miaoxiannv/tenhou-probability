const fileInput = document.getElementById('fileInput');
const uploadBtn = document.getElementById('uploadBtn');
const uploadStatus = document.getElementById('uploadStatus');
const columnsMeta = document.getElementById('columnsMeta');
const previewTable = document.getElementById('previewTable');

const chatLog = document.getElementById('chatLog');
const promptInput = document.getElementById('promptInput');
const sendBtn = document.getElementById('sendBtn');

const plotStatus = document.getElementById('plotStatus');
const plotImage = document.getElementById('plotImage');
const specOutput = document.getElementById('specOutput');
const codeOutput = document.getElementById('codeOutput');

let sessionId = '';
let hasData = false;

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function ensureSession() {
  if (sessionId) {
    return;
  }

  const res = await fetch('/api/session', { method: 'POST' });
  if (!res.ok) {
    throw new Error('创建会话失败');
  }

  const data = await res.json();
  sessionId = data.session_id;
}

function renderColumnsMeta(columns) {
  columnsMeta.innerHTML = '';
  for (const col of columns) {
    const chip = document.createElement('span');
    chip.className = 'meta-chip';
    chip.textContent = `${col.name} | ${col.dtype} | NA:${col.missing}`;
    columnsMeta.appendChild(chip);
  }
}

function renderPreviewRows(rows) {
  const thead = previewTable.querySelector('thead');
  const tbody = previewTable.querySelector('tbody');
  thead.innerHTML = '';
  tbody.innerHTML = '';

  if (!rows || rows.length === 0) {
    return;
  }

  const headers = Object.keys(rows[0]);

  const trHead = document.createElement('tr');
  for (const h of headers) {
    const th = document.createElement('th');
    th.textContent = h;
    trHead.appendChild(th);
  }
  thead.appendChild(trHead);

  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const h of headers) {
      const td = document.createElement('td');
      const value = row[h];
      td.textContent = value === null || value === undefined ? '' : String(value);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

async function uploadDataFile() {
  const file = fileInput.files?.[0];
  if (!file) {
    alert('请先选择 CSV/XLSX 文件');
    return;
  }

  try {
    uploadBtn.disabled = true;
    uploadStatus.textContent = '上传中...';

    await ensureSession();

    const form = new FormData();
    form.append('file', file);

    const res = await fetch(`/api/upload?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      body: form,
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || '上传失败');
    }

    renderColumnsMeta(data.columns || []);
    renderPreviewRows(data.preview_rows || []);

    hasData = true;
    sendBtn.disabled = false;
    uploadStatus.textContent = `已加载 ${data.filename}，${data.row_count} 行，${data.column_count} 列`;
    addMessage('assistant', '数据已加载。现在你可以用自然语言描述想要的图。');
  } catch (err) {
    uploadStatus.textContent = `上传失败：${err.message}`;
    addMessage('error', `上传失败：${err.message}`);
  } finally {
    uploadBtn.disabled = false;
  }
}

async function generatePlotFromPrompt() {
  const message = promptInput.value.trim();
  if (!message) {
    return;
  }

  if (!hasData) {
    alert('请先上传数据文件');
    return;
  }

  try {
    sendBtn.disabled = true;
    plotStatus.textContent = '模型思考并绘图中...';

    addMessage('user', message);

    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: sessionId,
        message,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || '绘图失败');
    }

    if (data.image_base64) {
      plotImage.src = `data:image/png;base64,${data.image_base64}`;
      plotImage.style.display = 'block';
    }

    specOutput.textContent = JSON.stringify(data.spec || {}, null, 2);
    codeOutput.textContent = data.python_code || '';

    const summary = data.used_fallback
      ? `${data.summary}（当前使用后备规则，建议优化提示词）`
      : data.summary;
    addMessage('assistant', summary);

    plotStatus.textContent = '已完成';
  } catch (err) {
    addMessage('error', `生成失败：${err.message}`);
    plotStatus.textContent = `失败：${err.message}`;
  } finally {
    sendBtn.disabled = false;
  }
}

uploadBtn.addEventListener('click', uploadDataFile);
sendBtn.addEventListener('click', generatePlotFromPrompt);

promptInput.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    generatePlotFromPrompt();
  }
});

addMessage('assistant', '欢迎使用。先在左侧上传 CSV/XLSX，再在这里输入自然语言绘图需求。');

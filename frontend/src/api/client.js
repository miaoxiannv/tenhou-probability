async function parseJson(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data?.detail || data?.message || '请求失败';
    throw new Error(detail);
  }
  return data;
}

const NETWORK_HINT =
  '无法连接后端服务（网络请求失败）。请先启动后端：cd /home/zhang/tenhou-probability && ./scripts/run_server.sh';

async function safeFetch(url, options) {
  try {
    return await fetch(url, options);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(NETWORK_HINT);
    }
    throw error;
  }
}

export async function createSession() {
  const res = await safeFetch('/api/session', { method: 'POST' });
  return parseJson(res);
}

export async function uploadDataset(sessionId, file) {
  const form = new FormData();
  form.append('file', file);

  const res = await safeFetch(`/api/upload?session_id=${encodeURIComponent(sessionId)}`, {
    method: 'POST',
    body: form
  });

  return parseJson(res);
}

export async function requestChat(sessionId, message, mode = 'auto') {
  const payload = { message };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  if (mode) {
    payload.mode = mode;
  }

  const res = await safeFetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  return parseJson(res);
}

export async function previewPlotSpec(sessionId, plotSpec) {
  const res = await safeFetch('/api/plot/spec', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      plot_spec: plotSpec
    })
  });
  return parseJson(res);
}

export async function requestStats(sessionId, plotSpec) {
  const res = await safeFetch('/api/stats', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      plot_spec: plotSpec
    })
  });
  return parseJson(res);
}

export async function exportPdfFile(sessionId, plotSpec, filename) {
  const res = await safeFetch('/api/export/pdf', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      plot_spec: plotSpec,
      filename
    })
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const detail = data?.detail || data?.message || 'PDF 导出失败';
    throw new Error(detail);
  }

  return res.blob();
}

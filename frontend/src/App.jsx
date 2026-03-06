import React, { useEffect, useMemo, useState } from 'react';
import {
  createSession,
  exportPdfFile,
  previewPlotSpec,
  requestChat,
  uploadDataset,
} from './api/client';
import { DataPane } from './components/DataPane';
import { ChatPane } from './components/ChatPane';
import { PlotPane } from './components/PlotPane';

const SETTINGS_KEY = 'viz-workspace-settings-v1';

function getInitialSettings() {
  if (typeof window === 'undefined') {
    return { theme: 'light', fontSize: 'medium' };
  }

  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) {
      return { theme: 'light', fontSize: 'medium' };
    }
    const parsed = JSON.parse(raw);
    return {
      theme: parsed.theme === 'dark' ? 'dark' : 'light',
      fontSize: ['small', 'medium', 'large'].includes(parsed.fontSize) ? parsed.fontSize : 'medium',
    };
  } catch {
    return { theme: 'light', fontSize: 'medium' };
  }
}

function buildPdfFilename() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `chart_${stamp}.pdf`;
}

function buildTableStatus(tableState) {
  if (!tableState?.filename) {
    return '未加载文件';
  }

  const rowCount = Number.isFinite(tableState.row_count) ? tableState.row_count : 0;
  const sourceRowCount = Number.isFinite(tableState.source_row_count)
    ? tableState.source_row_count
    : rowCount;
  const columnCount = Number.isFinite(tableState.column_count) ? tableState.column_count : 0;

  if (sourceRowCount !== rowCount) {
    return `当前数据：${tableState.filename}（视图 ${rowCount}/${sourceRowCount} 行，${columnCount} 列）`;
  }
  return `当前数据：${tableState.filename}，${rowCount} 行，${columnCount} 列`;
}

export function App() {
  const [sessionId, setSessionId] = useState('');
  const [file, setFile] = useState(null);
  const [uploadStatus, setUploadStatus] = useState('未上传文件');
  const [previewRows, setPreviewRows] = useState([]);
  const [tableColumns, setTableColumns] = useState([]);
  const [showSettings, setShowSettings] = useState(false);
  const [theme, setTheme] = useState(() => getInitialSettings().theme);
  const [fontSize, setFontSize] = useState(() => getInitialSettings().fontSize);

  const [messages, setMessages] = useState([
    { role: 'assistant', text: '可直接聊天，也可在聊天输入“加载文件 /home/zhang/xxx.csv”或“把第一行第二列的值改成2”。' },
  ]);
  const [prompt, setPrompt] = useState('');

  const [plotStatus, setPlotStatus] = useState('等待指令');
  const [plotSpec, setPlotSpec] = useState(null);
  const [plotPayload, setPlotPayload] = useState(null);
  const [stats, setStats] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [thinking, setThinking] = useState([]);

  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [editingSpec, setEditingSpec] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);

  const sendDisabled = useMemo(() => !prompt.trim(), [prompt]);
  const canDownloadPdf = Boolean(sessionId && plotSpec && !exportingPdf);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.fontSize = fontSize;

    window.localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({
        theme,
        fontSize,
      }),
    );
  }, [fontSize, theme]);

  const appendMessage = (role, text) => {
    setMessages((prev) => [...prev, { role, text }]);
  };

  const ensureSession = async () => {
    if (sessionId) {
      return sessionId;
    }

    const data = await createSession();
    setSessionId(data.session_id);
    return data.session_id;
  };

  const applyTableState = (tableState) => {
    if (!tableState) {
      return;
    }
    setPreviewRows(Array.isArray(tableState.preview_rows) ? tableState.preview_rows : []);
    const cols = Array.isArray(tableState.columns) ? tableState.columns.map((item) => item.name).filter(Boolean) : [];
    setTableColumns(cols);
    setUploadStatus(buildTableStatus(tableState));
  };

  const applyChatPayload = (data) => {
    if (data.table_state) {
      applyTableState(data.table_state);
    }
    setPlotSpec(data.plot_spec || null);
    setPlotPayload(data.plot_payload || null);
    setStats(data.stats || null);
    setWarnings(Array.isArray(data.warnings) ? data.warnings : []);
    setThinking(Array.isArray(data.thinking) ? data.thinking : []);
    setPlotStatus(data.summary || '已完成');
  };

  const handleUpload = async (selectedFile = null) => {
    const targetFile = selectedFile || file;
    if (!targetFile) {
      return;
    }

    try {
      setUploading(true);
      setUploadStatus('上传并解析中...');

      const sid = await ensureSession();
      const data = await uploadDataset(sid, targetFile);
      applyTableState(data);
      appendMessage('assistant', '数据已加载。现在可以直接发绘图或表格控制指令。');
    } catch (error) {
      setUploadStatus(`上传失败：${error.message}`);
      appendMessage('error', `上传失败：${error.message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleSelectFile = async (event) => {
    const selected = event.target.files?.[0] || null;
    setFile(selected);
    if (selected) {
      await handleUpload(selected);
    }
  };

  const handleSend = async () => {
    const text = prompt.trim();
    if (!text || sending) {
      return;
    }

    try {
      setSending(true);
      setPlotStatus('处理中...');
      appendMessage('user', text);
      setPrompt('');
      setWarnings([]);

      const sid = await ensureSession();
      const data = await requestChat(sid, text);
      if (data.session_id && data.session_id !== sid) {
        setSessionId(data.session_id);
      }

      applyChatPayload(data);
      appendMessage('assistant', data.summary || '已回复。');
    } catch (error) {
      setPlotStatus(`生成失败：${error.message}`);
      appendMessage('error', `生成失败：${error.message}`);
    } finally {
      setSending(false);
    }
  };

  const handleApplySpec = async (nextSpec) => {
    if (!sessionId) {
      appendMessage('error', '当前没有会话数据，无法应用参数。');
      return;
    }

    try {
      setEditingSpec(true);
      setPlotStatus('应用参数中...');
      const data = await previewPlotSpec(sessionId, nextSpec);
      applyChatPayload(data);
    } catch (error) {
      setPlotStatus(`参数应用失败：${error.message}`);
      appendMessage('error', `参数应用失败：${error.message}`);
    } finally {
      setEditingSpec(false);
    }
  };

  const handleDownloadPdf = async () => {
    if (!sessionId || !plotSpec) {
      appendMessage('error', '暂无可导出内容');
      return;
    }

    try {
      setExportingPdf(true);
      const blob = await exportPdfFile(sessionId, plotSpec, buildPdfFilename());
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = buildPdfFilename();
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      appendMessage('error', `PDF 导出失败：${error.message}`);
    } finally {
      setExportingPdf(false);
    }
  };

  return (
    <div className="app-root">
      <header className="app-header">
        <div>
          <h1>数据可视化工作台</h1>
          <p>Spec-first：后端返回结构化 PlotSpec，前端直接渲染图并可继续编辑参数。</p>
        </div>

        <button
          type="button"
          className="settings-trigger"
          aria-label="设置"
          onClick={() => setShowSettings(true)}
        >
          ⚙
        </button>
      </header>

      <main className="workspace">
        <DataPane
          file={file}
          onFileChange={handleSelectFile}
          uploadStatus={uploadStatus}
          tableColumns={tableColumns}
          previewRows={previewRows}
          loading={uploading}
        />

        <ChatPane
          messages={messages}
          prompt={prompt}
          onPromptChange={setPrompt}
          onSend={handleSend}
          sendDisabled={sendDisabled}
          sending={sending}
        />

        <PlotPane
          plotStatus={plotStatus}
          plotSpec={plotSpec}
          plotPayload={plotPayload}
          stats={stats}
          warnings={warnings}
          thinking={thinking}
          canDownloadPdf={canDownloadPdf}
          onDownloadPdf={handleDownloadPdf}
          onApplySpec={handleApplySpec}
          columnOptions={tableColumns}
          theme={theme}
          editing={editingSpec}
        />
      </main>

      {showSettings ? (
        <div className="settings-overlay" role="dialog" aria-modal="true">
          <div className="settings-modal">
            <div className="settings-head">
              <h2>设置</h2>
              <button type="button" className="plain-close" onClick={() => setShowSettings(false)}>
                关闭
              </button>
            </div>

            <div className="settings-section">
              <div className="settings-label">主题</div>
              <div className="settings-options">
                <label>
                  <input
                    type="radio"
                    name="theme"
                    value="light"
                    checked={theme === 'light'}
                    onChange={() => setTheme('light')}
                  />
                  浅色
                </label>
                <label>
                  <input
                    type="radio"
                    name="theme"
                    value="dark"
                    checked={theme === 'dark'}
                    onChange={() => setTheme('dark')}
                  />
                  深色
                </label>
              </div>
            </div>

            <div className="settings-section">
              <div className="settings-label">字号</div>
              <div className="settings-options">
                <label>
                  <input
                    type="radio"
                    name="font-size"
                    value="small"
                    checked={fontSize === 'small'}
                    onChange={() => setFontSize('small')}
                  />
                  小
                </label>
                <label>
                  <input
                    type="radio"
                    name="font-size"
                    value="medium"
                    checked={fontSize === 'medium'}
                    onChange={() => setFontSize('medium')}
                  />
                  中
                </label>
                <label>
                  <input
                    type="radio"
                    name="font-size"
                    value="large"
                    checked={fontSize === 'large'}
                    onChange={() => setFontSize('large')}
                  />
                  大
                </label>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

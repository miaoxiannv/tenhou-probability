import React, { useEffect, useMemo, useState } from 'react';
import {
  createSession,
  exportCsvFile,
  exportPdfFile,
  getSessionHistory,
  getSessionState,
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

function buildCsvFilename() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `table_${stamp}.csv`;
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
  const [hasTableData, setHasTableData] = useState(false);
  const [sessionState, setSessionState] = useState(null);
  const [historyItems, setHistoryItems] = useState([]);
  const [snapshotDraft, setSnapshotDraft] = useState('baseline');
  const [selectedSnapshot, setSelectedSnapshot] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [theme, setTheme] = useState(() => getInitialSettings().theme);
  const [fontSize, setFontSize] = useState(() => getInitialSettings().fontSize);

  const [messages, setMessages] = useState([
    { role: 'assistant', text: '可直接聊天，也可在聊天输入“加载文件 /home/zhang/xxx.csv”或“把第一行第二列的值改成2”。' },
  ]);
  const [prompt, setPrompt] = useState('');
  const [chatMode, setChatMode] = useState('auto');

  const [plotStatus, setPlotStatus] = useState('等待指令');
  const [plotSpec, setPlotSpec] = useState(null);
  const [plotPayload, setPlotPayload] = useState(null);
  const [stats, setStats] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [thinking, setThinking] = useState([]);

  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [tableActioning, setTableActioning] = useState(false);
  const [editingSpec, setEditingSpec] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [exportingCsv, setExportingCsv] = useState(false);

  const sendDisabled = useMemo(() => !prompt.trim(), [prompt]);
  const actionBusy = uploading || sending || tableActioning;
  const snapshotOptions = Array.isArray(sessionState?.snapshots) ? sessionState.snapshots : [];
  const canUndo = Boolean(hasTableData && Number(sessionState?.undo_count || 0) > 0 && !actionBusy);
  const canRedo = Boolean(hasTableData && Number(sessionState?.redo_count || 0) > 0 && !actionBusy);
  const canDownloadPdf = Boolean(sessionId && plotSpec && !exportingPdf);
  const canDownloadCsv = Boolean(sessionId && hasTableData && !exportingCsv);

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

  const refreshSessionMetadata = async (sid) => {
    if (!sid) {
      return;
    }
    try {
      const [stateData, historyData] = await Promise.all([
        getSessionState(sid),
        getSessionHistory(sid, 12),
      ]);
      setSessionState(stateData || null);
      setHistoryItems(Array.isArray(historyData?.items) ? historyData.items.slice().reverse() : []);
      if (Array.isArray(stateData?.snapshots) && !stateData.snapshots.includes(selectedSnapshot)) {
        setSelectedSnapshot('');
      }
    } catch {
      setSessionState(null);
      setHistoryItems([]);
    }
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
      setPreviewRows([]);
      setTableColumns([]);
      setHasTableData(false);
      setUploadStatus('未加载文件');
      return;
    }
    setPreviewRows(Array.isArray(tableState.preview_rows) ? tableState.preview_rows : []);
    const cols = Array.isArray(tableState.columns) ? tableState.columns.map((item) => item.name).filter(Boolean) : [];
    setTableColumns(cols);
    setHasTableData(true);
    setUploadStatus(buildTableStatus(tableState));
  };

  const applyChatPayload = (data) => {
    if ('table_state' in data) {
      applyTableState(data.table_state || null);
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
      await refreshSessionMetadata(sid);
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
      const data = await requestChat(sid, text, chatMode);
      const nextSessionId = data.session_id || sid;
      if (nextSessionId !== sid) {
        setSessionId(nextSessionId);
      }

      applyChatPayload(data);
      await refreshSessionMetadata(nextSessionId);
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
      await refreshSessionMetadata(sessionId);
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

  const handleDownloadCsv = async () => {
    if (!sessionId || !hasTableData) {
      appendMessage('error', '暂无可导出表格');
      return;
    }

    try {
      setExportingCsv(true);
      const blob = await exportCsvFile(sessionId, buildCsvFilename(), 'active');
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = buildCsvFilename();
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      appendMessage('error', `CSV 导出失败：${error.message}`);
    } finally {
      setExportingCsv(false);
    }
  };

  const runTableCommand = async (command) => {
    if (actionBusy || !command?.trim()) {
      return;
    }
    try {
      setTableActioning(true);
      const sid = await ensureSession();
      const data = await requestChat(sid, command, 'table');
      const nextSessionId = data.session_id || sid;
      if (nextSessionId !== sid) {
        setSessionId(nextSessionId);
      }
      applyChatPayload(data);
      await refreshSessionMetadata(nextSessionId);
      appendMessage('assistant', data.summary || '已执行表格操作。');
    } catch (error) {
      appendMessage('error', `表格操作失败：${error.message}`);
    } finally {
      setTableActioning(false);
    }
  };

  const handleUndo = async () => runTableCommand('撤销');

  const handleRedo = async () => runTableCommand('重做');

  const handleSaveSnapshot = async () => {
    const name = snapshotDraft.trim();
    if (!name) {
      return;
    }
    await runTableCommand(`保存快照 ${name}`);
    setSelectedSnapshot(name);
  };

  const handleLoadSnapshot = async () => {
    const name = selectedSnapshot.trim();
    if (!name) {
      return;
    }
    await runTableCommand(`加载快照 ${name}`);
  };

  return (
    <div className="app-root">
      <header className="app-header">
        <div>
          <h1>SheetPilot Studio</h1>
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
          actionBusy={actionBusy}
          canUndo={canUndo}
          canRedo={canRedo}
          onUndo={handleUndo}
          onRedo={handleRedo}
          snapshotDraft={snapshotDraft}
          onSnapshotDraftChange={setSnapshotDraft}
          selectedSnapshot={selectedSnapshot}
          onSelectedSnapshotChange={setSelectedSnapshot}
          onSaveSnapshot={handleSaveSnapshot}
          onLoadSnapshot={handleLoadSnapshot}
          snapshotOptions={snapshotOptions}
          historyItems={historyItems}
        />

        <ChatPane
          messages={messages}
          prompt={prompt}
          onPromptChange={setPrompt}
          mode={chatMode}
          onModeChange={setChatMode}
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
          canDownloadCsv={canDownloadCsv}
          onDownloadPdf={handleDownloadPdf}
          onDownloadCsv={handleDownloadCsv}
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

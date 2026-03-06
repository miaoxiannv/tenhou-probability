import React, { useEffect, useMemo, useState } from 'react';
import {
  createSession,
  exportCsvFile,
  exportPdfFile,
  exportPngFile,
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
const QUICK_PROMPTS = [
  '画一个散点图，x=group，y=value',
  '画折线图，按 day 展示 il6 趋势',
  '画柱状图，对比不同组的平均值',
  '画箱线图，比较 Group 的分布差异',
  '画热图，查看相关性',
  '筛选 group == A 后画图',
  '按 value 降序后画柱状图',
  '先做分组统计再画图',
  '把标题改成“实验结果总览”',
  '导出当前图并保留表格视图',
];

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

function buildTimestamp(prefix, ext) {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `${prefix}_${stamp}.${ext}`;
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
    return `${tableState.filename}（视图 ${rowCount}/${sourceRowCount} 行，${columnCount} 列）`;
  }
  return `${tableState.filename}（${rowCount} 行，${columnCount} 列）`;
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path
        d="M19.43 12.98a7.98 7.98 0 0 0 .06-.98 7.98 7.98 0 0 0-.06-.98l2.12-1.65a.5.5 0 0 0 .12-.64l-2-3.46a.5.5 0 0 0-.6-.22l-2.49 1a7.56 7.56 0 0 0-1.7-.98l-.38-2.65a.5.5 0 0 0-.49-.42h-4a.5.5 0 0 0-.49.42L8.73 5.07a7.56 7.56 0 0 0-1.7.98l-2.49-1a.5.5 0 0 0-.6.22l-2 3.46a.5.5 0 0 0 .12.64l2.12 1.65a7.98 7.98 0 0 0-.06.98c0 .33.02.66.06.98l-2.12 1.65a.5.5 0 0 0-.12.64l2 3.46a.5.5 0 0 0 .6.22l2.49-1c.52.4 1.09.73 1.7.98l.38 2.65a.5.5 0 0 0 .49.42h4a.5.5 0 0 0 .49-.42l.38-2.65c.61-.25 1.18-.58 1.7-.98l2.49 1a.5.5 0 0 0 .6-.22l2-3.46a.5.5 0 0 0-.12-.64l-2.12-1.65ZM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7Z"
        fill="currentColor"
      />
    </svg>
  );
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
  const [showDataPanel, setShowDataPanel] = useState(false);
  const [showDebugInfo, setShowDebugInfo] = useState(false);
  const [theme, setTheme] = useState(() => getInitialSettings().theme);
  const [fontSize, setFontSize] = useState(() => getInitialSettings().fontSize);

  const [messages, setMessages] = useState([
    { role: 'assistant', text: '上传数据后，直接描述你想要的图。我会先给出可用首图，再按你的指令微调。' },
  ]);
  const [prompt, setPrompt] = useState('');
  const [lastUserPrompt, setLastUserPrompt] = useState('');

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
  const [exportingPng, setExportingPng] = useState(false);

  const sendDisabled = useMemo(() => !prompt.trim(), [prompt]);
  const actionBusy = uploading || sending || tableActioning;
  const snapshotOptions = Array.isArray(sessionState?.snapshots) ? sessionState.snapshots : [];
  const canUndo = Boolean(hasTableData && Number(sessionState?.undo_count || 0) > 0 && !actionBusy);
  const canRedo = Boolean(hasTableData && Number(sessionState?.redo_count || 0) > 0 && !actionBusy);
  const canDownloadPdf = Boolean(sessionId && plotSpec && !exportingPdf);
  const canDownloadCsv = Boolean(sessionId && hasTableData && !exportingCsv);
  const canDownloadPng = Boolean(sessionId && plotSpec && !exportingPng);
  const canRetry = Boolean(lastUserPrompt && !sending);
  const datasetSummary = hasTableData ? uploadStatus : '未加载数据';

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
      appendMessage('assistant', '数据已加载。请直接描述目标图，我会先生成首图。');
    } catch (error) {
      setUploadStatus(`上传失败：${error.message}`);
      appendMessage('error', `上传失败：${error.message}。建议：检查文件格式是否为 CSV/XLSX，并确认列名不为空。`);
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

  const handleSend = async (overridePrompt = null) => {
    const text = (overridePrompt ?? prompt).trim();
    if (!text || sending) {
      return;
    }

    try {
      setSending(true);
      setPlotStatus('处理中...');
      appendMessage('user', text);
      setLastUserPrompt(text);
      if (!overridePrompt) {
        setPrompt('');
      }
      setWarnings([]);

      const sid = await ensureSession();
      const data = await requestChat(sid, text, 'auto');
      const nextSessionId = data.session_id || sid;
      if (nextSessionId !== sid) {
        setSessionId(nextSessionId);
      }

      applyChatPayload(data);
      await refreshSessionMetadata(nextSessionId);
      appendMessage('assistant', data.summary || '已回复。');
    } catch (error) {
      setPlotStatus(`生成失败：${error.message}`);
      appendMessage('error', `生成失败：${error.message}。建议：补充图类型、x/y 字段，或先输入“预览 20 行”确认列名。`);
    } finally {
      setSending(false);
    }
  };

  const handleRetry = async () => {
    if (!lastUserPrompt) {
      appendMessage('error', '没有可重试的上一次指令。');
      return;
    }
    await handleSend(lastUserPrompt);
  };

  const handleUseSuggestion = async (text) => {
    if (!text) {
      return;
    }
    await handleSend(text);
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
      appendMessage('error', `参数应用失败：${error.message}。建议：检查字段是否存在，或先重置为基础图类型。`);
    } finally {
      setEditingSpec(false);
    }
  };

  const handleDownloadPdf = async () => {
    if (!sessionId || !plotSpec) {
      appendMessage('error', '暂无可导出的图。建议先生成图后再导出。');
      return;
    }

    try {
      setExportingPdf(true);
      const filename = buildTimestamp('chart', 'pdf');
      const blob = await exportPdfFile(sessionId, plotSpec, filename);
      triggerBlobDownload(blob, filename);
    } catch (error) {
      appendMessage('error', `PDF 导出失败：${error.message}。建议：先切换为基础图类型后重试。`);
    } finally {
      setExportingPdf(false);
    }
  };

  const handleDownloadPng = async () => {
    if (!sessionId || !plotSpec) {
      appendMessage('error', '暂无可导出的图。建议先生成图后再导出。');
      return;
    }

    try {
      setExportingPng(true);
      const filename = buildTimestamp('chart', 'png');
      const blob = await exportPngFile(sessionId, plotSpec, filename);
      triggerBlobDownload(blob, filename);
    } catch (error) {
      appendMessage('error', `PNG 导出失败：${error.message}。建议：先切换为基础图类型后重试。`);
    } finally {
      setExportingPng(false);
    }
  };

  const handleDownloadCsv = async () => {
    if (!sessionId || !hasTableData) {
      appendMessage('error', '暂无可导出表格。建议先上传或生成表格视图。');
      return;
    }

    try {
      setExportingCsv(true);
      const filename = buildTimestamp('table', 'csv');
      const blob = await exportCsvFile(sessionId, filename, 'active');
      triggerBlobDownload(blob, filename);
    } catch (error) {
      appendMessage('error', `CSV 导出失败：${error.message}。建议：确认当前会话仍存在并重试。`);
    } finally {
      setExportingCsv(false);
    }
  };

  const handleExportSpec = () => {
    if (!plotSpec) {
      appendMessage('error', '暂无可导出的 spec。建议先生成图后导出。');
      return;
    }
    const blob = new Blob([JSON.stringify(plotSpec, null, 2)], { type: 'application/json' });
    triggerBlobDownload(blob, buildTimestamp('spec', 'json'));
  };

  const handleImportSpec = async (specData) => {
    if (!specData || typeof specData !== 'object') {
      appendMessage('error', 'spec 导入失败：JSON 内容无效。');
      return;
    }
    if (!sessionId) {
      appendMessage('error', 'spec 导入失败：请先上传数据并创建会话。');
      return;
    }
    await handleApplySpec(specData);
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
      appendMessage('error', `表格操作失败：${error.message}。建议：先确认列名和行号。`);
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
    <div className="app-root app-autoplot">
      <header className="app-header app-header-compact">
        <div className="header-copy">
          <h1>AutoPlot Studio</h1>
          <p>上传数据，描述需求，立即出图。</p>
        </div>

        <div className="top-actions">
          <label className="file-picker top-upload-btn">
            <input type="file" accept=".csv,.xlsx,.xls" onChange={handleSelectFile} />
            <span>{uploading ? '上传中...' : '上传数据'}</span>
          </label>
          <button
            type="button"
            className="ghost-btn"
            onClick={() => setShowDataPanel((prev) => !prev)}
            aria-label="切换数据面板"
          >
            {showDataPanel ? '隐藏数据面板' : '数据面板'}
          </button>
          <button
            type="button"
            className="ghost-btn"
            onClick={() => setShowDebugInfo((prev) => !prev)}
            aria-label="切换调试信息"
          >
            调试
          </button>
          <button
            type="button"
            className="settings-trigger"
            aria-label="设置"
            onClick={() => setShowSettings(true)}
          >
            <SettingsIcon />
          </button>
        </div>
      </header>

      <div className="context-strip">
        <span className="context-chip">数据集：{datasetSummary}</span>
        <span className="context-chip">模式：智能</span>
      </div>

      {showDebugInfo ? (
        <section className="debug-strip">
          <div>session: {sessionId || '未创建'}</div>
          <div>history: {Number(sessionState?.history_count || 0)}</div>
          <div>updated: {sessionState?.updated_at || 'n/a'}</div>
        </section>
      ) : null}

      <main className={`workspace ${showDataPanel ? 'workspace-with-data' : 'workspace-focus'}`}>
        {showDataPanel ? (
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
            hasTableData={hasTableData}
          />
        ) : null}

        <PlotPane
          plotStatus={plotStatus}
          plotSpec={plotSpec}
          plotPayload={plotPayload}
          stats={stats}
          warnings={warnings}
          thinking={thinking}
          canDownloadPdf={canDownloadPdf}
          canDownloadCsv={canDownloadCsv}
          canDownloadPng={canDownloadPng}
          onDownloadPdf={handleDownloadPdf}
          onDownloadCsv={handleDownloadCsv}
          onDownloadPng={handleDownloadPng}
          onApplySpec={handleApplySpec}
          onRetry={handleRetry}
          canRetry={canRetry}
          onExportSpec={handleExportSpec}
          onImportSpec={handleImportSpec}
          columnOptions={tableColumns}
          theme={theme}
          editing={editingSpec}
        />

        <ChatPane
          messages={messages}
          prompt={prompt}
          onPromptChange={setPrompt}
          mode="auto"
          onModeChange={() => {}}
          onSend={handleSend}
          sendDisabled={sendDisabled}
          sending={sending}
          placeholder="输入你的图表需求，例如：按 Group 对比 Expression，并标注显著性"
          suggestions={QUICK_PROMPTS}
          onUseSuggestion={handleUseSuggestion}
          showModeSelector={false}
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

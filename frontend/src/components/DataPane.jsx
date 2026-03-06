import React, { useMemo, useState } from 'react';
import Spreadsheet from 'react-spreadsheet';

export function DataPane({
  uploadStatus,
  tableColumns,
  previewRows,
  loading,
  actionBusy,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  snapshotDraft,
  onSnapshotDraftChange,
  selectedSnapshot,
  onSelectedSnapshotChange,
  onSaveSnapshot,
  onLoadSnapshot,
  snapshotOptions,
  historyItems,
  hasTableData,
}) {
  const [activeTab, setActiveTab] = useState('fields');

  const defaultHeaders = Array.from({ length: 8 }, (_, idx) => String.fromCharCode(65 + idx));
  const headers = previewRows.length
    ? (Array.isArray(tableColumns) && tableColumns.length ? tableColumns : Object.keys(previewRows[0] || {}))
    : defaultHeaders;
  const visibleRows = previewRows.length ? previewRows : Array.from({ length: 50 }, () => ({}));
  const rowLabels = visibleRows.map((_, index) => String(index + 1));
  const sheetData = visibleRows.map((row) =>
    headers.map((header) => ({
      value: row?.[header] ?? '',
      readOnly: true,
    })),
  );

  const fieldItems = useMemo(() => {
    if (Array.isArray(tableColumns) && tableColumns.length > 0) {
      return tableColumns;
    }
    return headers;
  }, [headers, tableColumns]);

  const hasSnapshots = Array.isArray(snapshotOptions) && snapshotOptions.length > 0;
  const hasHistory = Array.isArray(historyItems) && historyItems.length > 0;

  return (
    <section className="panel data-pane panel-enter">
      <div className="panel-head">
        <h2>数据资产</h2>
        <span className="panel-subtitle">字段预览与版本管理</span>
      </div>

      <div className="table-controls quick-toolbar">
        <button type="button" className="ghost-btn" disabled={!canUndo || actionBusy} onClick={onUndo}>
          撤销
        </button>
        <button type="button" className="ghost-btn" disabled={!canRedo || actionBusy} onClick={onRedo}>
          重做
        </button>
      </div>

      <div className="upload-status">{loading ? '上传并解析中...' : uploadStatus}</div>

      <div className="data-tabs" role="tablist" aria-label="数据面板标签">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'fields'}
          className={`tab-btn ${activeTab === 'fields' ? 'active' : ''}`}
          onClick={() => setActiveTab('fields')}
        >
          字段
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'snapshots'}
          className={`tab-btn ${activeTab === 'snapshots' ? 'active' : ''}`}
          onClick={() => setActiveTab('snapshots')}
        >
          版本
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'audit'}
          className={`tab-btn ${activeTab === 'audit' ? 'active' : ''}`}
          onClick={() => setActiveTab('audit')}
        >
          审计
        </button>
      </div>

      <div className="tab-panel">
        {activeTab === 'fields' ? (
          <div className="field-list">
            {fieldItems.map((item) => (
              <span key={`field-${item}`} className="field-chip">
                {item}
              </span>
            ))}
          </div>
        ) : null}
        {activeTab === 'snapshots' ? (
          <div className="snapshot-pane">
            <div className="table-controls version-toolbar">
              <input
                value={snapshotDraft}
                onChange={(event) => onSnapshotDraftChange?.(event.target.value)}
                placeholder="版本名，如 baseline"
                maxLength={40}
              />
              <button
                type="button"
                className="ghost-btn primary-btn"
                disabled={!snapshotDraft?.trim() || actionBusy}
                onClick={onSaveSnapshot}
              >
                保存版本
              </button>
              <select
                value={selectedSnapshot}
                onChange={(event) => onSelectedSnapshotChange?.(event.target.value)}
                aria-label="版本列表"
              >
                <option value="">选择版本</option>
                {(snapshotOptions || []).map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="ghost-btn"
                disabled={!selectedSnapshot || actionBusy}
                onClick={onLoadSnapshot}
              >
                回滚到版本
              </button>
            </div>

            {hasSnapshots ? (
              <div className="history-list">
                {snapshotOptions.map((item) => (
                  <div key={`snap-${item}`} className="history-item">
                    <div className="history-action">版本</div>
                    <div className="history-summary">{item}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="history-empty">暂无已保存版本。</div>
            )}
          </div>
        ) : null}
        {activeTab === 'audit' ? (
          hasHistory ? (
            <div className="history-list">
              {historyItems.map((item, idx) => (
                <div key={`hist-${idx}`} className="history-item">
                  <div className="history-action">{item.action || 'event'}</div>
                  <div className="history-summary">{item.summary || ''}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="history-empty">暂无操作记录。</div>
          )
        ) : null}
      </div>

      <details className="help-box" open={!hasTableData}>
        <summary>使用提示</summary>
        <div className="help-content">
          <div>加载本地文件：加载文件 /home/zhang/xxx.csv</div>
          <div>编辑单元格：把第一行第二列的值改成2 或 把 B1 改成 8</div>
          <div>图表控制：画图 type=line x=group y=value stats=on title=趋势图</div>
        </div>
      </details>

      <div className="table-shell">
        <Spreadsheet
          className="sheet-spreadsheet"
          data={sheetData}
          columnLabels={headers}
          rowLabels={rowLabels}
          onChange={() => {}}
        />
      </div>
    </section>
  );
}

import React from 'react';
import Spreadsheet from 'react-spreadsheet';

export function DataPane({
  file,
  onFileChange,
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
}) {
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

  return (
    <section className="panel data-pane panel-enter">
      <div className="panel-head">
        <h2>数据表</h2>
        <span className="panel-subtitle">常态可见</span>
      </div>

      <div className="upload-bar">
        <label className="file-picker">
          <input type="file" accept=".csv,.xlsx,.xls" onChange={onFileChange} />
          <span>{file ? file.name : '选择文件'}</span>
        </label>
      </div>

      <div className="table-controls">
        <button type="button" className="ghost-btn" disabled={!canUndo || actionBusy} onClick={onUndo}>
          撤销
        </button>
        <button type="button" className="ghost-btn" disabled={!canRedo || actionBusy} onClick={onRedo}>
          重做
        </button>
        <input
          value={snapshotDraft}
          onChange={(event) => onSnapshotDraftChange?.(event.target.value)}
          placeholder="快照名，如 baseline"
          maxLength={40}
        />
        <button
          type="button"
          className="ghost-btn"
          disabled={!snapshotDraft?.trim() || actionBusy}
          onClick={onSaveSnapshot}
        >
          保存快照
        </button>
      </div>

      <div className="table-controls">
        <select
          value={selectedSnapshot}
          onChange={(event) => onSelectedSnapshotChange?.(event.target.value)}
          aria-label="快照列表"
        >
          <option value="">选择快照</option>
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
          加载快照
        </button>
      </div>

      <div className="upload-status">
        {loading ? '上传并解析中...' : uploadStatus}
        <br />
        可在聊天中直接输入：加载文件 /home/zhang/xxx.csv
        <br />
        也可输入：把第一行第二列的值改成2 / 把 B1 改成 8
        <br />
        可控画图：画图 type=line x=group y=value stats=on title=趋势图
      </div>

      <div className="table-shell">
        <Spreadsheet
          className="sheet-spreadsheet"
          data={sheetData}
          columnLabels={headers}
          rowLabels={rowLabels}
          onChange={() => {}}
        />
      </div>

      <div className="history-panel">
        <div className="history-title">最近操作</div>
        {(historyItems || []).length ? (
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
        )}
      </div>
    </section>
  );
}

import React from 'react';
import Spreadsheet from 'react-spreadsheet';

export function DataPane({
  file,
  onFileChange,
  uploadStatus,
  tableColumns,
  previewRows,
  loading
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
    </section>
  );
}

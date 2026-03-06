import React from 'react';

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
      </div>

      <div className="table-shell">
        <table className="sheet-table">
          <thead>
            <tr>
              <th className="index-col">#</th>
              {headers.map((header) => (
                <th key={header}>{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                <td className="index-col">{rowIndex + 1}</td>
                {headers.map((header) => {
                  const value = row[header];
                  return (
                    <td key={`cell-${rowIndex}-${header}`} title={value === null ? '' : String(value)}>
                      {value === null ? '' : String(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

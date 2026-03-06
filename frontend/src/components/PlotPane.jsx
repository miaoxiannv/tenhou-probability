import React, { useEffect, useMemo, useRef, useState } from 'react';
import { PlotCanvas } from './PlotCanvas';

function formatStats(stats) {
  if (!stats || typeof stats.p_value !== 'number') {
    return '当前请求未触发可计算的统计检验。';
  }
  const pText = stats.p_value < 0.0001 ? 'p < 1e-4' : `p=${stats.p_value.toPrecision(4)}`;
  const stars = stats.significance_stars || 'ns';
  const effectMetric = stats.effect_metric || 'effect';
  const effectValue = typeof stats.effect_size === 'number' ? stats.effect_size.toFixed(3) : 'NA';
  return `${stats.method} · ${pText} · ${stars} · ${effectMetric}=${effectValue}`;
}

function baseLayer(draft) {
  return {
    mark: draft.chart_type === 'box' ? 'boxplot' : draft.chart_type === 'composed' ? 'scatter' : draft.chart_type,
    encoding: {
      x: draft.x || null,
      y: draft.y || null,
      hue: draft.hue || null,
    },
    jitter: false,
    alpha: 0.7,
    box_width: null,
    y_axis: 'left',
    ci: false,
  };
}

function toDraftSpec(spec) {
  if (!spec) {
    return {
      chart_type: 'scatter',
      data_ref: 'active_dataset',
      x: '',
      y: '',
      hue: '',
      palette: '',
      title: '',
      agg: '',
      bins: '',
      filters: [],
      facetField: '',
      facetColumns: 3,
      statsOverlayEnabled: false,
      layers: [],
    };
  }

  const encoding = spec.encoding || {};
  const layers = Array.isArray(spec.layers) ? spec.layers : [];

  return {
    chart_type: spec.chart_type || 'scatter',
    data_ref: spec.data_ref || 'active_dataset',
    x: spec.x || encoding.x || '',
    y: spec.y || encoding.y || '',
    hue: spec.hue || encoding.color || encoding.hue || '',
    palette: spec.palette || spec.style?.palette || '',
    title: spec.title || spec.style?.title || '',
    agg: spec.agg || '',
    bins: spec.bins || '',
    filters: Array.isArray(spec.filters) ? spec.filters : [],
    facetField: spec.facet?.field || '',
    facetColumns: spec.facet?.columns || 3,
    statsOverlayEnabled: Boolean(spec.stats_overlay?.enabled),
    layers,
  };
}

function normalizeLayer(layer, draft) {
  const mark = layer.mark || 'scatter';
  const encoding = layer.encoding || {};
  const x = encoding.x || draft.x || null;
  const y = encoding.y || draft.y || null;
  const hue = encoding.hue || encoding.color || draft.hue || null;
  return {
    mark,
    encoding: {
      x,
      y,
      hue,
      color: hue,
    },
    jitter: Boolean(layer.jitter),
    alpha: layer.alpha === '' || layer.alpha === null || layer.alpha === undefined ? null : Number(layer.alpha),
    box_width: layer.box_width === '' || layer.box_width === null || layer.box_width === undefined ? null : Number(layer.box_width),
    y_axis: layer.y_axis === 'right' ? 'right' : 'left',
    ci: Boolean(layer.ci),
    fit: layer.fit || null,
    name: layer.name || null,
  };
}

export function PlotPane({
  plotStatus,
  plotSpec,
  plotPayload,
  stats,
  warnings,
  thinking,
  canDownloadPdf,
  canDownloadCsv,
  canDownloadPng,
  onDownloadPdf,
  onDownloadCsv,
  onDownloadPng,
  onApplySpec,
  onRetry,
  canRetry,
  onExportSpec,
  onImportSpec,
  columnOptions,
  theme,
  editing,
}) {
  const [draft, setDraft] = useState(() => toDraftSpec(plotSpec));
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const importInputRef = useRef(null);
  const chartTypes = ['scatter', 'line', 'bar', 'hist', 'box', 'violin', 'heatmap', 'composed'];
  const aggOptions = ['', 'mean', 'median', 'sum', 'count'];
  const layerMarkOptions = ['scatter', 'line', 'bar', 'hist', 'boxplot', 'violin', 'regression'];

  useEffect(() => {
    setDraft(toDraftSpec(plotSpec));
  }, [plotSpec]);

  useEffect(() => {
    if (warnings?.length) {
      setDiagnosticsOpen(true);
    }
  }, [warnings]);

  const submitDisabled = useMemo(() => editing || !draft.chart_type, [draft.chart_type, editing]);
  const warningSummary = Array.isArray(warnings) && warnings.length ? warnings[0] : '';

  const updateLayer = (idx, updater) => {
    setDraft((prev) => {
      const next = [...prev.layers];
      const current = { ...(next[idx] || {}) };
      next[idx] = typeof updater === 'function' ? updater(current) : current;
      return { ...prev, layers: next };
    });
  };

  const handleAddLayer = () => {
    setDraft((prev) => ({
      ...prev,
      chart_type: 'composed',
      layers: [...prev.layers, baseLayer(prev)],
    }));
  };

  const handleApply = () => {
    const normalizedLayers = (draft.layers || [])
      .map((layer) => normalizeLayer(layer, draft))
      .filter((layer) => layer.mark);

    const nextSpec = {
      chart_type: draft.chart_type,
      data_ref: draft.data_ref || 'active_dataset',
      x: draft.x || null,
      y: draft.y || null,
      hue: draft.hue || null,
      palette: draft.palette || null,
      title: draft.title || null,
      agg: draft.agg || null,
      bins: draft.bins ? Number(draft.bins) : null,
      filters: Array.isArray(draft.filters) ? draft.filters : [],
      encoding: {
        x: draft.x || null,
        y: draft.y || null,
        color: draft.hue || null,
      },
      layers: normalizedLayers,
      facet: draft.facetField
        ? { field: draft.facetField, columns: Number(draft.facetColumns) || 3 }
        : null,
      stats_overlay: {
        enabled: Boolean(draft.statsOverlayEnabled),
        method: 'auto',
      },
      style: {
        theme,
        title: draft.title || null,
      },
    };

    if (nextSpec.chart_type !== 'composed' && normalizedLayers.length <= 1) {
      nextSpec.layers = [];
    }

    onApplySpec(nextSpec);
  };

  const handleImportSpecFile = async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      const rawText = await file.text();
      const parsed = JSON.parse(rawText);
      await onImportSpec?.(parsed);
      setAdvancedOpen(false);
    } catch {
      // Let App surface the canonical error message.
      await onImportSpec?.(null);
    } finally {
      event.target.value = '';
    }
  };

  return (
    <section className="panel plot-pane panel-enter panel-enter-delay-2">
      <div className="panel-head">
        <h2>图表画布</h2>
        <div className="plot-actions">
          <button type="button" className="ghost-btn" disabled={!canRetry} onClick={onRetry} title="使用上一次指令重试">
            重试
          </button>
          <button type="button" className="ghost-btn" onClick={() => setAdvancedOpen(true)}>
            高级设置
          </button>
          <details className="export-menu">
            <summary className="ghost-btn" aria-label="导出">
              导出
            </summary>
            <div className="export-menu-list">
              <button type="button" className="ghost-btn" disabled={!canDownloadPng} onClick={onDownloadPng}>
                导出 PNG
              </button>
              <button type="button" className="ghost-btn" disabled={!canDownloadPdf} onClick={onDownloadPdf}>
                导出 PDF
              </button>
              <button type="button" className="ghost-btn" disabled={!canDownloadCsv} onClick={onDownloadCsv}>
                导出 CSV
              </button>
            </div>
          </details>
        </div>
      </div>

      <div className="plot-status">{plotStatus}</div>

      <div className="plot-canvas">
        {plotPayload ? (
          <PlotCanvas payload={plotPayload} spec={plotSpec} theme={theme} />
        ) : (
          <div className="plot-placeholder">上传数据并描述图表需求，系统会先给出可用首图。</div>
        )}
      </div>

      <div className="plot-metrics">
        <div className="metric-box">
          <div className="metric-title">统计摘要</div>
          <div className="metric-note">{formatStats(stats)}</div>
        </div>
      </div>

      {warningSummary ? (
        <details className="warning-box">
          <summary>{warningSummary}</summary>
          {warnings.map((item, idx) => (
            <div key={`warn-${idx}`}>{item}</div>
          ))}
        </details>
      ) : null}

      {diagnosticsOpen || (Array.isArray(warnings) && warnings.length > 0) ? (
        <details className="thinking-box" open={diagnosticsOpen}>
          <summary>查看详情</summary>
          {thinking?.length ? (
            <ol className="thinking-list">
              {thinking.map((step, idx) => (
                <li key={`step-${idx}`}>{step}</li>
              ))}
            </ol>
          ) : (
            <div className="thinking-empty">暂无可展开细节。</div>
          )}
        </details>
      ) : null}

      {advancedOpen ? (
        <div className="drawer-mask" onClick={() => setAdvancedOpen(false)}>
          <aside className="advanced-drawer" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-head">
              <div className="drawer-title">高级参数</div>
              <div className="drawer-actions">
                <button type="button" className="ghost-btn" onClick={onExportSpec}>
                  导出 spec.json
                </button>
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={() => importInputRef.current?.click()}
                >
                  导入 spec.json
                </button>
                <button type="button" className="ghost-btn" onClick={() => setAdvancedOpen(false)}>
                  关闭
                </button>
              </div>
            </div>
            <input
              ref={importInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden-file-input"
              onChange={handleImportSpecFile}
            />

            <details className="spec-editor" open>
              <summary>参数编辑（含高级图层）</summary>
              <div className="editor-grid">
                <label>
                  类型
                  <select
                    value={draft.chart_type}
                    onChange={(event) => {
                      const chartType = event.target.value;
                      setDraft((prev) => ({
                        ...prev,
                        chart_type: chartType,
                        layers: chartType === 'composed' && prev.layers.length === 0 ? [baseLayer(prev)] : prev.layers,
                      }));
                    }}
                  >
                    {chartTypes.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  X
                  <select value={draft.x} onChange={(event) => setDraft((prev) => ({ ...prev, x: event.target.value }))}>
                    <option value="">(none)</option>
                    {columnOptions.map((item) => (
                      <option key={`x-${item}`} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Y
                  <select value={draft.y} onChange={(event) => setDraft((prev) => ({ ...prev, y: event.target.value }))}>
                    <option value="">(none)</option>
                    {columnOptions.map((item) => (
                      <option key={`y-${item}`} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Hue
                  <select value={draft.hue} onChange={(event) => setDraft((prev) => ({ ...prev, hue: event.target.value }))}>
                    <option value="">(none)</option>
                    {columnOptions.map((item) => (
                      <option key={`h-${item}`} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  聚合
                  <select value={draft.agg} onChange={(event) => setDraft((prev) => ({ ...prev, agg: event.target.value }))}>
                    {aggOptions.map((item) => (
                      <option key={`agg-${item || 'none'}`} value={item}>
                        {item || '(none)'}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  调色板
                  <input
                    value={draft.palette}
                    onChange={(event) => setDraft((prev) => ({ ...prev, palette: event.target.value }))}
                    placeholder="如 Blues / viridis"
                  />
                </label>
              </div>

              <div className="editor-row editor-row-wide">
                <label>
                  标题
                  <input
                    value={draft.title}
                    onChange={(event) => setDraft((prev) => ({ ...prev, title: event.target.value }))}
                    placeholder="可选"
                  />
                </label>
                <label>
                  bins
                  <input
                    value={draft.bins}
                    onChange={(event) => setDraft((prev) => ({ ...prev, bins: event.target.value }))}
                    placeholder="hist 可选"
                  />
                </label>
                <label>
                  facet 字段
                  <select value={draft.facetField} onChange={(event) => setDraft((prev) => ({ ...prev, facetField: event.target.value }))}>
                    <option value="">(none)</option>
                    {columnOptions.map((item) => (
                      <option key={`facet-${item}`} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  facet 列数
                  <input
                    value={draft.facetColumns}
                    onChange={(event) => setDraft((prev) => ({ ...prev, facetColumns: event.target.value }))}
                    placeholder="3"
                  />
                </label>
                <label className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={draft.statsOverlayEnabled}
                    onChange={(event) => setDraft((prev) => ({ ...prev, statsOverlayEnabled: event.target.checked }))}
                  />
                  启用统计标注
                </label>
                <button type="button" className="ghost-btn" disabled={submitDisabled} onClick={handleApply}>
                  {editing ? '应用中...' : '应用参数'}
                </button>
              </div>

              <div className="layer-editor">
                <div className="layer-head">
                  <strong>图层（layers）</strong>
                  <button type="button" className="ghost-btn" onClick={handleAddLayer}>
                    添加图层
                  </button>
                </div>

                {(draft.layers || []).length ? (
                  <div className="layer-list">
                    {draft.layers.map((layer, idx) => {
                      const encoding = layer.encoding || {};
                      return (
                        <div key={`layer-${idx}`} className="layer-card">
                          <div className="layer-title">Layer {idx + 1}</div>
                          <div className="layer-grid">
                            <label>
                              mark
                              <select
                                value={layer.mark || 'scatter'}
                                onChange={(event) => updateLayer(idx, (current) => ({ ...current, mark: event.target.value }))}
                              >
                                {layerMarkOptions.map((mark) => (
                                  <option key={`${idx}-${mark}`} value={mark}>
                                    {mark}
                                  </option>
                                ))}
                              </select>
                            </label>

                            <label>
                              x
                              <select
                                value={encoding.x || ''}
                                onChange={(event) =>
                                  updateLayer(idx, (current) => ({
                                    ...current,
                                    encoding: { ...(current.encoding || {}), x: event.target.value || null },
                                  }))
                                }
                              >
                                <option value="">(none)</option>
                                {columnOptions.map((item) => (
                                  <option key={`${idx}-lx-${item}`} value={item}>
                                    {item}
                                  </option>
                                ))}
                              </select>
                            </label>

                            <label>
                              y
                              <select
                                value={encoding.y || ''}
                                onChange={(event) =>
                                  updateLayer(idx, (current) => ({
                                    ...current,
                                    encoding: { ...(current.encoding || {}), y: event.target.value || null },
                                  }))
                                }
                              >
                                <option value="">(none)</option>
                                {columnOptions.map((item) => (
                                  <option key={`${idx}-ly-${item}`} value={item}>
                                    {item}
                                  </option>
                                ))}
                              </select>
                            </label>

                            <label>
                              hue
                              <select
                                value={encoding.hue || encoding.color || ''}
                                onChange={(event) =>
                                  updateLayer(idx, (current) => ({
                                    ...current,
                                    encoding: {
                                      ...(current.encoding || {}),
                                      hue: event.target.value || null,
                                      color: event.target.value || null,
                                    },
                                  }))
                                }
                              >
                                <option value="">(none)</option>
                                {columnOptions.map((item) => (
                                  <option key={`${idx}-lh-${item}`} value={item}>
                                    {item}
                                  </option>
                                ))}
                              </select>
                            </label>

                            <label>
                              alpha
                              <input
                                value={layer.alpha ?? ''}
                                onChange={(event) => updateLayer(idx, (current) => ({ ...current, alpha: event.target.value }))}
                                placeholder="0~1"
                              />
                            </label>

                            <label>
                              box width
                              <input
                                value={layer.box_width ?? ''}
                                onChange={(event) => updateLayer(idx, (current) => ({ ...current, box_width: event.target.value }))}
                                placeholder="0.05~1"
                              />
                            </label>

                            <label>
                              y axis
                              <select
                                value={layer.y_axis || 'left'}
                                onChange={(event) => updateLayer(idx, (current) => ({ ...current, y_axis: event.target.value }))}
                              >
                                <option value="left">left</option>
                                <option value="right">right</option>
                              </select>
                            </label>

                            <label className="checkbox-line">
                              <input
                                type="checkbox"
                                checked={Boolean(layer.jitter)}
                                onChange={(event) => updateLayer(idx, (current) => ({ ...current, jitter: event.target.checked }))}
                              />
                              jitter
                            </label>

                            <label className="checkbox-line">
                              <input
                                type="checkbox"
                                checked={Boolean(layer.ci)}
                                onChange={(event) => updateLayer(idx, (current) => ({ ...current, ci: event.target.checked }))}
                              />
                              CI
                            </label>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="thinking-empty">当前无图层。点击“添加图层”可编辑高级组合图。</div>
                )}
              </div>
            </details>
          </aside>
        </div>
      ) : null}
    </section>
  );
}

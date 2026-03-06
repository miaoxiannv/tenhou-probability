import React, { useEffect, useMemo, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';

function safeNumber(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function groupRecords(records, hueKey) {
  if (!hueKey) {
    return [{ name: '', rows: records }];
  }
  const map = new Map();
  records.forEach((row) => {
    const key = row[hueKey] === null || row[hueKey] === undefined ? 'NA' : String(row[hueKey]);
    if (!map.has(key)) {
      map.set(key, []);
    }
    map.get(key).push(row);
  });
  return Array.from(map.entries()).map(([name, rows]) => ({ name, rows }));
}

function withNumericJitter(values, enabled) {
  if (!enabled || !Array.isArray(values) || !values.length) {
    return values;
  }
  const nums = values.map((item) => Number(item));
  if (nums.some((item) => !Number.isFinite(item))) {
    return values;
  }

  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = Math.max(max - min, 1);
  return nums.map((value, idx) => value + ((idx % 13) - 6) * span * 0.0045);
}

function tracesFromLegacyPayload(payload) {
  if (!payload) {
    return [];
  }

  if (payload.chart_type === 'heatmap') {
    return [
      {
        type: 'heatmap',
        x: payload.x_labels || [],
        y: payload.y_labels || [],
        z: payload.z || [],
        colorscale: 'RdBu',
        zmid: 0,
      },
    ];
  }

  const records = Array.isArray(payload.records) ? payload.records : [];
  const groups = groupRecords(records, payload.hue);
  const xKey = payload.x;
  const yKey = payload.y;

  if (!xKey && payload.chart_type !== 'hist') {
    return [];
  }

  if (payload.chart_type === 'hist') {
    return groups.map((group) => ({
      type: 'histogram',
      name: group.name,
      x: group.rows.map((row) => row[xKey]),
      opacity: 0.75,
    }));
  }

  if (payload.chart_type === 'box') {
    return groups.map((group) => ({
      type: 'box',
      name: group.name || 'all',
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
      boxpoints: false,
    }));
  }

  if (payload.chart_type === 'violin') {
    return groups.map((group) => ({
      type: 'violin',
      name: group.name || 'all',
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
      points: false,
    }));
  }

  if (payload.chart_type === 'line') {
    return groups.map((group) => ({
      type: 'scatter',
      mode: 'lines+markers',
      name: group.name,
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
    }));
  }

  if (payload.chart_type === 'bar') {
    return groups.map((group) => ({
      type: 'bar',
      name: group.name,
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
    }));
  }

  return groups.map((group) => ({
    type: 'scatter',
    mode: 'markers',
    name: group.name,
    x: group.rows.map((row) => row[xKey]),
    y: group.rows.map((row) => safeNumber(row[yKey])),
  }));
}

function tracesFromLayer(layer) {
  const mark = layer?.mark;
  if (!mark) {
    return [];
  }

  const encoding = layer.encoding || {};
  const xKey = encoding.x;
  const yKey = encoding.y;
  const hueKey = encoding.hue;
  const alpha = typeof layer.alpha === 'number' ? layer.alpha : 0.78;

  if (mark === 'regression') {
    const lines = Array.isArray(layer.lines) ? layer.lines : [];
    const traces = [];
    lines.forEach((line, idx) => {
      const lineName = line.name || layer.name || `fit-${idx + 1}`;
      traces.push({
        type: 'scatter',
        mode: 'lines',
        name: lineName,
        x: line.x || [],
        y: line.y || [],
        line: { width: 2.2 },
        yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
      });

      if (Array.isArray(line.ci_upper) && Array.isArray(line.ci_lower) && line.ci_upper.length && line.ci_lower.length) {
        traces.push({
          type: 'scatter',
          mode: 'lines',
          name: `${lineName} CI`,
          x: [...(line.x || []), ...(line.x || []).slice().reverse()],
          y: [...line.ci_upper, ...line.ci_lower.slice().reverse()],
          fill: 'toself',
          fillcolor: 'rgba(37,99,235,0.14)',
          line: { color: 'rgba(0,0,0,0)' },
          hoverinfo: 'skip',
          showlegend: false,
          yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
        });
      }
    });
    return traces;
  }

  const records = Array.isArray(layer.records) ? layer.records : [];
  const grouped = groupRecords(records, hueKey);

  if (mark === 'hist') {
    return grouped.map((group) => ({
      type: 'histogram',
      name: group.name || layer.name || 'hist',
      x: group.rows.map((row) => row[xKey]),
      opacity: alpha,
      yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
    }));
  }

  if (mark === 'boxplot') {
    return grouped.map((group) => ({
      type: 'box',
      name: group.name || layer.name || 'box',
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
      boxpoints: layer.jitter ? 'all' : false,
      jitter: layer.jitter ? 0.45 : 0,
      pointpos: layer.jitter ? 0 : undefined,
      width: typeof layer.box_width === 'number' ? layer.box_width : undefined,
      opacity: alpha,
      yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
    }));
  }

  if (mark === 'violin') {
    return grouped.map((group) => ({
      type: 'violin',
      name: group.name || layer.name || 'violin',
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
      points: layer.jitter ? 'all' : false,
      jitter: layer.jitter ? 0.42 : 0,
      opacity: alpha,
      yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
    }));
  }

  if (mark === 'bar') {
    return grouped.map((group) => ({
      type: 'bar',
      name: group.name || layer.name || 'bar',
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
      opacity: alpha,
      yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
    }));
  }

  if (mark === 'line') {
    return grouped.map((group) => ({
      type: 'scatter',
      mode: 'lines+markers',
      name: group.name || layer.name || 'line',
      x: group.rows.map((row) => row[xKey]),
      y: group.rows.map((row) => safeNumber(row[yKey])),
      opacity: alpha,
      yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
    }));
  }

  return grouped.map((group) => ({
    type: 'scatter',
    mode: 'markers',
    name: group.name || layer.name || 'scatter',
    x: withNumericJitter(group.rows.map((row) => row[xKey]), layer.jitter),
    y: group.rows.map((row) => safeNumber(row[yKey])),
    marker: {
      opacity: alpha,
      size: 7,
    },
    yaxis: layer.y_axis === 'right' ? 'y2' : 'y',
  }));
}

function buildComposedTraces(payload, facetChunk = null) {
  const sourceLayers = facetChunk?.layers || payload.layers || [];
  const traces = [];
  sourceLayers.forEach((layer) => {
    traces.push(...tracesFromLayer(layer));
  });
  return traces;
}

function buildLayout({ payload, spec, theme, titleSuffix = '' }) {
  const dark = theme === 'dark';
  const titleRaw = spec?.title || spec?.style?.title || (spec?.chart_type ? `${spec.chart_type} plot` : '');
  const title = titleSuffix ? `${titleRaw} · ${titleSuffix}` : titleRaw;

  const hasRightAxis = (payload.layers || []).some((layer) => layer?.y_axis === 'right');
  const rightLayer = (payload.layers || []).find((layer) => layer?.y_axis === 'right');

  const annotations = [];
  if (payload.stats_overlay?.enabled && payload.stats_overlay?.label) {
    annotations.push({
      x: 0,
      y: 1.08,
      xref: 'paper',
      yref: 'paper',
      xanchor: 'left',
      yanchor: 'bottom',
      align: 'left',
      text: payload.stats_overlay.label,
      showarrow: false,
      font: { size: 12, color: dark ? '#c8d3e8' : '#334155' },
    });
  }

  const layout = {
    title: { text: title || '' },
    margin: { l: 52, r: hasRightAxis ? 58 : 18, t: 54, b: 52 },
    paper_bgcolor: dark ? '#171b23' : '#ffffff',
    plot_bgcolor: dark ? '#171b23' : '#ffffff',
    font: { color: dark ? '#eceff4' : '#101828', size: 13 },
    xaxis: {
      title: payload.x || payload.encoding?.x || '',
      gridcolor: dark ? '#2a3240' : '#e5e7eb',
      zerolinecolor: dark ? '#2a3240' : '#e5e7eb',
    },
    yaxis: {
      title: payload.y || payload.encoding?.y || '',
      gridcolor: dark ? '#2a3240' : '#e5e7eb',
      zerolinecolor: dark ? '#2a3240' : '#e5e7eb',
    },
    barmode: 'group',
    violinmode: 'overlay',
    boxmode: 'group',
    showlegend: true,
    annotations,
  };

  if (hasRightAxis) {
    layout.yaxis2 = {
      title: rightLayer?.encoding?.y || 'secondary',
      overlaying: 'y',
      side: 'right',
      gridcolor: 'rgba(0,0,0,0)',
      zerolinecolor: dark ? '#2a3240' : '#e5e7eb',
    };
  }

  return layout;
}

function SinglePlot({ payload, spec, theme }) {
  const ref = useRef(null);

  const traces = useMemo(() => {
    if (!payload) {
      return [];
    }
    if (payload.chart_type === 'heatmap') {
      return tracesFromLegacyPayload(payload);
    }
    if (Array.isArray(payload.layers) && payload.layers.length) {
      return buildComposedTraces(payload);
    }
    return tracesFromLegacyPayload(payload);
  }, [payload]);

  useEffect(() => {
    const node = ref.current;
    if (!node || !payload) {
      return undefined;
    }

    const layout = buildLayout({ payload, spec, theme });
    const config = {
      displayModeBar: false,
      responsive: true,
    };

    Plotly.react(node, traces, layout, config);
    return () => {
      Plotly.purge(node);
    };
  }, [payload, traces, spec, theme]);

  return <div ref={ref} className="plotly-root" />;
}

function FacetPlot({ payload, spec, theme, facetChunk }) {
  const ref = useRef(null);
  const traces = useMemo(() => buildComposedTraces(payload, facetChunk), [payload, facetChunk]);

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return undefined;
    }

    const facetPayload = {
      ...payload,
      layers: facetChunk.layers || [],
    };
    const layout = buildLayout({ payload: facetPayload, spec, theme, titleSuffix: `${payload.facet?.field || 'facet'}=${facetChunk.key}` });

    Plotly.react(
      node,
      traces,
      {
        ...layout,
        margin: { ...layout.margin, t: 56 },
      },
      { displayModeBar: false, responsive: true },
    );

    return () => {
      Plotly.purge(node);
    };
  }, [payload, spec, theme, facetChunk, traces]);

  return <div className="plotly-root facet-item" ref={ref} />;
}

export function PlotCanvas({ payload, spec, theme }) {
  const facets = Array.isArray(payload?.facets) ? payload.facets : [];
  const facetColumns = payload?.facet?.columns || 3;

  if (facets.length > 1) {
    return (
      <div className="facet-grid" style={{ gridTemplateColumns: `repeat(${Math.max(1, facetColumns)}, minmax(0, 1fr))` }}>
        {facets.map((facetChunk) => (
          <FacetPlot
            key={`facet-${facetChunk.key}`}
            payload={payload}
            spec={spec}
            theme={theme}
            facetChunk={facetChunk}
          />
        ))}
      </div>
    );
  }

  const mergedPayload = facets.length === 1
    ? { ...payload, layers: facets[0].layers || payload.layers || [] }
    : payload;

  return <SinglePlot payload={mergedPayload} spec={spec} theme={theme} />;
}

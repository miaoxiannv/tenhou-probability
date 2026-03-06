import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import * as api from './api/client';

vi.mock('plotly.js-dist-min', () => ({
  default: {
    react: vi.fn(),
    purge: vi.fn(),
  },
}));

vi.mock('./api/client', async () => {
  const actual = await vi.importActual('./api/client');
  return {
    ...actual,
    createSession: vi.fn(),
    requestChat: vi.fn(),
    uploadDataset: vi.fn(),
    previewPlotSpec: vi.fn(),
    exportPdfFile: vi.fn(),
    exportCsvFile: vi.fn(),
    exportPngFile: vi.fn(),
    getSessionState: vi.fn(),
    getSessionHistory: vi.fn(),
  };
});

function baseChatResponse(overrides = {}) {
  return {
    session_id: 'session-1',
    summary: '已回复。',
    used_fallback: false,
    execution_strategy: '',
    fallback_reason: null,
    plot_spec: null,
    stats: null,
    warnings: [],
    thinking: [],
    table_state: null,
    plot_payload: null,
    legacy_image_base64: '',
    raw_model_text: '',
    ...overrides,
  };
}

describe('App behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.createSession.mockResolvedValue({ session_id: 'session-1' });
    api.requestChat.mockResolvedValue(baseChatResponse());
    api.exportPdfFile.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }));
    api.exportCsvFile.mockResolvedValue(new Blob(['group,value\nA,1\n'], { type: 'text/csv' }));
    api.exportPngFile.mockResolvedValue(new Blob(['png'], { type: 'image/png' }));
    api.getSessionState.mockResolvedValue({
      session_id: 'session-1',
      created_at: '2026-03-06T00:00:00Z',
      updated_at: '2026-03-06T00:00:00Z',
      history_count: 1,
      has_plot_spec: false,
      undo_count: 0,
      redo_count: 0,
      snapshots: [],
      table_state: null,
    });
    api.getSessionHistory.mockResolvedValue({
      session_id: 'session-1',
      total: 1,
      items: [
        {
          ts: '2026-03-06T00:00:00Z',
          action: 'upload_file',
          summary: '上传文件 demo.csv',
          details: {},
        },
      ],
    });
    global.URL.createObjectURL = vi.fn(() => 'blob:test');
    global.URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();
  });

  it('can chat without uploading file in auto mode', async () => {
    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, '你好');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(api.requestChat).toHaveBeenCalledWith('session-1', '你好', 'auto');
    });
    await waitFor(() => {
      expect(screen.getAllByText('已回复。').length).toBeGreaterThan(0);
    });
  });

  it('suggestion chip can trigger send', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: '画热图，查看相关性' }));
    await waitFor(() => {
      expect(api.requestChat).toHaveBeenCalledWith('session-1', '画热图，查看相关性', 'auto');
    });
  });

  it('shows excel-like grid when opening data panel', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: '切换数据面板' }));
    await waitFor(() => {
      expect(screen.getByRole('columnheader', { name: 'A' })).toBeInTheDocument();
      expect(screen.getByRole('columnheader', { name: 'H' })).toBeInTheDocument();
    });
  });

  it('keeps version controls inside snapshots tab by default', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: '切换数据面板' }));
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: '字段' })).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: '保存版本' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '版本' }));
    expect(screen.getByRole('button', { name: '保存版本' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '回滚到版本' })).toBeInTheDocument();
  });

  it('shows loading and prevents duplicate submit while sending', async () => {
    let resolveRequest;
    const pending = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    api.requestChat.mockReturnValue(pending);

    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, 'test message');
    await user.click(screen.getByRole('button', { name: '发送' }));

    expect(screen.getByRole('button', { name: '发送中...' })).toBeDisabled();
    expect(api.requestChat).toHaveBeenCalledTimes(1);

    resolveRequest(baseChatResponse({ summary: 'done' }));
    await waitFor(() => {
      expect(screen.getAllByText('done').length).toBeGreaterThan(0);
    });
  });

  it('downloads pdf from unified export menu when plot spec exists', async () => {
    api.requestChat.mockResolvedValue(
      baseChatResponse({
        plot_spec: { chart_type: 'scatter', x: 'x', y: 'y', hue: null, filters: [] },
        plot_payload: {
          chart_type: 'scatter',
          x: 'x',
          y: 'y',
          hue: null,
          records: [{ x: 1, y: 2 }],
          rows: 1,
          total_rows: 1,
          truncated: false,
        },
        summary: '图已更新',
      }),
    );

    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, '画图');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getAllByText('图已更新').length).toBeGreaterThan(0);
    });

    const pdfBtn = screen.getByRole('button', { name: '导出 PDF' });
    await waitFor(() => expect(pdfBtn).toBeEnabled());
    await user.click(pdfBtn);

    await waitFor(() => {
      expect(api.exportPdfFile).toHaveBeenCalledTimes(1);
      expect(api.exportPdfFile).toHaveBeenCalledWith(
        'session-1',
        expect.objectContaining({ chart_type: 'scatter' }),
        expect.stringMatching(/^chart_\d{8}_\d{4}\.pdf$/),
      );
    });
  });

  it('shows execution strategy and fallback hint from backend response', async () => {
    api.requestChat.mockResolvedValue(
      baseChatResponse({
        summary: '未配置模型 API，已通过规则引擎生成 scatter 图。',
        used_fallback: true,
        execution_strategy: 'rule_fallback_no_api_key',
        fallback_reason: 'missing_api_key',
        plot_spec: { chart_type: 'scatter', x: 'x', y: 'y', hue: null, filters: [] },
        plot_payload: {
          chart_type: 'scatter',
          x: 'x',
          y: 'y',
          hue: null,
          records: [{ x: 1, y: 2 }],
          rows: 1,
          total_rows: 1,
          truncated: false,
        },
      }),
    );

    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole('textbox'), '画图');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByText(/生成策略：/)).toBeInTheDocument();
      expect(screen.getByText(/未配置 API Key/)).toBeInTheDocument();
    });
  });

  it('can prefill tuning prompt from tune action', async () => {
    api.requestChat.mockResolvedValue(
      baseChatResponse({
        plot_spec: { chart_type: 'scatter', x: 'x', y: 'y', hue: null, filters: [] },
        plot_payload: {
          chart_type: 'scatter',
          x: 'x',
          y: 'y',
          hue: null,
          records: [{ x: 1, y: 2 }],
          rows: 1,
          total_rows: 1,
          truncated: false,
        },
        summary: '图已更新',
      }),
    );

    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, '画图');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '微调' })).toBeEnabled();
    });

    await user.click(screen.getByRole('button', { name: '微调' }));
    expect(screen.getByRole('textbox')).toHaveValue('请基于当前图微调：');
  });

  it('downloads csv from unified export menu when table data exists', async () => {
    api.requestChat.mockResolvedValue(
      baseChatResponse({
        summary: '表格已更新',
        table_state: {
          filename: 'demo.csv',
          row_count: 2,
          source_row_count: 2,
          column_count: 2,
          columns: [{ name: 'group' }, { name: 'value' }],
          preview_rows: [
            { group: 'A', value: 1 },
            { group: 'B', value: 2 },
          ],
        },
      }),
    );

    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, '筛选 group == A');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getAllByText('表格已更新').length).toBeGreaterThan(0);
    });

    const csvBtn = screen.getByRole('button', { name: '导出 CSV' });
    await waitFor(() => expect(csvBtn).toBeEnabled());
    await user.click(csvBtn);

    await waitFor(() => {
      expect(api.exportCsvFile).toHaveBeenCalledTimes(1);
      expect(api.exportCsvFile).toHaveBeenCalledWith(
        'session-1',
        expect.stringMatching(/^table_\d{8}_\d{4}\.csv$/),
        'active',
      );
    });
  });

  it('triggers undo from data panel controls', async () => {
    api.requestChat
      .mockResolvedValueOnce(
        baseChatResponse({
          summary: '已更新单元格',
          table_state: {
            filename: 'demo.csv',
            row_count: 2,
            source_row_count: 2,
            column_count: 2,
            columns: [{ name: 'group' }, { name: 'value' }],
            preview_rows: [
              { group: 'A', value: 8 },
              { group: 'B', value: 2 },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        baseChatResponse({
          summary: '已撤销上一步操作。',
          table_state: {
            filename: 'demo.csv',
            row_count: 2,
            source_row_count: 2,
            column_count: 2,
            columns: [{ name: 'group' }, { name: 'value' }],
            preview_rows: [
              { group: 'A', value: 1 },
              { group: 'B', value: 2 },
            ],
          },
        }),
      );
    api.getSessionState
      .mockResolvedValueOnce({
        session_id: 'session-1',
        created_at: '2026-03-06T00:00:00Z',
        updated_at: '2026-03-06T00:00:01Z',
        history_count: 2,
        has_plot_spec: false,
        undo_count: 1,
        redo_count: 0,
        snapshots: [],
        table_state: null,
      })
      .mockResolvedValue({
        session_id: 'session-1',
        created_at: '2026-03-06T00:00:00Z',
        updated_at: '2026-03-06T00:00:02Z',
        history_count: 3,
        has_plot_spec: false,
        undo_count: 0,
        redo_count: 1,
        snapshots: [],
        table_state: null,
      });

    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, '把第一行第二列的值改成8');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getAllByText('已更新单元格').length).toBeGreaterThan(0);
    });

    await user.click(screen.getByRole('button', { name: '切换数据面板' }));
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: '字段' })).toBeInTheDocument();
    });
    const undoBtn = screen.getByRole('button', { name: '撤销' });
    await waitFor(() => expect(undoBtn).toBeEnabled());
    await user.click(undoBtn);

    await waitFor(() => {
      expect(api.requestChat).toHaveBeenCalledWith('session-1', '撤销', 'table');
      expect(screen.getAllByText('已撤销上一步操作。').length).toBeGreaterThan(0);
    });
  });

  it('renders audit history in data panel tab', async () => {
    api.requestChat.mockResolvedValue(
      baseChatResponse({
        summary: '表格已更新',
        table_state: {
          filename: 'demo.csv',
          row_count: 2,
          source_row_count: 2,
          column_count: 2,
          columns: [{ name: 'group' }, { name: 'value' }],
          preview_rows: [
            { group: 'A', value: 1 },
            { group: 'B', value: 2 },
          ],
        },
      }),
    );
    api.getSessionHistory.mockResolvedValue({
      session_id: 'session-1',
      total: 2,
      items: [
        {
          ts: '2026-03-06T00:00:03Z',
          action: 'update_cell',
          summary: '更新第 1 行第 2 列',
          details: { column: 'value' },
        },
        {
          ts: '2026-03-06T00:00:01Z',
          action: 'load_file',
          summary: '通过聊天加载文件 demo.csv',
          details: {},
        },
      ],
    });

    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, '把第一行第二列的值改成8');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await user.click(screen.getByRole('button', { name: '切换数据面板' }));
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: '字段' })).toBeInTheDocument();
    });
    await user.click(screen.getByRole('tab', { name: '审计' }));

    await waitFor(() => {
      expect(screen.getByText('update_cell')).toBeInTheDocument();
      expect(screen.getByText('更新第 1 行第 2 列')).toBeInTheDocument();
    });
  });
});

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
  };
});

function baseChatResponse(overrides = {}) {
  return {
    session_id: 'session-1',
    summary: '已回复。',
    used_fallback: false,
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
    global.URL.createObjectURL = vi.fn(() => 'blob:test');
    global.URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();
  });

  it('can chat without uploading file', async () => {
    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByPlaceholderText('输入消息，Enter 发送，Shift+Enter 换行');
    await user.type(textbox, '你好');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(api.requestChat).toHaveBeenCalledWith('session-1', '你好');
    });
    await waitFor(() => {
      expect(screen.getAllByText('已回复。').length).toBeGreaterThan(0);
    });
  });

  it('shows excel-like default grid before upload', () => {
    render(<App />);

    expect(screen.getByRole('columnheader', { name: 'A' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'H' })).toBeInTheDocument();
    expect(screen.getAllByRole('row').length).toBeGreaterThanOrEqual(51);
  });

  it('shows loading and prevents duplicate submit while sending', async () => {
    let resolveRequest;
    const pending = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    api.requestChat.mockReturnValue(pending);

    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByPlaceholderText('输入消息，Enter 发送，Shift+Enter 换行');
    await user.type(textbox, 'test message');
    await user.click(screen.getByRole('button', { name: '发送' }));

    expect(screen.getByRole('button', { name: '发送中...' })).toBeDisabled();
    expect(api.requestChat).toHaveBeenCalledTimes(1);

    resolveRequest(baseChatResponse({ summary: 'done' }));
    await waitFor(() => {
      expect(screen.getAllByText('done').length).toBeGreaterThan(0);
    });
  });

  it('downloads pdf when plot spec exists', async () => {
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

    const textbox = screen.getByPlaceholderText('输入消息，Enter 发送，Shift+Enter 换行');
    await user.type(textbox, '画图');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(screen.getAllByText('图已更新').length).toBeGreaterThan(0);
    });

    const downloadBtn = screen.getByRole('button', { name: '下载 PDF' });
    await waitFor(() => expect(downloadBtn).toBeEnabled());

    await user.click(downloadBtn);
    await waitFor(() => {
      expect(api.exportPdfFile).toHaveBeenCalledTimes(1);
      expect(api.exportPdfFile).toHaveBeenCalledWith(
        'session-1',
        expect.objectContaining({ chart_type: 'scatter' }),
        expect.stringMatching(/^chart_\d{8}_\d{4}\.pdf$/),
      );
    });
  });

  it('keeps pdf button disabled when no plot exists', () => {
    render(<App />);
    const downloadBtn = screen.getByRole('button', { name: '下载 PDF' });
    expect(downloadBtn).toBeDisabled();
    expect(downloadBtn).toHaveAttribute('title', '暂无可导出内容');
  });
});

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatPane } from './ChatPane';

describe('ChatPane send behavior', () => {
  it('disables send button when sendDisabled is true', () => {
    render(
      <ChatPane
        messages={[]}
        prompt=""
        onPromptChange={() => {}}
        onSend={() => {}}
        sendDisabled
        sending={false}
      />,
    );

    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
  });

  it('sends on Enter and keeps newline on Shift+Enter', () => {
    const onSend = vi.fn();
    render(
      <ChatPane
        messages={[]}
        prompt="hello"
        onPromptChange={() => {}}
        onSend={onSend}
        sendDisabled={false}
        sending={false}
      />,
    );

    const textbox = screen.getByRole('textbox');
    fireEvent.keyDown(textbox, { key: 'Enter', shiftKey: false });
    expect(onSend).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(textbox, { key: 'Enter', shiftKey: true });
    expect(onSend).toHaveBeenCalledTimes(1);
  });
});

import React from 'react';

const CHAT_MODE_OPTIONS = [
  { value: 'auto', label: '智能' },
  { value: 'chat', label: '问答' },
  { value: 'plot', label: '制图' },
  { value: 'table', label: '表格' },
];

function Message({ item }) {
  const roleClass = item.role === 'user' ? 'msg user' : item.role === 'error' ? 'msg error' : 'msg assistant';

  return (
    <div className={roleClass}>
      <div className="msg-role">{item.role === 'user' ? '你' : item.role === 'error' ? '系统' : '助手'}</div>
      <div className="msg-text">{item.text}</div>
    </div>
  );
}

export function ChatPane({
  messages,
  prompt,
  onPromptChange,
  mode,
  onModeChange,
  onSend,
  sendDisabled,
  sending,
  placeholder,
  suggestions,
  onUseSuggestion,
  showModeSelector = true,
  textareaRef,
}) {
  const handleSubmit = (event) => {
    event.preventDefault();
    if (!sendDisabled && !sending) {
      onSend();
    }
  };

  return (
    <section className="panel chat-pane panel-enter panel-enter-delay-1">
      <div className="panel-head">
        <div>
          <h2>智能助手</h2>
          <span className="panel-subtitle">业务问题与数据指令</span>
        </div>
        {showModeSelector ? (
          <div className="mode-picker mode-segment" role="tablist" aria-label="聊天模式">
            {CHAT_MODE_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="tab"
                aria-selected={mode === option.value}
                className={`segment-btn ${mode === option.value ? 'active' : ''}`}
                onClick={() => onModeChange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : (
          <span className="panel-subtitle">智能模式</span>
        )}
      </div>

      {Array.isArray(suggestions) && suggestions.length ? (
        <div className="suggestion-row">
          {suggestions.map((item, idx) => (
            <button
              key={`sg-${idx}`}
              type="button"
              className="suggestion-chip"
              onClick={() => onUseSuggestion?.(item)}
              disabled={sending}
            >
              {item}
            </button>
          ))}
        </div>
      ) : null}

      <div className="chat-shell">
        <div className="chat-log">
          {messages.map((item, idx) => (
            <Message key={`${item.role}-${idx}`} item={item} />
          ))}
        </div>

        <form className="composer" onSubmit={handleSubmit}>
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            placeholder={placeholder || '输入消息，Enter 发送，Shift+Enter 换行'}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                if (!sendDisabled && !sending) {
                  onSend();
                }
              }
            }}
          />

          <button type="submit" disabled={sendDisabled || sending}>
            {sending ? '发送中...' : '发送'}
          </button>
        </form>
      </div>
    </section>
  );
}

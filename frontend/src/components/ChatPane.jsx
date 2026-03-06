import React from 'react';

const CHAT_MODE_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'chat', label: 'Chat' },
  { value: 'plot', label: 'Plot' },
  { value: 'table', label: 'Table' },
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
  sending
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
          <h2>对话</h2>
          <span className="panel-subtitle">自然语言指令</span>
        </div>
        <label className="mode-picker">
          <span>模式</span>
          <select
            aria-label="聊天模式"
            value={mode}
            onChange={(event) => onModeChange(event.target.value)}
          >
            {CHAT_MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="chat-shell">
        <div className="chat-log">
          {messages.map((item, idx) => (
            <Message key={`${item.role}-${idx}`} item={item} />
          ))}
        </div>

        <form className="composer" onSubmit={handleSubmit}>
          <textarea
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
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

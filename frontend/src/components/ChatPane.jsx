import React from 'react';

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
        <h2>对话</h2>
        <span className="panel-subtitle">自然语言指令</span>
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

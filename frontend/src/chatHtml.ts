// ==============================================================
// chatHtml.ts
//
// Generates the complete HTML for the sidebar chat webview.
// All CSS + JS is inline (single file, no external assets).
// Styled like GitHub Copilot / Cursor chat panel.
// ==============================================================

import * as vscode from 'vscode';

export function getChatHtml(
  webview: vscode.Webview,
  _context: vscode.ExtensionContext,
): string {
  const nonce = getNonce();

  return /* html */ `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
    content="default-src 'none';
             style-src 'nonce-${nonce}';
             script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenClaw AI</title>
<style nonce="${nonce}">
  /* ── Reset & base ── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-foreground);
    background: var(--vscode-sideBar-background, var(--vscode-editor-background));
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--vscode-panel-border);
    background: var(--vscode-titleBar-activeBackground, var(--vscode-sideBar-background));
    flex-shrink: 0;
  }
  .header-title {
    font-weight: 600;
    font-size: 13px;
    flex: 1;
    color: var(--vscode-titleBar-activeForeground, var(--vscode-foreground));
  }
  .header-icon { font-size: 16px; }

  /* ── Provider selector row ── */
  .provider-row {
    display: flex;
    gap: 6px;
    padding: 6px 10px;
    border-bottom: 1px solid var(--vscode-panel-border);
    flex-shrink: 0;
    align-items: center;
  }
  .provider-row label {
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
    white-space: nowrap;
  }
  .provider-row select {
    flex: 1;
    background: var(--vscode-dropdown-background);
    color: var(--vscode-dropdown-foreground);
    border: 1px solid var(--vscode-dropdown-border);
    border-radius: 3px;
    padding: 2px 4px;
    font-size: 11px;
    cursor: pointer;
    outline: none;
  }
  .provider-row select:focus {
    border-color: var(--vscode-focusBorder);
  }

  /* ── Context bar ── */
  .context-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-bottom: 1px solid var(--vscode-panel-border);
    flex-shrink: 0;
    min-height: 26px;
    background: var(--vscode-editor-background);
  }
  .context-pill {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--vscode-badge-background);
    color: var(--vscode-badge-foreground);
    border-radius: 10px;
    padding: 1px 8px;
    font-size: 10px;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex-shrink: 1;
  }
  .context-pill.selection { background: var(--vscode-gitDecoration-modifiedResourceForeground, #e2c08d); color: #000; }
  .context-none {
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    opacity: 0.5;
  }
  .hidden { display: none !important; }
  .welcome-footer { margin-top: 10px; font-size: 11px; }
  .context-toggle {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    cursor: pointer;
    user-select: none;
    flex-shrink: 0;
  }
  .context-toggle input { cursor: pointer; margin: 0; width: 12px; height: 12px; }
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
    scroll-behavior: smooth;
  }

  /* ── Individual message ── */
  .message {
    padding: 8px 12px;
    line-height: 1.5;
    animation: fadeIn 0.15s ease;
  }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

  .message.user {
    background: var(--vscode-list-hoverBackground);
    border-left: 3px solid var(--vscode-focusBorder);
    margin: 2px 8px 2px 0;
    border-radius: 0 4px 4px 0;
  }
  .message.assistant {
    margin: 2px 0 2px 0;
    background: transparent;
  }

  .message-role {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
    opacity: 0.65;
  }
  .message.user .message-role { color: var(--vscode-focusBorder); }
  .message.assistant .message-role { color: var(--vscode-charts-green, #4ec9b0); }

  .message-content {
    white-space: pre-wrap;
    word-break: break-word;
  }
  .message-content p { margin-bottom: 8px; }
  .message-content p:last-child { margin-bottom: 0; }

  /* ── Code blocks ── */
  .message-content code {
    font-family: var(--vscode-editor-font-family, 'Consolas', monospace);
    font-size: 12px;
    background: var(--vscode-textBlockQuote-background, rgba(127,127,127,0.1));
    border-radius: 3px;
    padding: 1px 4px;
  }
  .message-content pre {
    background: var(--vscode-editor-background);
    border: 1px solid var(--vscode-panel-border);
    border-radius: 4px;
    padding: 10px 12px;
    overflow-x: auto;
    margin: 6px 0;
  }
  .message-content pre code {
    background: none;
    padding: 0;
    font-size: 12px;
  }

  /* ── Tool call indicator ── */
  .tool-call {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
    animation: fadeIn 0.1s ease;
  }
  .tool-call-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--vscode-charts-yellow, #dcdcaa);
    animation: pulse 1s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* ── Typing indicator ── */
  .typing-indicator {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 10px 12px;
  }
  .typing-dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--vscode-charts-green, #4ec9b0);
    animation: bounce 1.2s infinite;
  }
  .typing-dot:nth-child(2) { animation-delay: 0.2s; }
  .typing-dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce {
    0%, 80%, 100% { transform: translateY(0); }
    40% { transform: translateY(-6px); }
  }

  /* ── Meta footer on message ── */
  .message-meta {
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    margin-top: 6px;
    opacity: 0.6;
  }

  /* ── Error message ── */
  .message.error {
    background: var(--vscode-inputValidation-errorBackground, rgba(255,0,0,0.1));
    border-left: 3px solid var(--vscode-inputValidation-errorBorder, #f44747);
    margin: 2px 8px;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    font-size: 12px;
    color: var(--vscode-errorForeground, #f44747);
  }

  /* ── Welcome message ── */
  .welcome {
    padding: 20px 16px;
    text-align: center;
    color: var(--vscode-descriptionForeground);
  }
  .welcome h3 {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--vscode-foreground);
  }
  .welcome p { font-size: 12px; line-height: 1.5; margin-bottom: 6px; }
  .welcome .chip {
    display: inline-block;
    background: var(--vscode-badge-background);
    color: var(--vscode-badge-foreground);
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    margin: 2px;
  }

  /* ── Input area ── */
  .input-area {
    border-top: 1px solid var(--vscode-panel-border);
    padding: 8px 10px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .input-row {
    display: flex;
    gap: 6px;
    align-items: flex-end;
  }
  #messageInput {
    flex: 1;
    background: var(--vscode-input-background);
    color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, transparent);
    border-radius: 4px;
    padding: 7px 10px;
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    resize: none;
    min-height: 36px;
    max-height: 120px;
    line-height: 1.4;
    outline: none;
    transition: border-color 0.1s;
  }
  #messageInput:focus {
    border-color: var(--vscode-focusBorder);
  }
  #messageInput::placeholder {
    color: var(--vscode-input-placeholderForeground);
  }

  .btn {
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    font-family: var(--vscode-font-family);
    transition: background 0.1s, opacity 0.1s;
    display: flex;
    align-items: center;
    gap: 4px;
    white-space: nowrap;
  }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .btn-send {
    background: var(--vscode-button-background);
    color: var(--vscode-button-foreground);
    padding: 7px 14px;
    height: 36px;
    font-weight: 600;
  }
  .btn-send:hover:not(:disabled) { background: var(--vscode-button-hoverBackground); }

  .btn-cancel {
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
    padding: 7px 10px;
    height: 36px;
    display: none;
  }
  .btn-cancel.visible { display: flex; }
  .btn-cancel:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground); }

  .input-hint {
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    opacity: 0.6;
    padding: 0 2px;
  }

  /* Scrollbar */
  #messages::-webkit-scrollbar { width: 4px; }
  #messages::-webkit-scrollbar-track { background: transparent; }
  #messages::-webkit-scrollbar-thumb { background: var(--vscode-scrollbarSlider-background); border-radius: 2px; }
  #messages::-webkit-scrollbar-thumb:hover { background: var(--vscode-scrollbarSlider-hoverBackground); }

  /* ── Tab strip ── */
  .tab-strip {
    display: flex;
    border-bottom: 1px solid var(--vscode-panel-border);
    flex-shrink: 0;
    background: var(--vscode-sideBar-background, var(--vscode-editor-background));
  }
  .tab-btn {
    flex: 1;
    padding: 6px 0;
    font-size: 11px;
    font-family: var(--vscode-font-family);
    font-weight: 500;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--vscode-descriptionForeground);
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
    letter-spacing: 0.3px;
  }
  .tab-btn:hover { color: var(--vscode-foreground); }
  .tab-btn.active {
    color: var(--vscode-foreground);
    border-bottom-color: var(--vscode-focusBorder);
    font-weight: 600;
  }

  /* ── Tools panel ── */
  #toolsPanel {
    display: none;
    flex: 1;
    overflow-y: auto;
    flex-direction: column;
    padding: 8px 0;
  }
  #toolsPanel.visible { display: flex; }

  .tools-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 12px 4px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--vscode-descriptionForeground);
  }
  .tools-section-header .tool-count {
    background: var(--vscode-badge-background);
    color: var(--vscode-badge-foreground);
    border-radius: 8px;
    padding: 0 6px;
    font-size: 10px;
    font-weight: 600;
  }

  .tool-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 4px;
    margin: 1px 6px;
    transition: background 0.1s;
    cursor: default;
  }
  .tool-item:hover { background: var(--vscode-list-hoverBackground); }

  .tool-item-icon {
    font-size: 14px;
    flex-shrink: 0;
    margin-top: 1px;
    width: 18px;
    text-align: center;
  }
  .tool-item-body { flex: 1; min-width: 0; }
  .tool-item-name {
    font-size: 12px;
    font-weight: 600;
    color: var(--vscode-foreground);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tool-item-desc {
    font-size: 10px;
    color: var(--vscode-descriptionForeground);
    margin-top: 1px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tool-item-badge {
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 3px;
    font-weight: 600;
    flex-shrink: 0;
    margin-top: 2px;
  }
  .tool-item-badge.builtin {
    background: var(--vscode-badge-background);
    color: var(--vscode-badge-foreground);
  }
  .tool-item-badge.custom {
    background: var(--vscode-charts-green, #4ec9b0);
    color: #000;
  }

  .tool-run-btn {
    flex-shrink: 0;
    background: var(--vscode-button-secondaryBackground);
    color: var(--vscode-button-secondaryForeground);
    border: none;
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 10px;
    font-family: var(--vscode-font-family);
    cursor: pointer;
    margin-top: 1px;
    transition: background 0.1s;
    white-space: nowrap;
  }
  .tool-run-btn:hover { background: var(--vscode-button-secondaryHoverBackground); }

  .tools-divider {
    height: 1px;
    background: var(--vscode-panel-border);
    margin: 6px 12px;
  }

  .tools-empty {
    padding: 20px 16px;
    text-align: center;
    font-size: 12px;
    color: var(--vscode-descriptionForeground);
    line-height: 1.6;
  }
  .tools-loading {
    padding: 16px;
    text-align: center;
    font-size: 11px;
    color: var(--vscode-descriptionForeground);
    opacity: 0.6;
  }

  #toolsPanel::-webkit-scrollbar { width: 4px; }
  #toolsPanel::-webkit-scrollbar-track { background: transparent; }
  #toolsPanel::-webkit-scrollbar-thumb { background: var(--vscode-scrollbarSlider-background); border-radius: 2px; }
</style>
</head>
<body>

<!-- ── Header ── -->
<div class="header">
  <span class="header-icon">🦾</span>
  <span class="header-title">OpenClaw AI</span>
</div>

<!-- ── Provider / Model selector ── -->
<div class="provider-row">
  <label>Provider</label>
  <select id="providerSelect">
    <option value="openai">OpenAI</option>
    <option value="gemini">Gemini</option>
    <option value="ollama">Ollama</option>
    <option value="vllm">vLLM</option>
  </select>
  <label>Model</label>
  <select id="modelSelect">
    <option value="">Default</option>
  </select>
</div>

<!-- ── Context bar ── -->
<div class="context-bar" id="contextBar">
  <span class="context-none" id="contextNone">No file open</span>
  <span class="context-pill hidden" id="contextPill"></span>
  <label class="context-toggle" title="Toggle file context injection">
    <input type="checkbox" id="contextToggle" checked>
    inject context
  </label>
</div>

<!-- ── Tab strip ── -->
<div class="tab-strip">
  <button class="tab-btn active" id="tabChat" onclick="switchTab('chat')">💬 Chat</button>
  <button class="tab-btn" id="tabTools" onclick="switchTab('tools')">🔧 Tools</button>
</div>

<!-- ── Messages ── -->
<div id="messages">
  <div class="welcome" id="welcomeMsg">
    <h3>👋 OpenClaw AI</h3>
    <p>Your AI-powered dev assistant. Ask anything about your code.</p>
    <div>
      <span class="chip">Generate Tests</span>
      <span class="chip">Code Review</span>
      <span class="chip">Find Bugs</span>
      <span class="chip">Explain Code</span>
    </div>
    <p class="welcome-footer">
      Select code in editor + ask a question for context-aware answers.
    </p>
  </div>
</div>

<!-- ── Tools panel ── -->
<div id="toolsPanel">
  <div class="tools-loading" id="toolsLoading">Loading tools…</div>
</div>

<!-- ── Input area ── -->
<div class="input-area">
  <div class="input-row">
    <textarea
      id="messageInput"
      rows="1"
      placeholder="Ask about your code… (Enter to send, Shift+Enter for newline)"
    ></textarea>
    <button class="btn btn-cancel" id="cancelBtn" title="Cancel">⏹</button>
    <button class="btn btn-send" id="sendBtn" title="Send (Enter)">Send</button>
  </div>
  <div class="input-hint">Enter to send · Shift+Enter for new line · Select code for context</div>
</div>

<script nonce="${nonce}">
const vscode = acquireVsCodeApi();

// ── State ──────────────────────────────────────────────────────────────────
let isStreaming = false;
let currentAssistantEl = null;
let currentContentEl = null;
let providerModels = {};
let currentTab = 'chat';

// ── DOM refs ───────────────────────────────────────────────────────────────
const messagesEl   = document.getElementById('messages');
const toolsPanel   = document.getElementById('toolsPanel');
const inputEl      = document.getElementById('messageInput');
const sendBtn      = document.getElementById('sendBtn');
const cancelBtn    = document.getElementById('cancelBtn');
const welcomeMsg   = document.getElementById('welcomeMsg');
const providerSel  = document.getElementById('providerSelect');
const modelSel     = document.getElementById('modelSelect');
const inputArea    = document.querySelector('.input-area');

// ── Auto-resize textarea ───────────────────────────────────────────────────
inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});

// ── Send on Enter (Shift+Enter = newline) ──────────────────────────────────
inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
sendBtn.addEventListener('click', sendMessage);
cancelBtn.addEventListener('click', () => {
    vscode.postMessage({ type: 'cancelStream' });
});

// ── Provider select → update model list ───────────────────────────────────
providerSel.addEventListener('change', () => {
    updateModelOptions(providerSel.value);
});

function updateModelOptions(provider) {
    const models = providerModels[provider] || [];
    modelSel.innerHTML = '<option value="">Default</option>';
    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m; opt.textContent = m;
        modelSel.appendChild(opt);
    });
}

const contextPill    = document.getElementById('contextPill');
const contextNone    = document.getElementById('contextNone');
const contextToggle  = document.getElementById('contextToggle');

// ── Send message ───────────────────────────────────────────────────────────
function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isStreaming) { return; }

    hideWelcome();
    appendUserMessage(text);

    inputEl.value = '';
    inputEl.style.height = 'auto';

    vscode.postMessage({
        type: 'sendMessage',
        text,
        provider: providerSel.value,
        model: modelSel.value || undefined,
        contextEnabled: contextToggle.checked,
    });
}

// ── Append user message bubble ─────────────────────────────────────────────
function appendUserMessage(text) {
    const el = document.createElement('div');
    el.className = 'message user';
    el.innerHTML = \`
        <div class="message-role">You</div>
        <div class="message-content">\${escapeHtml(text)}</div>
    \`;
    messagesEl.appendChild(el);
    scrollToBottom();
}

// ── Start assistant message bubble ────────────────────────────────────────
function startAssistantMessage() {
    setStreaming(true);

    const el = document.createElement('div');
    el.className = 'message assistant';

    const role = document.createElement('div');
    role.className = 'message-role';
    role.textContent = 'OpenClaw';

    const typing = document.createElement('div');
    typing.className = 'typing-indicator';
    typing.id = 'typingIndicator';
    typing.innerHTML = \`
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    \`;

    const content = document.createElement('div');
    content.className = 'message-content';
    content.style.display = 'none';

    el.appendChild(role);
    el.appendChild(typing);
    el.appendChild(content);
    messagesEl.appendChild(el);

    currentAssistantEl = el;
    currentContentEl = content;
    scrollToBottom();
}

// ── Append a chunk to the streaming bubble ─────────────────────────────────
function appendChunk(text) {
    const typing = document.getElementById('typingIndicator');
    if (typing) {
        typing.style.display = 'none';
        currentContentEl.style.display = 'block';
    }
    currentContentEl.textContent += text;
    scrollToBottom();
}

// ── Finalize the streaming message ────────────────────────────────────────
function finalizeMessage(content, meta) {
    if (currentContentEl && content) {
        currentContentEl.textContent = '';
        currentContentEl.innerHTML = renderMarkdown(content);
        currentContentEl.style.display = 'block';
        const typing = document.getElementById('typingIndicator');
        if (typing) { typing.remove(); }
    }
    if (meta && currentAssistantEl) {
        const metaEl = document.createElement('div');
        metaEl.className = 'message-meta';
        const parts = [];
        if (meta.provider) { parts.push(meta.provider + (meta.model ? ' / ' + meta.model : '')); }
        if (meta.durationMs) { parts.push((meta.durationMs / 1000).toFixed(1) + 's'); }
        if (meta.totalToolCalls) { parts.push(meta.totalToolCalls + ' tool calls'); }
        metaEl.textContent = parts.join(' · ');
        currentAssistantEl.appendChild(metaEl);
    }
    setStreaming(false);
    currentAssistantEl = null;
    currentContentEl = null;
    scrollToBottom();
}

// ── Add a tool call indicator ──────────────────────────────────────────────
function addToolCallIndicator(toolName, count) {
    const el = document.createElement('div');
    el.className = 'tool-call';
    el.innerHTML = \`
        <div class="tool-call-dot"></div>
        <span>Using tool: <strong>\${escapeHtml(toolName || 'unknown')}</strong> (#\${count})</span>
    \`;
    messagesEl.appendChild(el);
    scrollToBottom();
}

// ── Show error ─────────────────────────────────────────────────────────────
function showError(message) {
    setStreaming(false);
    const typing = document.getElementById('typingIndicator');
    if (typing) { typing.remove(); }
    const el = document.createElement('div');
    el.className = 'message error';
    el.textContent = '⚠ ' + message;
    messagesEl.appendChild(el);
    scrollToBottom();
}

// ── Helpers ────────────────────────────────────────────────────────────────
function setStreaming(val) {
    isStreaming = val;
    sendBtn.disabled = val;
    cancelBtn.classList.toggle('visible', val);
    inputEl.disabled = val;
}

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function hideWelcome() {
    if (welcomeMsg) { welcomeMsg.style.display = 'none'; }
}

function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── Simple markdown renderer (bold, code, code blocks) ──────────────────
function renderMarkdown(text) {
    // Code blocks
    text = text.replace(/\`\`\`(\\w*)\\n([\\s\\S]*?)\`\`\`/g, (_, lang, code) => {
        return \`<pre><code class="language-\${lang}">\${escapeHtml(code.trim())}</code></pre>\`;
    });
    // Inline code
    text = text.replace(/\`([^\`]+)\`/g, (_, code) => \`<code>\${escapeHtml(code)}</code>\`);
    // Bold
    text = text.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
    // Italic
    text = text.replace(/\\*(.+?)\\*/g, '<em>$1</em>');
    // Newlines to <br>
    text = text.replace(/\\n/g, '<br>');
    return text;
}

// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(tab) {
    currentTab = tab;
    const isChat = tab === 'chat';
    document.getElementById('tabChat').classList.toggle('active', isChat);
    document.getElementById('tabTools').classList.toggle('active', !isChat);
    messagesEl.style.display = isChat ? '' : 'none';
    toolsPanel.classList.toggle('visible', !isChat);
    inputArea.style.display = isChat ? '' : 'none';
    if (!isChat) {
        vscode.postMessage({ type: 'getTools' });
    }
}

// ── Render tools panel ─────────────────────────────────────────────────────
const BUILTIN_ICONS = {
    generate_tests: '🧪', review_code: '🔍', find_bugs: '🐛',
    explain_code: '📖', refactor_code: '♻️', generate_docs: '📝',
    security_analysis: '🔒', optimize_performance: '⚡',
    analyze_complexity: '📊', translate_code: '🔄',
};

function renderTools(builtin, custom) {
    toolsPanel.innerHTML = '';

    const hasCustom = custom && custom.length > 0;
    const hasBuiltin = builtin && builtin.length > 0;

    if (!hasCustom && !hasBuiltin) {
        toolsPanel.innerHTML = '<div class="tools-empty">No tools available.<br>Start the backend to load tools.</div>';
        return;
    }

    // ── Custom tools section ────────────────────────────────────────────────
    if (hasCustom) {
        const hdr = document.createElement('div');
        hdr.className = 'tools-section-header';
        hdr.innerHTML = \`<span>Custom Tools</span><span class="tool-count">\${custom.length}</span>\`;
        toolsPanel.appendChild(hdr);

        custom.forEach(t => {
            const item = document.createElement('div');
            item.className = 'tool-item';
            item.innerHTML = \`
                <div class="tool-item-icon">🔧</div>
                <div class="tool-item-body">
                    <div class="tool-item-name">\${escapeHtml(t.displayName || t.name)}</div>
                    <div class="tool-item-desc">\${escapeHtml(t.description || 'Custom tool')}</div>
                </div>
                <span class="tool-item-badge custom">custom</span>
                <button class="tool-run-btn" data-tool="\${escapeHtml(t.name)}" data-type="custom">▶ Run</button>
            \`;
            toolsPanel.appendChild(item);
        });

        if (hasBuiltin) {
            const div = document.createElement('div');
            div.className = 'tools-divider';
            toolsPanel.appendChild(div);
        }
    }

    // ── Builtin tools section ───────────────────────────────────────────────
    if (hasBuiltin) {
        const hdr = document.createElement('div');
        hdr.className = 'tools-section-header';
        hdr.innerHTML = \`<span>Built-in Tools</span><span class="tool-count">\${builtin.length}</span>\`;
        toolsPanel.appendChild(hdr);

        builtin.forEach(t => {
            const icon = BUILTIN_ICONS[t.name] || '⚙️';
            const item = document.createElement('div');
            item.className = 'tool-item';
            item.innerHTML = \`
                <div class="tool-item-icon">\${icon}</div>
                <div class="tool-item-body">
                    <div class="tool-item-name">\${escapeHtml(t.displayName || t.name)}</div>
                    <div class="tool-item-desc">\${escapeHtml(t.description || '')}</div>
                </div>
                <span class="tool-item-badge builtin">builtin</span>
                <button class="tool-run-btn" data-tool="\${escapeHtml(t.name)}" data-type="builtin">▶ Run</button>
            \`;
            toolsPanel.appendChild(item);
        });
    }

    // ── Wire up Run buttons ─────────────────────────────────────────────────
    toolsPanel.querySelectorAll('.tool-run-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const toolName = btn.getAttribute('data-tool');
            vscode.postMessage({ type: 'runCustomTool', toolName });
            // Switch to chat tab so user sees the result
            switchTab('chat');
        });
    });
}

// ── Messages from extension → webview ─────────────────────────────────────
window.addEventListener('message', (event) => {
    const msg = event.data;
    switch (msg.type) {

        case 'pushUserMessage':
            // FIX #2: tool right-click results now show the triggering message in chat
            // Previously missing — tool ran silently with no user message visible
            hideWelcome();
            appendUserMessage(msg.text);
            break;

        case 'startAssistant':
            startAssistantMessage();
            break;

        case 'chunk':
            appendChunk(msg.content);
            break;

        case 'done':
            finalizeMessage(null, {
                provider: msg.provider,
                model: msg.model,
                durationMs: msg.durationMs,
                totalToolCalls: msg.totalToolCalls,
            });
            break;

        case 'fullResponse':
            finalizeMessage(msg.content, {
                provider: msg.provider,
                model: msg.model,
                durationMs: msg.durationMs,
                totalToolCalls: msg.totalToolCalls,
            });
            break;

        case 'toolCall':
            addToolCallIndicator(msg.toolName, msg.count);
            break;

        case 'error':
            showError(msg.message);
            break;

        case 'cancelled':
            finalizeMessage(null, null);
            break;

        case 'contextAttached':
            updateContextPill(msg.summary);
            break;

        case 'clearChat':
            messagesEl.innerHTML = '';
            if (welcomeMsg) {
                welcomeMsg.style.display = 'block';
                messagesEl.appendChild(welcomeMsg);
            }
            break;

        case 'newSession':
            messagesEl.innerHTML = '';
            if (welcomeMsg) {
                welcomeMsg.style.display = 'block';
                messagesEl.appendChild(welcomeMsg);
            }
            break;

        case 'providers':
            updateProviderDropdowns(msg.providers || []);
            break;

        case 'tools':
            renderTools(msg.builtin || [], msg.custom || []);
            break;
    }
});

// ── Update the context pill in the bar ────────────────────────────────────
function updateContextPill(summary) {
    if (!summary) {
        contextNone.classList.remove('hidden');
        contextPill.classList.add('hidden');
        return;
    }
    contextNone.classList.add('hidden');
    contextPill.classList.remove('hidden');
    contextPill.textContent = summary.label;
    contextPill.className = 'context-pill' + (summary.captureMode === 'selection' ? ' selection' : '');
    contextPill.title = \`\${summary.lineCount} lines · \${summary.captureMode}\${summary.truncated ? ' · truncated' : ''}\`;
}

// ── Update provider + model dropdowns from backend ─────────────────────────
function updateProviderDropdowns(providers) {
    providerModels = {};
    const currentProvider = providerSel.value;

    // Clear and rebuild provider options
    providerSel.innerHTML = '';
    providers.forEach(p => {
        providerModels[p.provider] = p.models || [];
        const opt = document.createElement('option');
        opt.value = p.provider;
        opt.textContent = p.provider.charAt(0).toUpperCase() + p.provider.slice(1)
            + (p.type === 'local' ? ' (local)' : '');
        if (p.error) { opt.textContent += ' ⚠'; opt.disabled = true; }
        providerSel.appendChild(opt);
    });

    // Restore previous selection or fallback to first
    if (providers.find(p => p.provider === currentProvider)) {
        providerSel.value = currentProvider;
    }
    updateModelOptions(providerSel.value);
}

// ── Request providers on load ──────────────────────────────────────────────
vscode.postMessage({ type: 'getProviders' });
</script>
</body>
</html>`;
}

function getNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from({ length: 32 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
}

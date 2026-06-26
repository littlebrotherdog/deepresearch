/* Deep Research Agent - Frontend Logic */

const API = {
    sessions: '/api/sessions',
    modelConfig: '/api/model/config',
    wsUrl: `ws://${window.location.host}/ws/chat`,
};

let currentSessionId = null;
let ws = null;
let isResearching = false;

// ---------------------------------------------------------------------------
// Markdown rendering (minimal)
// ---------------------------------------------------------------------------
function renderMarkdown(text) {
    if (!text) return '';
    let html = text;
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code class="${lang}">${escapeHtml(code.trim())}</code></pre>`);
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // Bold and italic
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    // Blockquote
    html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
    // Unordered lists
    html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
    // Ordered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    // Paragraphs
    html = html.split('\n\n').map(p => {
        if (p.startsWith('<') || p.trim() === '') return p;
        return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    }).join('\n');
    return html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------
async function loadSessions() {
    const resp = await fetch(API.sessions);
    const sessions = await resp.json();
    const list = document.getElementById('session-list');
    list.innerHTML = '';
    sessions.forEach(s => {
        const item = document.createElement('div');
        item.className = 'session-item' + (s.id === currentSessionId ? ' active' : '');
        item.dataset.sessionId = s.id;
        const time = new Date(s.updated_at * 1000).toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
        });
        item.innerHTML = `
            <div style="flex:1;overflow:hidden;">
                <div class="session-title">${escapeHtml(s.title || '未命名')}</div>
                <div class="session-meta">${time} · ${s.message_count}条消息 · ${s.research_count}条研究</div>
            </div>
        `;
        item.onclick = () => selectSession(s.id);
        list.appendChild(item);
    });
}

async function createSession() {
    const resp = await fetch(API.sessions, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: '' }),
    });
    const session = await resp.json();
    currentSessionId = session.id;
    await loadSessions();
    await loadSessionMessages(session.id);
    document.getElementById('message-input').focus();
}

async function selectSession(sessionId) {
    currentSessionId = sessionId;
    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.sessionId === sessionId);
    });
    await loadSessionMessages(sessionId);
}

async function loadSessionMessages(sessionId) {
    const resp = await fetch(`${API.sessions}/${sessionId}`);
    const session = await resp.json();
    const messagesEl = document.getElementById('chat-messages');
    messagesEl.innerHTML = '';

    document.getElementById('current-session-title').textContent = session.title || '未命名会话';
    document.getElementById('delete-session-btn').style.display = 'block';

    // Display conversation messages
    if (session.short_term && session.short_term.length > 0) {
        session.short_term.forEach(m => {
            if (m.role === 'user' || m.role === 'assistant') {
                addMessageToUI(m.role, m.content);
            }
        });
    }

    // Show long-term memory summary if exists
    if (session.long_term && session.long_term.length > 0) {
        const memDiv = document.createElement('div');
        memDiv.className = 'message assistant';
        memDiv.style.fontSize = '12px';
        memDiv.style.opacity = '0.6';
        memDiv.innerHTML = `<em>记忆摘要 (${session.long_term.length} 条): 之前对话的关键信息已保存在长期记忆中</em>`;
        messagesEl.insertBefore(memDiv, messagesEl.firstChild);
    }

    // Show research notes count
    if (session.research && session.research.length > 0) {
        const resDiv = document.createElement('div');
        resDiv.className = 'message assistant';
        resDiv.style.fontSize = '12px';
        resDiv.style.opacity = '0.6';
        resDiv.innerHTML = `<em>已收集 ${session.research.length} 条研究资料</em>`;
        messagesEl.insertBefore(resDiv, messagesEl.firstChild);
    }

    if (session.short_term.length === 0) {
        showWelcome();
    }
}

function showWelcome() {
    const messagesEl = document.getElementById('chat-messages');
    messagesEl.innerHTML = `
        <div class="welcome-message">
            <h2>Deep Research Agent</h2>
            <p>基于百度搜索的深度研究助手，支持信息搜集、分析总结和多会话记忆管理。</p>
            <div class="features">
                <div class="feature">
                    <span class="feature-icon">搜索</span>
                    <span>通过百度搜索收集实时信息</span>
                </div>
                <div class="feature">
                    <span class="feature-icon">分析</span>
                    <span>多轮搜索 + 智能信息提取</span>
                </div>
                <div class="feature">
                    <span class="feature-icon">记忆</span>
                    <span>按会话管理，长期记忆不丢失</span>
                </div>
            </div>
        </div>
    `;
}

function addMessageToUI(role, content) {
    const messagesEl = document.getElementById('chat-messages');
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    if (role === 'assistant') {
        msgDiv.innerHTML = renderMarkdown(content);
    } else {
        msgDiv.textContent = content;
    }
    messagesEl.appendChild(msgDiv);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return msgDiv;
}

// ---------------------------------------------------------------------------
// WebSocket chat
// ---------------------------------------------------------------------------
function connectWebSocket() {
    ws = new WebSocket(API.wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWsMessage(data);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
        console.log('WebSocket closed, reconnecting in 3s...');
        setTimeout(connectWebSocket, 3000);
    };
}

function handleWsMessage(data) {
    const { step, message, data: stepData } = data;

    if (step === 'session') {
        currentSessionId = stepData.session_id;
        loadSessions();
        return;
    }

    if (step === 'planning') {
        showProgress(message, 'planning');
        if (stepData && stepData.queries) {
            stepData.queries.forEach(q => {
                addProgressStep(`搜索词: ${q}`, 'planning');
            });
        }
        return;
    }

    if (step === 'searching') {
        showProgress(message, 'searching');
        addProgressStep(message, 'searching');
        return;
    }

    if (step === 'reading') {
        addProgressStep(message, 'reading');
        return;
    }

    if (step === 'synthesizing') {
        if (stepData && stepData.streaming) {
            // Streaming synthesis content
            const progressEl = document.getElementById('research-progress');
            if (progressEl.style.display !== 'none') {
                progressEl.style.display = 'none';
                // Start streaming assistant message
                currentStreamingMsg = addMessageToUI('assistant', '');
            }
            if (currentStreamingMsg) {
                currentStreamingMsg.innerHTML = renderMarkdown(
                    (currentStreamingMsg.dataset.raw || '') + message
                );
                currentStreamingMsg.dataset.raw = (currentStreamingMsg.dataset.raw || '') + message;
                const messagesEl = document.getElementById('chat-messages');
                messagesEl.scrollTop = messagesEl.scrollHeight;
            }
        }
        return;
    }

    if (step === 'done') {
        if (message) {
            // Non-streaming done with full message
            if (currentStreamingMsg) {
                currentStreamingMsg.innerHTML = renderMarkdown(message);
            } else {
                addMessageToUI('assistant', message);
            }
        }
        currentStreamingMsg = null;
        hideProgress();
        isResearching = false;
        updateSendButton();
        loadSessions(); // refresh session list
        return;
    }

    if (step === 'complete') {
        currentStreamingMsg = null;
        hideProgress();
        isResearching = false;
        updateSendButton();
        loadSessions();
        return;
    }

    if (step === 'error') {
        hideProgress();
        isResearching = false;
        updateSendButton();
        addMessageToUI('assistant', `错误: ${message}`);
        return;
    }
}

let currentStreamingMsg = null;

function showProgress(text, type) {
    const el = document.getElementById('research-progress');
    el.style.display = 'block';
    document.getElementById('progress-text').textContent = text;
}

function addProgressStep(text, type) {
    const steps = document.getElementById('progress-steps');
    const step = document.createElement('div');
    step.className = `progress-step ${type}`;
    step.textContent = text;
    steps.appendChild(step);
    steps.scrollTop = steps.scrollHeight;
}

function hideProgress() {
    document.getElementById('research-progress').style.display = 'none';
    document.getElementById('progress-steps').innerHTML = '';
}

// ---------------------------------------------------------------------------
// Send message
// ---------------------------------------------------------------------------
function sendMessage() {
    const input = document.getElementById('message-input');
    const message = input.value.trim();
    if (!message || isResearching) return;

    if (!currentSessionId) {
        createSession().then(() => {
            addMessageToUI('user', message);
            input.value = '';
            input.style.height = 'auto';
            isResearching = true;
            updateSendButton();
            ws.send(JSON.stringify({ session_id: currentSessionId, message }));
        });
        return;
    }

    addMessageToUI('user', message);
    input.value = '';
    input.style.height = 'auto';
    isResearching = true;
    updateSendButton();

    // Reset streaming state
    currentStreamingMsg = null;

    ws.send(JSON.stringify({ session_id: currentSessionId, message }));
}

function updateSendButton() {
    const btn = document.getElementById('send-btn');
    const input = document.getElementById('message-input');
    btn.disabled = isResearching || !input.value.trim();
}

// ---------------------------------------------------------------------------
// Model config
// ---------------------------------------------------------------------------
async function loadModelConfig() {
    try {
        const resp = await fetch(API.modelConfig);
        const config = await resp.json();
        document.getElementById('config-base-url').value = config.base_url || '';
        document.getElementById('config-api-key').value = '';
        document.getElementById('config-api-key').placeholder = config.api_key || 'sk-...';
        document.getElementById('config-model-name').value = config.model_name || '';
        document.getElementById('config-temperature').value = config.temperature || 0.3;
        document.getElementById('config-max-tokens').value = config.max_tokens || 4096;
    } catch (e) {
        console.error('Failed to load model config:', e);
    }
}

async function saveModelConfig() {
    const config = {
        base_url: document.getElementById('config-base-url').value.trim() || null,
        api_key: document.getElementById('config-api-key').value.trim() || null,
        model_name: document.getElementById('config-model-name').value.trim() || null,
        temperature: parseFloat(document.getElementById('config-temperature').value) || null,
        max_tokens: parseInt(document.getElementById('config-max-tokens').value) || null,
    };

    const statusEl = document.getElementById('config-status');
    statusEl.className = 'config-status';
    statusEl.textContent = '保存中...';
    statusEl.style.display = 'block';

    try {
        const resp = await fetch(API.modelConfig, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        });
        const result = await resp.json();
        statusEl.className = 'config-status success';
        statusEl.textContent = `配置已保存: ${result.model_name} @ ${result.base_url}`;
        setTimeout(() => {
            document.getElementById('config-modal').style.display = 'none';
        }, 1000);
    } catch (e) {
        statusEl.className = 'config-status error';
        statusEl.textContent = `保存失败: ${e.message}`;
    }
}

// ---------------------------------------------------------------------------
// Delete session
// ---------------------------------------------------------------------------
async function deleteCurrentSession() {
    if (!currentSessionId) return;
    if (!confirm('确定删除当前会话？所有记忆将被清除。')) return;
    await fetch(`${API.sessions}/${currentSessionId}`, { method: 'DELETE' });
    currentSessionId = null;
    document.getElementById('current-session-title').textContent = '选择或新建一个会话';
    document.getElementById('delete-session-btn').style.display = 'none';
    showWelcome();
    await loadSessions();
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    // New session
    document.getElementById('new-session-btn').onclick = createSession;

    // Delete session
    document.getElementById('delete-session-btn').onclick = deleteCurrentSession;

    // Send button
    document.getElementById('send-btn').onclick = sendMessage;

    // Input - Enter to send, Shift+Enter for newline
    const input = document.getElementById('message-input');
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        updateSendButton();
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Config modal
    document.getElementById('config-btn').onclick = () => {
        document.getElementById('config-modal').style.display = 'flex';
        loadModelConfig();
    };
    document.getElementById('close-config').onclick = () => {
        document.getElementById('config-modal').style.display = 'none';
    };
    document.getElementById('save-config').onclick = saveModelConfig;

    // Close modal on background click
    document.getElementById('config-modal').onclick = (e) => {
        if (e.target.id === 'config-modal') {
            e.target.style.display = 'none';
        }
    };

    // Initialize
    loadSessions();
    connectWebSocket();
});

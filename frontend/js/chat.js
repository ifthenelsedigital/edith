/**
 * EDITH — Chat UI Module
 * 
 * Handles message rendering, markdown parsing, and chat display logic.
 */

const Chat = (() => {
    const messagesContainer = () => document.getElementById('chatMessages');
    const welcomeScreen = () => document.getElementById('welcomeScreen');

    /**
     * Simple Markdown → HTML converter
     */
    function parseMarkdown(text) {
        if (!text) return '';

        let html = text;

        // Escape HTML entities (but preserve intentional tags)
        html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        // Code blocks (```...```)
        html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
            return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
        });

        // Inline code (`...`)
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Bold (**...**)
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

        // Italic (*...*)
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

        // Links [text](url)
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

        // Unordered lists
        html = html.replace(/^[\s]*[-*]\s+(.+)/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>\n?)+/gs, (match) => `<ul>${match}</ul>`);

        // Ordered lists
        html = html.replace(/^[\s]*\d+\.\s+(.+)/gm, '<li>$1</li>');

        // Headers
        html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');

        // Paragraphs (double newline)
        html = html.replace(/\n\n/g, '</p><p>');
        
        // Single newlines → <br> (except inside pre/code)
        html = html.replace(/(?<!<\/pre>)\n(?!<pre>)/g, '<br>');

        // Wrap in paragraph if not already structured
        if (!html.startsWith('<')) {
            html = `<p>${html}</p>`;
        }

        return html;
    }

    /**
     * Hide the welcome screen
     */
    function hideWelcome() {
        const ws = welcomeScreen();
        if (ws) {
            ws.style.display = 'none';
        }
    }

    /**
     * Show the welcome screen
     */
    function showWelcome() {
        const ws = welcomeScreen();
        if (ws) {
            ws.style.display = 'flex';
        }
    }

    /**
     * Add a user message to the chat
     */
    function addUserMessage(content) {
        hideWelcome();

        const container = messagesContainer();
        const div = document.createElement('div');
        div.className = 'message user';
        div.innerHTML = `
            <div class="message-avatar">U</div>
            <div class="message-body">
                <div class="message-content">${escapeHtml(content)}</div>
            </div>
        `;
        container.appendChild(div);
        Animations.scrollToBottom(container);
    }

    /**
     * Start an assistant message (returns an object to append tokens to)
     */
    function startAssistantMessage() {
        hideWelcome();

        const container = messagesContainer();
        const div = document.createElement('div');
        div.className = 'message assistant';
        div.innerHTML = `
            <div class="message-avatar">E</div>
            <div class="message-body">
                <div class="message-content"></div>
            </div>
        `;
        container.appendChild(div);

        const contentEl = div.querySelector('.message-content');
        let rawText = '';

        return {
            element: div,
            contentElement: contentEl,
            appendToken(token) {
                rawText += token;
                contentEl.innerHTML = parseMarkdown(rawText);
                Animations.scrollToBottom(container);
            },
            finalize() {
                contentEl.innerHTML = parseMarkdown(rawText);
                Animations.scrollToBottom(container);
            },
            getRawText() {
                return rawText;
            },
        };
    }

    /**
     * Add a complete assistant message
     */
    function addAssistantMessage(content) {
        hideWelcome();

        const container = messagesContainer();
        const div = document.createElement('div');
        div.className = 'message assistant';
        div.innerHTML = `
            <div class="message-avatar">E</div>
            <div class="message-body">
                <div class="message-content">${parseMarkdown(content)}</div>
            </div>
        `;
        container.appendChild(div);
        Animations.scrollToBottom(container);
    }

    /**
     * Add a tool execution card (running state)
     */
    function addToolStart(name, args) {
        const container = messagesContainer();
        const div = document.createElement('div');
        div.className = 'message assistant';
        div.id = `tool-${name}-${Date.now()}`;

        const argsStr = Object.entries(args || {})
            .map(([k, v]) => `${k}: ${v}`)
            .join(', ');

        const toolIcons = {
            set_volume: '🔊',
            get_volume: '🔊',
            set_brightness: '☀️',
            get_brightness: '☀️',
            open_url: '🌐',
            list_tabs: '📑',
            switch_tab: '🔀',
            close_tab: '❌',
            search_files: '📂',
            web_search: '🔍',
        };
        const icon = toolIcons[name] || '⚙️';

        div.innerHTML = `
            <div class="message-avatar" style="background: rgba(124, 58, 237, 0.1); border: 1px solid rgba(124, 58, 237, 0.2); color: #7c3aed;">
                ⚙
            </div>
            <div class="message-body">
                <div class="tool-card">
                    <div class="tool-card-header">
                        <span class="tool-icon">${icon}</span>
                        <span class="tool-name">${name}</span>
                        <span style="margin-left:auto;"><span class="tool-spinner"></span></span>
                    </div>
                    <div class="tool-card-body">${argsStr ? `Arguments: ${argsStr}` : 'Executing…'}</div>
                </div>
            </div>
        `;
        container.appendChild(div);
        Animations.scrollToBottom(container);
        return div.id;
    }

    /**
     * Update a tool card with its result
     */
    function updateToolResult(name, result) {
        // Find the last tool card for this tool name
        const cards = document.querySelectorAll('.tool-card-header .tool-name');
        let targetCard = null;
        cards.forEach(c => {
            if (c.textContent === name) {
                targetCard = c.closest('.tool-card');
            }
        });

        if (targetCard) {
            // Remove spinner
            const spinner = targetCard.querySelector('.tool-spinner');
            if (spinner) {
                spinner.parentElement.innerHTML = '<span style="color: #22c55e;">✓</span>';
            }
            // Update body
            const body = targetCard.querySelector('.tool-card-body');
            if (body) {
                body.textContent = result;
            }
        }
    }

    /**
     * Clear all messages
     */
    function clearMessages() {
        const container = messagesContainer();
        container.innerHTML = '';
        showWelcome();
    }

    /**
     * Load messages from history
     */
    function loadMessages(messages) {
        const container = messagesContainer();
        // Remove welcome screen temporarily
        const ws = welcomeScreen();
        container.innerHTML = '';
        
        if (!messages || messages.length === 0) {
            if (ws) container.appendChild(ws);
            showWelcome();
            return;
        }

        hideWelcome();

        messages.forEach(msg => {
            if (msg.role === 'user') {
                const div = document.createElement('div');
                div.className = 'message user';
                div.innerHTML = `
                    <div class="message-avatar">U</div>
                    <div class="message-body">
                        <div class="message-content">${escapeHtml(msg.content)}</div>
                    </div>
                `;
                container.appendChild(div);
            } else if (msg.role === 'assistant') {
                const div = document.createElement('div');
                div.className = 'message assistant';
                div.innerHTML = `
                    <div class="message-avatar">E</div>
                    <div class="message-body">
                        <div class="message-content">${parseMarkdown(msg.content)}</div>
                    </div>
                `;
                container.appendChild(div);
            } else if (msg.role === 'tool') {
                const div = document.createElement('div');
                div.className = 'message assistant';
                div.innerHTML = `
                    <div class="message-avatar" style="background: rgba(124, 58, 237, 0.1); border: 1px solid rgba(124, 58, 237, 0.2); color: #7c3aed;">⚙</div>
                    <div class="message-body">
                        <div class="tool-card">
                            <div class="tool-card-header">
                                <span class="tool-icon">⚙️</span>
                                <span class="tool-name">${msg.tool_name || 'tool'}</span>
                                <span style="margin-left:auto; color: #22c55e;">✓</span>
                            </div>
                            <div class="tool-card-body">${escapeHtml(msg.content)}</div>
                        </div>
                    </div>
                `;
                container.appendChild(div);
            }
        });

        Animations.scrollToBottom(container, false);
    }

    /**
     * Escape HTML to prevent XSS
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Add an approval card for a command-router action
     * Returns an object with { element, resolve(result), reject() }
     */
    function addApprovalCard(approvalId, toolName, args, description) {
        hideWelcome();

        const container = messagesContainer();
        const div = document.createElement('div');
        div.className = 'message assistant';
        div.id = `approval-${approvalId}`;

        const toolIcons = {
            set_volume: '🔊',
            get_volume: '🔊',
            set_brightness: '☀️',
            get_brightness: '☀️',
            open_url: '🌐',
            launch_app: '🚀',
            create_text_file: '📝',
            web_search: '🔍',
        };
        const icon = toolIcons[toolName] || '⚙️';

        const argsStr = Object.entries(args || {})
            .filter(([_, v]) => v !== '' && v !== null && v !== undefined)
            .map(([k, v]) => `${k}: ${v}`)
            .join(', ');

        div.innerHTML = `
            <div class="message-avatar" style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.25); color: #f59e0b;">
                ⚡
            </div>
            <div class="message-body">
                <div class="approval-card" data-approval-id="${approvalId}">
                    <div class="approval-card-header">
                        <span class="approval-icon">${icon}</span>
                        <span class="approval-label">Action Approval Required</span>
                    </div>
                    <div class="approval-card-body">
                        <div class="approval-description">${escapeHtml(description)}</div>
                        ${argsStr ? `<div class="approval-tool-info">${escapeHtml(toolName)}(${escapeHtml(argsStr)})</div>` : `<div class="approval-tool-info">${escapeHtml(toolName)}</div>`}
                        <div class="approval-actions">
                            <button class="approval-btn approval-btn-approve" data-action="approve">✓ Approve</button>
                            <button class="approval-btn approval-btn-deny" data-action="deny">✕ Deny</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        container.appendChild(div);
        Animations.scrollToBottom(container);

        const card = div.querySelector('.approval-card');
        const approveBtn = div.querySelector('[data-action="approve"]');
        const denyBtn = div.querySelector('[data-action="deny"]');

        return {
            element: div,
            approvalId: approvalId,
            approveBtn,
            denyBtn,
            resolve(statusText) {
                // Mark the card as resolved
                card.classList.add('resolved');
                const actionsEl = card.querySelector('.approval-actions');
                if (actionsEl) {
                    actionsEl.innerHTML = `<span class="approval-result">${escapeHtml(statusText)}</span>`;
                }
            },
        };
    }

    return {
        addUserMessage,
        startAssistantMessage,
        addAssistantMessage,
        addToolStart,
        updateToolResult,
        addApprovalCard,
        clearMessages,
        loadMessages,
        hideWelcome,
        showWelcome,
        parseMarkdown,
    };
})();

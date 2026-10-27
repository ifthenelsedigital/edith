/**
 * EDITH — Main Application Controller
 *
 * Initializes WebSocket, manages sessions, wires voice state machine
 * to the UI, and orchestrates the full voice → transcribe → LLM → TTS flow.
 */

const App = (() => {
    // ── State ──
    let ws = null;
    let currentSessionId = null;
    let isProcessing = false;
    let reconnectAttempts = 0;
    const MAX_RECONNECT = 5;
    let currentAssistantMessage = null;
    let pendingMessage = null;
    let recoveringMessage = false;

    // ── Voice preferences ──
    let ttsEnabled = true;          // voice responses on by default when voice input used
    let lastInputWasVoice = false;  // track whether last input came from mic

    // ── DOM Refs ──
    const chatInput     = () => document.getElementById('chatInput');
    const sendBtn       = () => document.getElementById('sendBtn');
    const newChatBtn    = () => document.getElementById('newChatBtn');
    const sessionsList  = () => document.getElementById('sessionsList');
    const modelBadge    = () => document.getElementById('modelBadge');
    const settingsBtn   = () => document.getElementById('settingsBtn');
    const settingsModal = () => document.getElementById('settingsModal');
    const settingsClose = () => document.getElementById('settingsClose');
    const menuToggle    = () => document.getElementById('menuToggle');
    const panelLeft     = () => document.getElementById('panelLeft');
    const deleteChatBtn = () => document.getElementById('deleteChatBtn');

    // ════════════════════════════════════════════════
    //  WebSocket
    // ════════════════════════════════════════════════

    function connectWebSocket() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${location.host}/ws/chat`;

        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('🟢 WebSocket connected');
            Animations.setStatus('online', 'Connected');
            reconnectAttempts = 0;
            if (pendingMessage !== null) {
                recoverPendingMessage(pendingMessage);
            }
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleServerEvent(data);
            } catch (err) {
                console.error('Failed to parse server message:', err);
            }
        };

        ws.onclose = () => {
            console.log('🔴 WebSocket disconnected');
            Animations.setStatus('error', 'Disconnected');
            if (isProcessing) {
                Animations.removeTypingIndicator();
                if (currentAssistantMessage) {
                    currentAssistantMessage.finalize();
                    currentAssistantMessage = null;
                }
                setProcessing(false);
                Voice.setIdle();
            }

            if (reconnectAttempts < MAX_RECONNECT) {
                reconnectAttempts++;
                const delay = Math.min(1000 * reconnectAttempts, 5000);
                console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts})…`);
                setTimeout(connectWebSocket, delay);
            }
        };

        ws.onerror = (err) => {
            console.error('WebSocket error:', err);
        };
    }

    async function recoverPendingMessage(message) {
        if (recoveringMessage || !currentSessionId) return;

        recoveringMessage = true;
        const sessionId = currentSessionId;

        try {
            for (let attempt = 0; attempt < 60; attempt++) {
                await new Promise(resolve => setTimeout(resolve, 2000));
                if (pendingMessage !== message || currentSessionId !== sessionId) return;

                const response = await fetch(`/api/sessions/${sessionId}/messages`);
                if (!response.ok) {
                    throw new Error(`Message recovery failed: ${response.status}`);
                }

                const data = await response.json();
                let userMessageIndex = -1;
                for (let index = data.messages.length - 1; index >= 0; index--) {
                    if (data.messages[index].role === 'user' && data.messages[index].content === message) {
                        userMessageIndex = index;
                        break;
                    }
                }

                if (userMessageIndex >= 0 && data.messages.slice(userMessageIndex + 1).some(item => item.role === 'assistant')) {
                    Chat.loadMessages(data.messages);
                    pendingMessage = null;
                    return;
                }
            }
        } catch (err) {
            console.error('Failed to recover the pending reply:', err);
        } finally {
            recoveringMessage = false;
        }
    }

    function handleServerEvent(data) {
        switch (data.type) {
            case 'session':
                if (currentSessionId && currentSessionId !== data.session_id && pendingMessage !== null) {
                    newChat();
                    Chat.addUserMessage(pendingMessage);
                    const container = document.getElementById('chatMessages');
                    container.appendChild(Animations.createTypingIndicator());
                }
                if (pendingMessage !== null && window.matchMedia('(max-width: 768px)').matches) {
                    panelLeft()?.classList.add('mobile-open');
                }
                currentSessionId = data.session_id;
                loadSessions();
                break;

            case 'session_title':
                // No chatTitle heading in the new layout, but keep for future
                loadSessions();
                break;

            case 'tool_start':
                Chat.addToolStart(data.name, data.args);
                break;

            case 'tool_result':
                Chat.updateToolResult(data.name, data.result);
                break;

            case 'pending_approval':
                pendingMessage = null;
                Animations.removeTypingIndicator();
                handleApprovalRequest(data);
                break;

            case 'token':
                if (!currentAssistantMessage) {
                    Animations.removeTypingIndicator();
                    currentAssistantMessage = Chat.startAssistantMessage();
                }
                currentAssistantMessage.appendToken(data.content);
                break;

            case 'done':
                if (currentAssistantMessage) {
                    currentAssistantMessage.finalize();
                    const responseText = currentAssistantMessage.getRawText();
                    // Only speak if last input was voice AND TTS is enabled
                    if (lastInputWasVoice && ttsEnabled) {
                        speakResponse(responseText);
                    } else {
                        Voice.setIdle();
                    }
                    currentAssistantMessage = null;
                }
                pendingMessage = null;
                setProcessing(false);
                break;

            case 'error':
                pendingMessage = null;
                Animations.removeTypingIndicator();
                if (currentAssistantMessage) {
                    currentAssistantMessage.appendToken(`\n\n⚠ Error: ${data.message}`);
                    currentAssistantMessage.finalize();
                    currentAssistantMessage = null;
                } else {
                    Chat.addAssistantMessage(`⚠ Error: ${data.message}`);
                }
                setProcessing(false);
                Voice.setIdle();
                break;

            case 'pong':
                break;

            default:
                console.log('Unknown event:', data);
        }
    }

    function handleApprovalRequest(data) {
        const card = Chat.addApprovalCard(
            data.approval_id,
            data.tool_name,
            data.args,
            data.description,
        );

        card.approveBtn.addEventListener('click', () => {
            card.approveBtn.disabled = true;
            card.denyBtn.disabled = true;
            card.resolve('✓ Approved — executing…');

            const container = document.getElementById('chatMessages');
            const indicator = Animations.createTypingIndicator();
            container.appendChild(indicator);
            Animations.scrollToBottom(container);

            ws.send(JSON.stringify({
                type: 'approval_response',
                approval_id: data.approval_id,
                approved: true,
            }));
        });

        card.denyBtn.addEventListener('click', () => {
            card.approveBtn.disabled = true;
            card.denyBtn.disabled = true;
            card.resolve('✕ Denied');

            ws.send(JSON.stringify({
                type: 'approval_response',
                approval_id: data.approval_id,
                approved: false,
            }));
        });

        setProcessing(false);
    }

    function sendMessage(content) {
        if (!content.trim() || isProcessing) return;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            Chat.addAssistantMessage('⚠ Not connected to server. Please wait for reconnection…');
            return;
        }

        Chat.addUserMessage(content);
        if (window.matchMedia('(max-width: 768px)').matches) {
            panelLeft()?.classList.add('mobile-open');
        }

        const container = document.getElementById('chatMessages');
        const indicator = Animations.createTypingIndicator();
        container.appendChild(indicator);
        Animations.scrollToBottom(container);

        setProcessing(true);
        pendingMessage = content;

        ws.send(JSON.stringify({
            type: 'message',
            content: content,
            session_id: currentSessionId,
        }));

        const input = chatInput();
        input.value = '';
        input.style.height = 'auto';
        updateSendButton();
    }

    // ════════════════════════════════════════════════
    //  Voice → Transcribe → Send
    // ════════════════════════════════════════════════

    async function transcribeAndSend(audioBlob, mimeType) {
        console.log(`📤 Uploading audio: ${audioBlob.size} bytes, MIME=${mimeType}`);
        Voice.setThinking();

        try {
            // Send as FormData with MIME type
            const formData = new FormData();
            const ext = mimeType?.includes('ogg') ? '.ogg'
                      : mimeType?.includes('mp4') ? '.mp4'
                      : '.webm';
            formData.append('audio', audioBlob, `recording${ext}`);
            if (mimeType) {
                formData.append('mime_type', mimeType);
            }

            const response = await fetch('/api/voice/transcribe', {
                method: 'POST',
                body: formData,
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Could not transcribe audio');
            }

            if (data.text && data.text.trim()) {
                console.log(`📝 Transcript: "${data.text.trim()}"`);
                lastInputWasVoice = true;
                sendMessage(data.text.trim());
            } else {
                Voice.setIdle();
                Chat.addAssistantMessage('🎙️ No speech detected. Try again.');
            }

        } catch (err) {
            console.error('Voice transcription failed:', err);
            Chat.addAssistantMessage(`🎙️ Voice input failed: ${err.message}`);
            Voice.setIdle();
        }
    }

    // ════════════════════════════════════════════════
    //  TTS (Browser speechSynthesis)
    // ════════════════════════════════════════════════

    function speakResponse(text) {
        if (!text || !window.speechSynthesis) {
            Voice.setIdle();
            return;
        }

        // Cancel any existing speech
        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1;

        utterance.onstart = () => {
            Voice.setSpeaking();
        };

        utterance.onend = () => {
            Voice.setIdle();
        };

        utterance.onerror = (e) => {
            console.warn('Speech synthesis error:', e.error);
            Voice.setIdle();
        };

        // Handle autoplay restrictions
        try {
            window.speechSynthesis.speak(utterance);
        } catch (err) {
            console.warn('TTS blocked by autoplay policy:', err);
            Voice.setIdle();
        }
    }

    // ════════════════════════════════════════════════
    //  Sessions
    // ════════════════════════════════════════════════

    async function loadSessions() {
        try {
            const resp = await fetch('/api/sessions');
            const data = await resp.json();
            renderSessions(data.sessions || []);
        } catch (err) {
            console.error('Failed to load sessions:', err);
        }
    }

    function renderSessions(sessions) {
        const list = sessionsList();
        if (!list) return;

        list.innerHTML = '';
        sessions.forEach(session => {
            const item = document.createElement('div');
            item.className = `session-item${session.id === currentSessionId ? ' active' : ''}`;
            item.dataset.sessionId = session.id;
            item.innerHTML = `
                <span class="session-icon">💬</span>
                <span class="session-title">${escapeHtml(session.title || 'New Chat')}</span>
                <button class="session-delete" title="Delete" data-session-id="${session.id}">✕</button>
            `;

            item.addEventListener('click', (e) => {
                if (e.target.closest('.session-delete')) return;
                switchSession(session.id, session.title);
            });

            const delBtn = item.querySelector('.session-delete');
            delBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteSession(session.id);
            });

            list.appendChild(item);
        });
    }

    async function switchSession(sessionId, title) {
        currentSessionId = sessionId;

        document.querySelectorAll('.session-item').forEach(el => {
            el.classList.toggle('active', el.dataset.sessionId === sessionId);
        });

        try {
            const resp = await fetch(`/api/sessions/${sessionId}/messages`);
            const data = await resp.json();
            Chat.loadMessages(data.messages || []);
        } catch (err) {
            console.error('Failed to load messages:', err);
        }

        closeMobilePanel();
    }

    function newChat() {
        currentSessionId = null;
        Chat.clearMessages();

        const container = document.getElementById('chatMessages');
        if (!document.getElementById('welcomeScreen')) {
            container.innerHTML = createWelcomeHTML();
            bindSuggestionChips();
        }
        Chat.showWelcome();

        document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
        chatInput().focus();
        closeMobilePanel();
    }

    async function deleteSession(sessionId) {
        try {
            await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
            if (currentSessionId === sessionId) {
                newChat();
            }
            loadSessions();
        } catch (err) {
            console.error('Failed to delete session:', err);
        }
    }

    // ════════════════════════════════════════════════
    //  UI Helpers
    // ════════════════════════════════════════════════

    function setProcessing(processing) {
        isProcessing = processing;
        Animations.setLogoProcessing(processing);

        const input = chatInput();
        const btn = sendBtn();
        if (processing) {
            input.disabled = true;
            btn.disabled = true;
            input.placeholder = 'EDITH is thinking…';
        } else {
            input.disabled = false;
            btn.disabled = false;
            input.placeholder = 'Type a command…';
            input.focus();
        }
        updateSendButton();
    }

    function updateSendButton() {
        const btn = sendBtn();
        const input = chatInput();
        const hasText = !!(input && input.value.trim());

        if (hasText && !isProcessing) {
            btn.classList.add('active');
            btn.removeAttribute('disabled');
        } else {
            btn.classList.remove('active');
            btn.setAttribute('disabled', '');
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function closeMobilePanel() {
        const pl = panelLeft();
        if (pl) pl.classList.remove('mobile-open');
    }

    function createWelcomeHTML() {
        return `
            <div class="welcome-screen" id="welcomeScreen">
                <div class="welcome-logo">
                    <svg viewBox="0 0 60 60" fill="none">
                        <circle cx="30" cy="30" r="27" stroke="url(#welcGrad2)" stroke-width="1.5" opacity="0.3">
                            <animate attributeName="r" values="27;29;27" dur="3s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="30" cy="30" r="18" stroke="url(#welcGrad2)" stroke-width="1" opacity="0.5">
                            <animate attributeName="r" values="18;20;18" dur="2.5s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="30" cy="30" r="7" fill="url(#welcGrad2)">
                            <animate attributeName="r" values="7;9;7" dur="2s" repeatCount="indefinite"/>
                        </circle>
                        <defs>
                            <linearGradient id="welcGrad2" x1="0" y1="0" x2="60" y2="60">
                                <stop offset="0%" stop-color="#00e5ff"/>
                                <stop offset="100%" stop-color="#2979ff"/>
                            </linearGradient>
                        </defs>
                    </svg>
                </div>
                <h2 class="welcome-title">Hello, I'm <span class="gradient-text">EDITH</span></h2>
                <p class="welcome-subtitle">Your Enhanced Digital Intelligence Technology Hub</p>
                <div class="welcome-suggestions">
                    <button class="suggestion-chip" data-message="Set my volume to 50%">🔊 Volume 50%</button>
                    <button class="suggestion-chip" data-message="Search the web for latest AI news">🌐 AI News</button>
                    <button class="suggestion-chip" data-message="Open google.com in my browser">🌍 Open Google</button>
                    <button class="suggestion-chip" data-message="Find Python files on my Desktop">📂 Find files</button>
                </div>
            </div>
        `;
    }

    // ════════════════════════════════════════════════
    //  Settings
    // ════════════════════════════════════════════════

    async function loadSettings() {
        try {
            const resp = await fetch('/api/settings');
            const data = await resp.json();
            if (modelBadge()) modelBadge().textContent = data.ollama_model || 'Unknown';
            const modelInput = document.getElementById('settingModel');
            const urlInput = document.getElementById('settingOllamaUrl');
            const ttsInput = document.getElementById('settingTTS');
            if (modelInput) modelInput.value = data.ollama_model || '';
            if (urlInput) urlInput.value = data.ollama_base_url || '';
            if (ttsInput) ttsInput.value = data.tts_engine || '';
        } catch (err) {
            if (modelBadge()) modelBadge().textContent = 'Offline';
        }
    }

    // ════════════════════════════════════════════════
    //  Health Status Polling
    // ════════════════════════════════════════════════

    async function pollHealth() {
        try {
            const resp = await fetch('/api/health');
            const data = await resp.json();
            Animations.updateStatusCards(data);
        } catch (err) {
            console.warn('Health check failed:', err);
        }
    }

    // ════════════════════════════════════════════════
    //  Event Bindings
    // ════════════════════════════════════════════════

    function bindSuggestionChips() {
        document.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const msg = chip.dataset.message;
                if (msg) {
                    lastInputWasVoice = false;
                    sendMessage(msg);
                }
            });
        });
    }

    function init() {
        // Connect WebSocket
        connectWebSocket();

        // Load initial data
        loadSessions();
        loadSettings();

        // ── Check microphone availability ──
        if (Voice.isSupported()) {
            Animations.updateMicStatus(true);
        } else {
            Animations.updateMicStatus(false);
        }

        // ── Health polling ──
        pollHealth();
        setInterval(pollHealth, 30000); // every 30s

        // ── Send Button ──
        sendBtn().addEventListener('click', () => {
            lastInputWasVoice = false;
            sendMessage(chatInput().value);
        });

        // ── Input ──
        const input = chatInput();
        input.addEventListener('input', () => {
            updateSendButton();
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 100) + 'px';
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                lastInputWasVoice = false;
                sendMessage(input.value);
            }
        });

        // ── New Chat ──
        newChatBtn().addEventListener('click', newChat);

        // ── Delete Chat ──
        deleteChatBtn().addEventListener('click', () => {
            if (currentSessionId) {
                deleteSession(currentSessionId);
            }
        });

        // ── Suggestion Chips ──
        bindSuggestionChips();

        // ── Voice: Push-to-Talk ──
        const vBtn = document.getElementById('voiceBtn');
        if (vBtn) {
            vBtn.addEventListener('click', async () => {
                await Voice.toggle();
            });
        }

        // ── Voice: Cancel ──
        const cancelBtn = document.getElementById('cancelBtn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                Voice.cancel();
            });
        }

        // ── Voice: Recording Complete Callback ──
        Voice.onRecordingComplete = (blob, mimeType) => {
            transcribeAndSend(blob, mimeType);
        };

        Voice.onError = (msg) => {
            Chat.addAssistantMessage(`🎙️ ${msg}`);
        };

        // ── TTS Toggle ──
        const ttsToggle = document.getElementById('ttsToggle');
        if (ttsToggle) {
            ttsToggle.addEventListener('click', () => {
                ttsEnabled = !ttsEnabled;
                ttsToggle.classList.toggle('enabled', ttsEnabled);
                ttsToggle.textContent = ttsEnabled ? '🔈 Voice ON' : '🔇 Voice OFF';
            });
        }

        // ── Sessions Drawer Toggle ──
        const sessToggle = document.getElementById('sessionsToggle');
        const sessDrawer = document.getElementById('sessionsDrawer');
        if (sessToggle && sessDrawer) {
            sessToggle.addEventListener('click', () => {
                sessDrawer.classList.toggle('open');
            });
        }

        // ── Settings Modal ──
        settingsBtn().addEventListener('click', () => {
            settingsModal().classList.add('open');
        });
        settingsClose().addEventListener('click', () => {
            settingsModal().classList.remove('open');
        });
        settingsModal().addEventListener('click', (e) => {
            if (e.target === settingsModal()) {
                settingsModal().classList.remove('open');
            }
        });

        // ── Mobile Panel Toggle ──
        menuToggle().addEventListener('click', () => {
            const pl = panelLeft();
            if (pl) pl.classList.toggle('mobile-open');
        });

        // ── Heartbeat ──
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);

        console.log('⚡ EDITH Command Center initialized');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return {
        sendMessage,
        newChat,
        switchSession,
    };
})();

/**
 * EDITH — Animations & Visual Effects Module
 *
 * Manages the reactor orb state, typing indicators, status updates,
 * and wires up voice state changes to visual feedback.
 */

const Animations = (() => {

    // ── State labels for the voice status indicator ──
    const STATE_LABELS = {
        idle:            'SYSTEM READY',
        requesting_mic:  'REQUESTING MIC',
        listening:       'LISTENING',
        processing:      'PROCESSING',
        thinking:        'THINKING',
        speaking:        'SPEAKING',
        error:           'ERROR',
    };

    // ════════════════════════════════════════════════
    //  Reactor Orb
    // ════════════════════════════════════════════════

    function setReactorState(state) {
        const orb = document.getElementById('reactorOrb');
        if (orb) {
            orb.setAttribute('data-state', state);
        }

        // Update voice status label
        const label = document.getElementById('voiceStatusLabel');
        if (label) {
            label.setAttribute('data-state', state);
            label.textContent = STATE_LABELS[state] || state.toUpperCase();
        }
    }

    // ════════════════════════════════════════════════
    //  Entrance Animation
    // ════════════════════════════════════════════════

    function animateIn(element, delay = 0) {
        element.style.opacity = '0';
        element.style.transform = 'translateY(8px)';

        setTimeout(() => {
            element.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            element.style.opacity = '1';
            element.style.transform = 'translateY(0)';
        }, delay);
    }

    // ════════════════════════════════════════════════
    //  Scroll
    // ════════════════════════════════════════════════

    function scrollToBottom(container, smooth = true) {
        if (smooth) {
            container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
        } else {
            container.scrollTop = container.scrollHeight;
        }
    }

    // ════════════════════════════════════════════════
    //  Typing Indicator
    // ════════════════════════════════════════════════

    function createTypingIndicator() {
        const div = document.createElement('div');
        div.className = 'typing-indicator';
        div.id = 'typingIndicator';
        div.innerHTML = `
            <div class="message-avatar" style="background: rgba(0, 229, 255, 0.1); border: 1px solid rgba(0, 229, 255, 0.2); color: var(--holo-cyan);">
                E
            </div>
            <div class="typing-dots">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        `;
        return div;
    }

    function removeTypingIndicator() {
        const el = document.getElementById('typingIndicator');
        if (el) {
            el.style.opacity = '0';
            el.style.transform = 'translateY(-4px)';
            el.style.transition = 'all 0.2s ease';
            setTimeout(() => el.remove(), 200);
        }
    }

    // ════════════════════════════════════════════════
    //  Logo Pulse (processing state)
    // ════════════════════════════════════════════════

    function setLogoProcessing(active) {
        const logo = document.getElementById('logoIcon');
        if (!logo) return;

        if (active) {
            logo.style.animation = 'logo-pulse 0.8s ease-in-out infinite';
        } else {
            logo.style.animation = 'logo-pulse 3s ease-in-out infinite';
        }
    }

    // ════════════════════════════════════════════════
    //  Connection Status
    // ════════════════════════════════════════════════

    function setStatus(status, text) {
        // Update WebSocket status card
        const dot = document.getElementById('statusConnectionDot');
        const val = document.getElementById('statusConnectionValue');

        if (dot) {
            dot.className = 'status-dot-inline';
            if (status === 'online') dot.classList.add('online');
            else if (status === 'error') dot.classList.add('error');
        }

        if (val) {
            val.textContent = text || status;
        }
    }

    // ════════════════════════════════════════════════
    //  System Status Cards
    // ════════════════════════════════════════════════

    function updateStatusCards(health) {
        if (!health || !health.subsystems) return;

        const subs = health.subsystems;

        // Ollama
        const ollamaOk = subs.ollama?.status === 'connected';
        _setCardStatus('statusOllamaDot', 'statusOllamaValue',
            ollamaOk ? 'online' : 'error',
            ollamaOk
                ? `Connected · ${subs.ollama.model}`
                : `Model not found · run: ollama pull ${subs.ollama?.model || '?'}`
        );

        // Whisper
        _setCardStatus('statusWhisperDot', 'statusWhisperValue',
            subs.whisper?.status === 'ready' ? 'online' : 'error',
            subs.whisper?.status === 'ready' ? `Ready · ${subs.whisper.model_size}` : 'Unavailable'
        );

        // FFmpeg
        _setCardStatus('statusFFmpegDot', 'statusFFmpegValue',
            subs.ffmpeg?.status === 'available' ? 'online' : 'error',
            subs.ffmpeg?.status === 'available' ? 'Available' : 'Missing — install FFmpeg'
        );

        // TTS
        _setCardStatus('statusTTSDot', 'statusTTSValue',
            subs.tts?.status === 'available' ? 'online' : 'warning',
            subs.tts?.status === 'available' ? `${subs.tts.engine}` : 'Unavailable'
        );
    }

    function _setCardStatus(dotId, valId, statusClass, text) {
        const dot = document.getElementById(dotId);
        const val = document.getElementById(valId);
        if (dot) {
            dot.className = 'status-dot-inline';
            dot.classList.add(statusClass);
        }
        if (val) val.textContent = text;
    }

    function updateMicStatus(available) {
        _setCardStatus('statusMicDot', 'statusMicValue',
            available ? 'online' : 'error',
            available ? 'Available' : 'Not available'
        );
    }

    // ════════════════════════════════════════════════
    //  Shake (error feedback)
    // ════════════════════════════════════════════════

    function shake(element) {
        element.style.animation = 'none';
        element.offsetHeight; // reflow
        element.style.animation = 'shake 0.4s ease';
        setTimeout(() => { element.style.animation = ''; }, 400);
    }

    // ════════════════════════════════════════════════
    //  Voice State Change Listener
    // ════════════════════════════════════════════════

    // Auto-bind: when voice state changes, update the reactor orb
    document.addEventListener('voicestatechange', (e) => {
        const { state } = e.detail;
        setReactorState(state);

        // Update PTT button
        const pttBtn = document.getElementById('voiceBtn');
        const cancelBtn = document.getElementById('cancelBtn');

        if (pttBtn) {
            pttBtn.setAttribute('data-recording', state === 'listening' ? 'true' : 'false');
            pttBtn.title = state === 'listening'
                ? 'Stop English recording and send'
                : 'Start English voice recording';
            pttBtn.setAttribute(
                'aria-label',
                state === 'listening' ? 'Stop English recording and send' : 'Start English voice recording',
            );
        }

        if (cancelBtn) {
            cancelBtn.classList.toggle('visible', state === 'listening');
        }
    });


    return {
        setReactorState,
        animateIn,
        scrollToBottom,
        createTypingIndicator,
        removeTypingIndicator,
        setLogoProcessing,
        setStatus,
        updateStatusCards,
        updateMicStatus,
        shake,
    };
})();

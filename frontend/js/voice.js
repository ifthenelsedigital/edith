/**
 * EDITH — Voice State Machine
 *
 * A robust finite-state machine for browser-side voice recording.
 *
 * States:
 *   idle            – ready, mic not active
 *   requesting_mic  – awaiting getUserMedia permission
 *   listening       – actively recording
 *   processing      – recording stopped, uploading to backend
 *   thinking        – waiting for LLM response
 *   speaking        – TTS playing assistant response
 *   error           – recoverable error, auto-resets to idle
 *
 * Guarantees:
 *   - Mic stream is ALWAYS released when exiting 'listening'
 *   - Timeout: auto-stop after MAX_RECORD_SECONDS
 *   - Empty recordings (< MIN_BLOB_BYTES) are caught
 *   - Cancel discards recording and returns to idle
 *   - Emits 'voicestatechange' CustomEvents on document
 *
 * Architecture note — Wake Word:
 *   A future WakeWordDetector can hook into the 'idle' state to open
 *   a low-power audio stream, then call Voice.startRecording() when
 *   the wake word is detected.
 */

const Voice = (() => {
    // ── Constants ──
    const MAX_RECORD_SECONDS = 30;
    const MIN_BLOB_BYTES = 1000; // ~1 KB — below this is likely silence

    // ── State ──
    let state = 'idle';
    let mediaRecorder = null;
    let audioChunks = [];
    let stream = null;
    let recordingTimer = null;
    let currentMimeType = null;

    // ── Callbacks ──
    // Set by the app to handle completed recordings
    let _onRecordingComplete = null; // (blob, mimeType) => void
    let _onError = null; // (errorMsg) => void

    // ════════════════════════════════════════════════
    //  State Management
    // ════════════════════════════════════════════════

    function setState(newState, detail) {
        const oldState = state;
        state = newState;
        console.log(`🎙️ Voice: ${oldState} → ${newState}${detail ? ` (${detail})` : ''}`);

        // Emit custom event for UI binding
        document.dispatchEvent(new CustomEvent('voicestatechange', {
            detail: { state: newState, previousState: oldState, info: detail || '' },
        }));
    }

    function getState() {
        return state;
    }

    // ════════════════════════════════════════════════
    //  Capability Check
    // ════════════════════════════════════════════════

    function isSupported() {
        return !!(
            navigator.mediaDevices &&
            navigator.mediaDevices.getUserMedia &&
            window.MediaRecorder
        );
    }

    // ════════════════════════════════════════════════
    //  MIME Type Detection
    // ════════════════════════════════════════════════

    function getSupportedMimeType() {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4',
        ];
        for (const type of types) {
            if (MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }
        return 'audio/webm'; // fallback
    }

    function getMimeType() {
        return currentMimeType;
    }

    // ════════════════════════════════════════════════
    //  Recording Control
    // ════════════════════════════════════════════════

    async function startRecording() {
        if (state !== 'idle') {
            console.warn(`Voice: cannot start recording from state '${state}'`);
            return false;
        }

        if (!isSupported()) {
            setState('error', 'Browser does not support audio recording');
            _handleError('Voice recording is not supported in this browser.');
            return false;
        }

        setState('requesting_mic');

        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true,
                },
            });
        } catch (err) {
            const msg = err.name === 'NotAllowedError'
                ? 'Microphone permission denied. Please allow access in your browser settings.'
                : `Microphone error: ${err.message}`;
            setState('error', msg);
            _handleError(msg);
            return false;
        }

        // ── Set up MediaRecorder ──
        audioChunks = [];
        currentMimeType = getSupportedMimeType();

        try {
            mediaRecorder = new MediaRecorder(stream, { mimeType: currentMimeType });
        } catch (err) {
            // Fallback: let browser choose
            console.warn('Voice: specified MIME not supported, using default');
            mediaRecorder = new MediaRecorder(stream);
            currentMimeType = mediaRecorder.mimeType || 'audio/webm';
        }

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        };

        mediaRecorder.onerror = (event) => {
            console.error('MediaRecorder error:', event.error);
            _releaseStream();
            setState('error', 'Recording failed');
            _handleError('Recording failed unexpectedly.');
        };

        mediaRecorder.start(250); // collect data every 250ms
        setState('listening');

        // ── Auto-stop timeout ──
        recordingTimer = setTimeout(() => {
            console.log(`Voice: auto-stopping after ${MAX_RECORD_SECONDS}s`);
            stopRecording();
        }, MAX_RECORD_SECONDS * 1000);

        return true;
    }

    function stopRecording() {
        return new Promise((resolve) => {
            if (state !== 'listening' || !mediaRecorder) {
                resolve(null);
                return;
            }

            // Clear auto-stop timer
            if (recordingTimer) {
                clearTimeout(recordingTimer);
                recordingTimer = null;
            }

            setState('processing', 'assembling audio');

            mediaRecorder.onstop = () => {
                _releaseStream();

                const blob = new Blob(audioChunks, { type: currentMimeType });
                audioChunks = [];

                if (blob.size < MIN_BLOB_BYTES) {
                    console.warn(`Voice: recording too small (${blob.size} bytes), likely silence`);
                    setState('idle');
                    _handleError('No speech detected — try speaking closer to the microphone.');
                    resolve(null);
                    return;
                }

                console.log(`Voice: recorded ${blob.size} bytes (${currentMimeType})`);

                // Fire the callback
                if (_onRecordingComplete) {
                    _onRecordingComplete(blob, currentMimeType);
                }

                resolve(blob);
            };

            try {
                mediaRecorder.stop();
            } catch (err) {
                console.error('Voice: error stopping MediaRecorder:', err);
                _releaseStream();
                setState('error', 'Failed to stop recording');
                _handleError('Failed to stop recording.');
                resolve(null);
            }
        });
    }

    function cancel() {
        // Discard recording and return to idle
        if (recordingTimer) {
            clearTimeout(recordingTimer);
            recordingTimer = null;
        }

        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            // Temporarily remove onstop to avoid processing
            mediaRecorder.onstop = () => {};
            try {
                mediaRecorder.stop();
            } catch (_) { /* ignore */ }
        }

        _releaseStream();
        audioChunks = [];
        setState('idle', 'cancelled');
    }

    /**
     * Toggle: if idle → start, if listening → stop and submit.
     * Returns 'recording' if started, a Blob if stopped, or null on error.
     */
    async function toggle() {
        if (state === 'listening') {
            return await stopRecording();
        } else if (state === 'idle') {
            const started = await startRecording();
            return started ? 'recording' : null;
        }
        // In any other state, ignore
        return null;
    }

    // ════════════════════════════════════════════════
    //  State Notifications (called by App)
    // ════════════════════════════════════════════════

    function setThinking() {
        if (state === 'processing') {
            setState('thinking');
        }
    }

    function setSpeaking() {
        setState('speaking');
    }

    function setIdle() {
        setState('idle');
    }

    // ════════════════════════════════════════════════
    //  TTS Playback
    // ════════════════════════════════════════════════

    function playAudio(audioData) {
        const audio = new Audio();
        if (audioData instanceof Blob) {
            audio.src = URL.createObjectURL(audioData);
        } else {
            audio.src = audioData;
        }
        audio.play().catch(err => {
            console.error('Audio playback failed:', err);
        });
        return audio;
    }

    // ════════════════════════════════════════════════
    //  Internal Helpers
    // ════════════════════════════════════════════════

    function _releaseStream() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        mediaRecorder = null;
    }

    function _handleError(msg) {
        if (_onError) {
            _onError(msg);
        }
        // Auto-recover to idle after a brief delay
        setTimeout(() => {
            if (state === 'error') {
                setState('idle', 'auto-recovered');
            }
        }, 3000);
    }

    // ════════════════════════════════════════════════
    //  Public API
    // ════════════════════════════════════════════════

    return {
        // Control
        startRecording,
        stopRecording,
        cancel,
        toggle,

        // State
        getState,
        setThinking,
        setSpeaking,
        setIdle,

        // Info
        isSupported,
        getMimeType,
        playAudio,

        // Callbacks
        set onRecordingComplete(fn) { _onRecordingComplete = fn; },
        set onError(fn) { _onError = fn; },

        // Legacy compat
        get isRecording() { return state === 'listening'; },
    };
})();

// Voice capture is local until a separate, explicit paid-request approval.
export const SILENCE_DURATION_MS = 900;
export const SILENCE_THRESHOLD_RMS = 0.025;
export const SILENCE_CHECK_INTERVAL_MS = 100;
const MAX_RECORDING_MS = 45000;
const NO_SPEECH_TIMEOUT_MS = 8000;
const MAX_AUDIO_BYTES = 6 * 1024 * 1024;
const MAX_CONTINUOUS_TURNS = 5;
const $ = id => document.getElementById(id);

export class VoiceController {
    constructor({request, onText, onState, onError, onMessage, isBusy}) {
        Object.assign(this, {request, onText, onState, onError, onMessage, isBusy});
        this.generation = 0;
        this.muted = false;
        this.processing = false;
        this.turns = 0;
        $('microphone').onclick = () => this.toggle();
        $('test-mic').onclick = () => this.start(true);
        $('voice-finish').onclick = () => this.finishRecording(false);
        $('mute').onclick = () => {
            this.muted = !this.muted;
            $('mute').textContent = this.muted ? 'Unmute' : 'Mute';
            $('mute').setAttribute('aria-pressed', String(this.muted));
            if (this.muted) this.interrupt();
        };
        document.addEventListener('keydown', event => {
            if (event.repeat || event.target.closest('input,textarea,select,[contenteditable="true"]') || document.querySelector('dialog[open]')) return;
            const active = this.recorder || this.audio || this.processing || this.preparing;
            if (event.code === 'Space' && (active || !event.target.closest('button,a'))) { event.preventDefault(); this.toggle(); }
            if (event.code === 'Escape' && (this.recorder || this.audio || this.processing || this.preparing)) {
                event.preventDefault(); this.interrupt();
            }
        });
        window.addEventListener('pagehide', () => this.interrupt());
        this.notice('Microphone inactive. Audio stays local until you approve transcription.');
    }

    configure(status) {
        this.config = status;
        $('elevenlabs-state').textContent = status.demo_blocked ? 'Demo blocked' : status.last_request==='error' ? 'Last request failed' : status.verified_connection ? 'Last request OK' : status.key_configured ? 'Key set · untested' : 'Key missing';
        $('elevenlabs-state').title = status.message;
    }

    notice(text) { $('voice-status').textContent = text; }

    async consent(title, description) {
        const dialog = $('voice-consent');
        if (dialog.open) return false;
        $('voice-consent-title').textContent = title;
        $('voice-consent-text').textContent = description;
        return new Promise(resolve => {
            const finish = approved => {
                clearTimeout(timeout);
                dialog.oncancel = null;
                $('voice-approve').onclick = null;
                $('voice-decline').onclick = null;
                dialog.close();
                resolve(approved);
            };
            const timeout = setTimeout(() => finish(false), 120000);
            dialog.oncancel = event => { event.preventDefault(); finish(false); };
            $('voice-approve').onclick = () => finish(true);
            $('voice-decline').onclick = () => finish(false);
            dialog.showModal();
        });
    }

    async toggle() {
        if (this.audio) {
            this.interrupt();
            if (!this.isBusy()) await this.start(false);
        } else if (this.recorder || this.preparing || this.processing) {
            this.interrupt();
        } else {
            this.turns = 0;
            await this.start(false);
        }
    }

    async start(localTest = false) {
        if (this.isBusy() || this.recorder || this.audio || this.preparing || this.processing) {
            this.notice('Wait for the active request, or stop it before recording.');
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !window.AudioContext) {
            this.fail('This browser does not support the required microphone, MediaRecorder and Web Audio APIs. Use current Edge or Chrome on localhost.');
            return;
        }
        const generation = ++this.generation;
        this.preparing = true;
        this.notice('Requesting microphone permission…');
        try {
            const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
            if (generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
            this.stream = stream;
            const formats = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
            const mime = formats.find(type => MediaRecorder.isTypeSupported(type));
            if (!mime) throw new Error('This browser cannot record WebM, Ogg or MP4 audio.');
            this.context = new AudioContext();
            await this.context.resume();
            if (generation !== this.generation) { this.releaseCapture(); return; }
            this.source = this.context.createMediaStreamSource(stream);
            this.analyser = this.context.createAnalyser();
            this.analyser.fftSize = 1024;
            this.source.connect(this.analyser); // Never connect the microphone to speakers.
            const samples = new Float32Array(this.analyser.fftSize);
            const recorder = new MediaRecorder(stream, {mimeType: mime});
            this.recorder = recorder;
            this.discard = false;
            let chunks = [], bytes = 0, speechFrames = 0, lastSpeech = performance.now();
            const started = performance.now();
            recorder.ondataavailable = event => {
                if (event.data.size) { chunks.push(event.data); bytes += event.data.size; }
                if (bytes > MAX_AUDIO_BYTES) { this.finishRecording(true); this.fail('Recording reached the 6 MB limit. Nothing was sent.'); }
            };
            recorder.onerror = () => { this.finishRecording(true); this.fail('Microphone recording failed. Check your input device and try again.'); };
            recorder.onstop = async () => {
                const discarded = this.discard || generation !== this.generation;
                const blob = discarded ? null : new Blob(chunks, {type: recorder.mimeType});
                chunks = [];
                this.recorder = null;
                this.releaseCapture();
                if (discarded) return;
                if (!blob?.size || speechFrames < 3) {
                    this.notice('No clear speech detected. Nothing was sent.');
                    this.onState('idle');
                    return;
                }
                if (localTest) {
                    this.notice('Local microphone test complete. Recorded audio was discarded; no API request was made.');
                    this.onState('idle');
                    return;
                }
                await this.handleRecording(blob, recorder.mimeType, generation);
            };
            stream.getAudioTracks()[0].onended = () => {
                if (this.recorder?.state === 'recording') { this.finishRecording(true); this.fail('The microphone disconnected. No audio was sent.'); }
            };
            recorder.start(250);
            $('microphone').textContent = 'Stop mic';
            $('microphone').setAttribute('aria-pressed', 'true');
            $('voice-finish').disabled = false;
            $('mic-state').textContent = localTest ? 'Testing locally' : 'Recording';
            this.notice(localTest ? 'Local microphone test — speak, then pause. No upload.' : 'Listening… pause for about 900 ms to finish. No live transcription.');
            this.onState('listening');
            // Timed polling continues without requestAnimationFrame in background tabs.
            // Browser suspension/throttling can still delay the approximately 900 ms boundary.
            this.interval = setInterval(() => {
                this.analyser.getFloatTimeDomainData(samples);
                const rms = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
                $('audio-level').value = Math.min(0.2, rms);
                const now = performance.now();
                if (rms >= SILENCE_THRESHOLD_RMS) { speechFrames++; lastSpeech = now; }
                if ((speechFrames >= 3 && now - lastSpeech >= SILENCE_DURATION_MS) || now - started >= MAX_RECORDING_MS || (speechFrames < 3 && now - started >= NO_SPEECH_TIMEOUT_MS)) {
                    this.finishRecording(false);
                }
            }, SILENCE_CHECK_INTERVAL_MS);
        } catch (error) {
            this.releaseCapture();
            const descriptions = {NotAllowedError: 'Microphone permission was denied. Allow microphone access for localhost in your browser settings.',
                NotFoundError: 'No microphone was detected. Connect or enable an input device.',
                NotReadableError: 'The microphone could not be opened. Another application may be using it.'};
            this.fail(descriptions[error.name] || error.message || 'Microphone recording failed.');
        } finally {
            this.preparing = false;
        }
    }

    releaseCapture() {
        clearInterval(this.interval);
        this.interval = null;
        this.source?.disconnect();
        this.source = null;
        this.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
        this.stream = null;
        this.context?.close().catch(() => {});
        this.context = null;
        this.analyser = null;
        $('audio-level').value = 0;
        $('mic-state').textContent = 'Inactive';
        $('microphone').textContent = 'Mic';
        $('microphone').setAttribute('aria-pressed', 'false');
        $('voice-finish').disabled = true;
    }

    finishRecording(discard) {
        this.discard = discard;
        clearInterval(this.interval);
        if (this.recorder?.state === 'recording') this.recorder.stop();
        // Stop capture immediately; queued MediaRecorder data is handled by onstop.
        this.releaseCapture();
    }

    interrupt() {
        this.generation++;
        $('voice-continue').checked = false;
        this.finishRecording(true);
        if (this.audio) {
            this.audio.pause();
            this.audio.src = '';
            this.audio = null;
        }
        this.endPlayback?.();
        this.endPlayback = null;
        if (this.playbackUrl) URL.revokeObjectURL(this.playbackUrl);
        this.playbackUrl = null;
        this.notice(this.processing ? 'Voice interrupted. An already-submitted request may still finish and consume credits; it will not start a new action.' : 'Voice stopped. Microphone inactive.');
        this.onState(this.isBusy() ? 'thinking' : 'idle');
    }

    fail(message) {
        $('voice-continue').checked = false;
        this.notice(message);
        this.onError(message);
    }

    async handleRecording(blob, mime, generation) {
        if (this.config?.demo_blocked || !this.config?.key_configured) {
            this.fail(this.config?.demo_blocked ? 'Demo mode blocks ElevenLabs calls. Your local recording was discarded. Text chat and the local mic test still work.' : 'ElevenLabs key is missing. Your local recording was discarded; text chat still works.');
            return;
        }
        this.onState('idle');
        this.notice('Recording stopped. Awaiting transcription approval.');
        const approved = await this.consent('Approve ElevenLabs transcription?', 'Send this recording to ElevenLabs Scribe? This uses account credits even on the free tier and may incur charges. JARVIS keeps no recording on disk; ElevenLabs applies its own retention policy. Declining discards the recording.');
        if (!approved || generation !== this.generation) { this.notice('Recording discarded. No transcription request made.'); return; }
        this.processing = true;
        let outcome;
        try {
            this.notice('Transcribing…');
            this.onState('thinking');
            const buffer = new Uint8Array(await blob.arrayBuffer());
            let binary = '';
            for (let offset = 0; offset < buffer.length; offset += 32768) binary += String.fromCharCode(...buffer.subarray(offset, offset + 32768));
            const transcript = await this.request('/api/voice/transcribe', {audio: btoa(binary), mime, approved: true});
            if (generation !== this.generation) return;
            if (!transcript.ok) throw new Error(transcript.spoken);
            $('elevenlabs-state').textContent = 'Last request OK';
            this.onMessage('Transcription: ' + transcript.transcript);
            this.notice('Transcript received. Processing your request…');
            outcome = await this.onText(transcript.transcript);
        } catch (error) {
            if (generation === this.generation) { $('elevenlabs-state').textContent='Request failed'; this.fail(error.message); }
        } finally {
            this.processing = false;
            if (generation !== this.generation && !this.isBusy()) this.onState('idle');
        }
        if (generation !== this.generation || !outcome?.ok) return;
        this.turns++;
        if (!this.muted && outcome.job) await this.speak(outcome.job);
        if (generation === this.generation && $('voice-continue').checked && this.turns < MAX_CONTINUOUS_TURNS && !outcome.confirmation && !outcome.needs_tasks) {
            this.notice('Continuing the explicitly enabled voice session…');
            setTimeout(() => { if (generation === this.generation) this.start(false); }, 400);
        } else if (this.turns >= MAX_CONTINUOUS_TURNS) {
            $('voice-continue').checked = false;
            this.notice('Five-turn voice session finished. Press Mic to start again.');
        }
    }

    async speak(job) {
        if (this.muted) { this.notice('Speech is muted. Choose Unmute before requesting speech.'); return; }
        if (this.isBusy() || this.processing || this.recorder || this.preparing || this.audio) {
            this.notice('Finish the active request, or stop recording/playback before requesting speech.');
            return;
        }
        if (this.config?.demo_blocked || !this.config?.key_configured || !this.config?.voice_configured) {
            this.fail('Speech needs non-demo mode, a server-side ElevenLabs key and a voice ID. Text output remains available.');
            return;
        }
        const generation = this.generation;
        const approved = await this.consent('Approve ElevenLabs speech?', 'Generate speech for this assistant response using ElevenLabs? This consumes credits even on the free tier and may incur charges. Long answers and code use a short spoken notice instead. Each retry needs new approval.');
        if (!approved || this.muted || generation !== this.generation) return;
        this.finishRecording(true);
        this.processing = true;
        this.onState('thinking');
        this.notice('Generating speech… microphone inactive.');
        let response;
        try {
            response = await this.request('/api/voice/speak', {job, approved: true});
            if (generation !== this.generation) return;
            if (!response.ok) throw new Error(response.spoken);
            $('elevenlabs-state').textContent = 'Last request OK';
            if (!response.audio) throw new Error('Speech audio expired or was already retrieved. A new request needs approval.');
        } catch (error) {
            if (generation === this.generation) { $('elevenlabs-state').textContent='Request failed'; this.fail(error.message); }
            return;
        } finally {
            this.processing = false;
            if (generation !== this.generation && !this.isBusy()) this.onState('idle');
        }
        if (generation !== this.generation) return;
        let bytes;
        try { bytes = Uint8Array.from(atob(response.audio), char => char.charCodeAt(0)); }
        catch { this.fail('Speech audio could not be decoded. Text remains available.'); return; }
        const playbackUrl = URL.createObjectURL(new Blob([bytes], {type: response.mime}));
        this.playbackUrl = playbackUrl;
        const audio = new Audio(playbackUrl);
        this.audio = audio;
        try {
            await new Promise((resolve, reject) => {
                this.endPlayback = resolve;
                audio.onended = resolve;
                audio.onerror = () => reject(new Error('Speech playback failed. Check your output device; text remains available.'));
                audio.onplaying = () => {
                    if (generation === this.generation && this.audio === audio) {
                        this.onState('speaking');
                        this.notice('Speaking… microphone inactive. Mic, Space or Escape interrupts.');
                    }
                };
                audio.play().catch(() => reject(new Error('The browser blocked audio playback. Allow sound for localhost; text remains available.')));
            });
            if (generation === this.generation) { this.onState('idle'); this.notice('Speech finished. Microphone inactive.'); }
        } catch (error) { if (generation === this.generation) this.fail(error.message); }
        finally {
            audio.pause(); audio.src = '';
            if (this.audio === audio) this.audio = null;
            URL.revokeObjectURL(playbackUrl);
            if(this.playbackUrl===playbackUrl){this.playbackUrl=null;this.endPlayback=null;}
        }
    }
}

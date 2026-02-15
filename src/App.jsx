import { useEffect, useRef, useState, useCallback } from 'react';
import {
  LiveAvatarSession,
  SessionEvent,
  SessionState,
  AgentEventsEnum,
  VoiceChatEvent,
} from '@heygen/liveavatar-web-sdk';
import './App.css';

const API_BASE = 'http://localhost:5000';

function App() {
  const sessionRef = useRef(null);
  const sessionIdRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);

  const [sessionState, setSessionState] = useState(SessionState.INACTIVE);
  const [isStreamReady, setIsStreamReady] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isAvatarTalking, setIsAvatarTalking] = useState(false);
  const [isUserTalking, setIsUserTalking] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [textInput, setTextInput] = useState('');
  const [avatarText, setAvatarText] = useState('');
  const [userText, setUserText] = useState('');

  // ── Fetch session token from backend ──────────────
  const fetchToken = async () => {
    const res = await fetch(`${API_BASE}/api/session/token`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || !data.session_token) {
      throw new Error(data.error || 'Failed to get session token');
    }
    sessionIdRef.current = data.session_id;
    return data.session_token;
  };

  // ── Start session ─────────────────────────────────
  const startSession = useCallback(async () => {
    setIsLoading(true);
    try {
      const token = await fetchToken();

      const session = new LiveAvatarSession(token, {
        voiceChat: true,
      });

      // Session lifecycle
      session.on(SessionEvent.SESSION_STATE_CHANGED, (state) => {
        console.log('Session state →', state);
        setSessionState(state);
        if (state === SessionState.DISCONNECTED) {
          setIsStreamReady(false);
          sessionRef.current = null;
        }
      });

      session.on(SessionEvent.SESSION_STREAM_READY, () => {
        console.log('Stream ready');
        setIsStreamReady(true);
        if (videoRef.current) session.attach(videoRef.current);
        // Start listening once stream is ready so avatar responds to voice
        session.startListening();
      });

      // Avatar speech
      session.on(AgentEventsEnum.AVATAR_SPEAK_STARTED, () => setIsAvatarTalking(true));
      session.on(AgentEventsEnum.AVATAR_SPEAK_ENDED, () => {
        setIsAvatarTalking(false);
        setTimeout(() => setAvatarText(''), 2000);
      });
      session.on(AgentEventsEnum.AVATAR_TRANSCRIPTION, (e) => {
        if (e.text) setAvatarText(e.text);
      });

      // User speech
      session.on(AgentEventsEnum.USER_SPEAK_STARTED, () => setIsUserTalking(true));
      session.on(AgentEventsEnum.USER_SPEAK_ENDED, () => {
        setIsUserTalking(false);
        setTimeout(() => setUserText(''), 2000);
      });
      session.on(AgentEventsEnum.USER_TRANSCRIPTION, (e) => {
        if (e.text) setUserText(e.text);
      });

      // Voice chat mute state
      session.voiceChat.on(VoiceChatEvent.MUTED, () => setIsMuted(true));
      session.voiceChat.on(VoiceChatEvent.UNMUTED, () => setIsMuted(false));

      sessionRef.current = session;
      await session.start();
    } catch (err) {
      console.error('Start failed:', err);
      alert('Failed to start session: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ── Stop session ──────────────────────────────────
  const stopSession = useCallback(async () => {
    try {
      if (sessionRef.current) {
        sessionRef.current.stopListening();
        await sessionRef.current.stop();
        sessionRef.current = null;
      }
      // Also tell the server to stop the session (belt & suspenders)
      if (sessionIdRef.current) {
        fetch(`${API_BASE}/api/session/stop`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionIdRef.current }),
        }).catch(() => {});
        sessionIdRef.current = null;
      }
    } catch (e) {
      console.warn('Stop error:', e);
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    // Clear the canvas so the last frame doesn't persist
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext('2d');
      ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    }
    stopChromaKey();
    setSessionState(SessionState.INACTIVE);
    setIsStreamReady(false);
    setAvatarText('');
    setUserText('');
  }, []);

  // ── Toggle mic ────────────────────────────────────
  const toggleMute = useCallback(() => {
    if (!sessionRef.current) return;
    if (isMuted) {
      sessionRef.current.voiceChat.unmute();
    } else {
      sessionRef.current.voiceChat.mute();
    }
  }, [isMuted]);

  // ── Send text ─────────────────────────────────────
  const sendMessage = useCallback(() => {
    if (!sessionRef.current || !textInput.trim()) return;
    sessionRef.current.message(textInput.trim());
    setTextInput('');
  }, [textInput]);

  // ── Interrupt ─────────────────────────────────────
  const interruptAvatar = useCallback(() => {
    sessionRef.current?.interrupt();
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    const cleanup = () => {
      sessionRef.current?.stopListening();
      sessionRef.current?.stop().catch(() => {});
      if (sessionIdRef.current) {
        // Use sendBeacon for reliable cleanup on page unload
        const data = JSON.stringify({ session_id: sessionIdRef.current });
        navigator.sendBeacon(`${API_BASE}/api/session/stop`, new Blob([data], { type: 'application/json' }));
      }
    };
    window.addEventListener('beforeunload', cleanup);
    return () => {
      window.removeEventListener('beforeunload', cleanup);
      cleanup();
    };
  }, []);

  // ── Chroma key render loop ─────────────────────
  const startChromaKey = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    let logged = false;

    const draw = () => {
      if (video.paused || video.ended || !video.videoWidth) {
        animFrameRef.current = requestAnimationFrame(draw);
        return;
      }

      // Match canvas size to video
      if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        console.log('Canvas size:', canvas.width, 'x', canvas.height);
      }

      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const d = frame.data;

      // Log a sample of corner pixels once to debug the green color values
      if (!logged && d.length > 16) {
        const samples = [];
        for (let s = 0; s < 5; s++) {
          const idx = s * 4;
          samples.push(`[${d[idx]},${d[idx+1]},${d[idx+2]},${d[idx+3]}]`);
        }
        console.log('First 5 pixels RGBA:', samples.join(' '));
        logged = true;
      }

      let removed = 0;
      for (let i = 0; i < d.length; i += 4) {
        const r = d[i], g = d[i + 1], b = d[i + 2];
        // Aggressive green screen removal:
        // Green must be the dominant channel by at least 30 points
        if (g > 50 && (g - r) > 25 && (g - b) > 25) {
          d[i + 3] = 0; // transparent
          removed++;
        }
      }

      ctx.putImageData(frame, 0, 0);
      animFrameRef.current = requestAnimationFrame(draw);
    };

    animFrameRef.current = requestAnimationFrame(draw);
  }, []);

  const stopChromaKey = useCallback(() => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
  }, []);

  // Re-attach video when stream becomes ready & start chroma key
  useEffect(() => {
    if (isStreamReady && videoRef.current && sessionRef.current) {
      sessionRef.current.attach(videoRef.current);
      startChromaKey();
    }
    return () => stopChromaKey();
  }, [isStreamReady, startChromaKey, stopChromaKey]);

  const isConnected = sessionState === SessionState.CONNECTED;

  return (
    <div className="app-container">
      <h1 className="title">Live Avatar Chat</h1>

      {/* Video */}
      <div className="video-wrapper">
        <video ref={videoRef} autoPlay playsInline className="avatar-video-hidden" />
        <canvas ref={canvasRef} className="avatar-canvas" />

        {/* Subtitles */}
        {(avatarText || userText) && (
          <div className="subtitle-container">
            {avatarText && <div className="subtitle avatar-sub">{avatarText}</div>}
            {userText && <div className="subtitle user-sub">You: {userText}</div>}
          </div>
        )}

        {/* Talking indicators */}
        {isConnected && isStreamReady && (
          <div className="status-bar">
            {isAvatarTalking && <span className="status-dot green" />}
            {isUserTalking && <span className="status-dot blue" />}
          </div>
        )}

        {/* Placeholder states */}
        {!isConnected && !isLoading && (
          <div className="video-placeholder"><p>Click "Start Session" to connect</p></div>
        )}
        {isLoading && (
          <div className="video-placeholder"><p>Connecting…</p></div>
        )}
        {isConnected && !isStreamReady && (
          <div className="video-placeholder"><p>Waiting for stream…</p></div>
        )}
      </div>

      {/* Controls */}
      <div className="controls">
        {!isConnected ? (
          <button onClick={startSession} disabled={isLoading} className="btn btn-primary">
            {isLoading ? 'Connecting…' : 'Start Session'}
          </button>
        ) : (
          <>
            <button onClick={toggleMute} className={`btn ${isMuted ? 'btn-secondary' : 'btn-active'}`}>
              {isMuted ? '🎙️ Unmute' : '🔇 Mute'}
            </button>
            <button onClick={interruptAvatar} className="btn btn-secondary">
              Interrupt
            </button>
            <button onClick={stopSession} className="btn btn-danger">
              End Session
            </button>
          </>
        )}
      </div>

      {/* Text input */}
      {isConnected && (
        <div className="text-input-row">
          <input
            type="text"
            placeholder="Type a message…"
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            className="text-input"
          />
          <button onClick={sendMessage} className="btn btn-primary" disabled={!textInput.trim()}>
            Send
          </button>
        </div>
      )}
    </div>
  );
}

export default App;
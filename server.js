import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: join(__dirname, '.env') });

const app = express();
app.use(cors());
app.use(express.json());

// ── Config ──────────────────────────────────────────
const LIVEAVATAR_API_KEY = process.env.LIVEAVATAR_API_KEY;
const AVATAR_ID = '03f8332d-9046-42a1-bff3-3b2309f77b58';
const CONTEXT_ID = '162d1502-6d67-4558-a343-a0b9331b468a';
const API_URL = 'https://api.liveavatar.com';

if (!LIVEAVATAR_API_KEY) {
  console.error('ERROR: LIVEAVATAR_API_KEY not found in .env');
  console.error('Add LIVEAVATAR_API_KEY=your_key to .env');
  process.exit(1);
}
console.log('LiveAvatar API key loaded');

// ── Create session token ────────────────────────────
app.post('/api/session/token', async (_req, res) => {
  try {
    const body = {
      mode: 'FULL',
      avatar_id: AVATAR_ID,
      avatar_persona: {
        context_id: CONTEXT_ID,
        language: 'en',
      },
      interactivity_type: 'CONVERSATIONAL',
    };

    console.log('Creating LiveAvatar session…');

    const response = await fetch(`${API_URL}/v1/sessions/token`, {
      method: 'POST',
      headers: {
        'X-API-KEY': LIVEAVATAR_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errText = await response.text();
      console.error('Token request failed:', response.status, errText);
      let msg = 'Failed to get session token';
      try {
        const j = JSON.parse(errText);
        msg = j.message || j.data?.[0]?.message || errText;
      } catch {}
      return res.status(response.status).json({ error: msg });
    }

    const data = await response.json();
    const session_token = data.data?.session_token;
    const session_id = data.data?.session_id;

    if (!session_token) {
      console.error('No session_token in response:', data);
      return res.status(500).json({ error: 'No session token returned' });
    }

    console.log('Session created:', session_id);
    res.json({ session_token, session_id });
  } catch (err) {
    console.error('Session error:', err);
    res.status(500).json({ error: 'Failed to create session' });
  }
});

// ── Stop a specific session ─────────────────────────
app.post('/api/session/stop', async (req, res) => {
  try {
    const { session_id } = req.body;
    if (!session_id) return res.status(400).json({ error: 'session_id required' });
    console.log('Stopping session:', session_id);

    const response = await fetch(`${API_URL}/v1/sessions/stop`, {
      method: 'POST',
      headers: {
        'X-API-KEY': LIVEAVATAR_API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ session_id }),
    });

    if (!response.ok) {
      const errText = await response.text();
      console.error('Stop failed:', response.status, errText);
      return res.status(response.status).json({ error: errText });
    }

    console.log('Session stopped:', session_id);
    res.json({ success: true });
  } catch (err) {
    console.error('Stop error:', err);
    res.status(500).json({ error: 'Failed to stop session' });
  }
});

// ── List & kill all active sessions ─────────────────
app.post('/api/sessions/stop-all', async (_req, res) => {
  try {
    const listRes = await fetch(`${API_URL}/v1/sessions?type=active`, {
      headers: { 'X-API-KEY': LIVEAVATAR_API_KEY },
    });
    const listData = await listRes.json();
    const sessions = listData.data?.results || [];
    console.log(`Found ${sessions.length} active session(s)`);

    const results = await Promise.allSettled(
      sessions.map((s) =>
        fetch(`${API_URL}/v1/sessions/stop`, {
          method: 'POST',
          headers: {
            'X-API-KEY': LIVEAVATAR_API_KEY,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ session_id: s.session_id }),
        })
      )
    );

    const stopped = results.filter((r) => r.status === 'fulfilled').length;
    console.log(`Stopped ${stopped}/${sessions.length} sessions`);
    res.json({ stopped, total: sessions.length });
  } catch (err) {
    console.error('Stop-all error:', err);
    res.status(500).json({ error: 'Failed to stop sessions' });
  }
});

// ── Start ───────────────────────────────────────────
const PORT = process.env.PORT || 5000;
app.listen(PORT, () => console.log(`Server → http://localhost:${PORT}`));
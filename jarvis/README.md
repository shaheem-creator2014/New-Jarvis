# JARVIS — personal AI assistant for Shaheem

A Windows-compatible local dashboard with read-only knowledge indexing, a Canvas graph, local Ollama chat, approved tools, optional ElevenLabs voice, Google read-only integrations, public research, and explicit persistent memory. The application requires Python 3.11+ and no mandatory third-party packages, Node.js, npm or frontend build. It uses HTML, CSS and vanilla JavaScript.

## Run on your Windows PC

1. Clone this repository or extract the source ZIP on your PC. Open the **jarvis** folder in VS Code.
2. Install Python 3.11 or newer yourself if necessary, from [python.org](https://www.python.org/downloads/windows/). In VS Code's terminal, verify `py -3 --version`.
3. With the terminal in the folder containing `run.py`, run:

   ```powershell
   py -3 run.py
   ```

   `python run.py` also works if your `python` command selects Python 3.11+. The launcher starts the local server and opens your browser. The dashboard address on **that PC** is `http://localhost:8765`. Keep the terminal running; use Ctrl+C to stop. If the browser does not open, type the address into Edge or Chrome. Do not open `ui/index.html` directly.
4. Start with **FICTIONAL DEMO** mode. Try File search → `ESP32`, graph nodes, Brief, Plan, Memory with fictional test facts, and Test mic locally. These features do not require Ollama or credentials. AI conversation/robotics explanations need Ollama.

From this cloud checkout the equivalent commands are `cd /workspace/New-Jarvis/jarvis` and `python run.py --no-browser`. A cloud machine's loopback address is not your PC's address; no public cloud preview or remote Windows control is configured.

Other commands:

```text
python run.py --index-only
python run.py --search ESP32
python -m unittest discover -s tests -v
```

If port 8765 is already occupied, stop the other JARVIS instance you started or the application using that port, then retry. The launcher does not silently install software, download a model, connect an account, or make a paid request.

## Configuration and demo isolation

Optionally copy `.env.example` to `.env` in the `jarvis` folder and edit it privately. The launcher now loads supported settings from `.env`; existing process environment values take precedence. Whole-line comments and simple quoted values are supported. No shell evaluation, interpolation, or escape expansion occurs. Unknown settings fail with a line number without printing values.

Supported names: `JARVIS_DEMO`, `JARVIS_MODEL`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `JARVIS_SEARCH_PROVIDER`, `BRAVE_SEARCH_API_KEY`, `JARVIS_GOOGLE_CLIENT_ID`, `JARVIS_GOOGLE_CLIENT_SECRET`. Keep keys/tokens/client secrets out of Git, JavaScript, screenshots and chat. `.env`, OAuth client JSON, tokens and memory contents are ignored by Git. Never commit credentials.

Demo mode defaults to `JARVIS_DEMO=1`. Only `agent/data.py` interprets that variable and selects the data source. Demo documents use fixed seed 2014; creation is repeatable and does not overwrite existing files. Clients, emails, appointments, tasks and reminders are fictional and labeled. No real Gmail, Calendar, research, voice API or real memory store is accessed in demo mode.

To explicitly approve real-data operation, set `JARVIS_DEMO=0` privately and run `python run.py --approve-real-knowledge`. The flag also authorizes the fixed knowledge folder described below. External accounts still need their own OAuth/consent, and paid requests still need approval. Do not enable real mode without reviewing those choices.

## Knowledge and dashboard

The real knowledge folder is `Documents/JARVIS_KNOWLEDGE` below the Windows user home; no fixed username or arbitrary API path is accepted. Place **copies** of documents there. Suggested folders are School, Robotics, Website_Projects, Content_Creation and Personal_Notes. Indexed source files are never modified.

TXT and UTF-8 Markdown are indexed recursively. `.git`, `node_modules`, unsupported/binary files, symbolic links/junctions and files over 2 MB are skipped. Markdown `[[wikilinks]]` form undirected edges; ambiguous or missing targets are not invented. Search returns actual filenames and extracted-text line citations. Do not modify the folder concurrently during indexing.

PDF extraction is optional and uses `pypdf` **only if already installed**. Missing extractors are reported; nothing is installed automatically. Extraction runs in a child process with an eight-second timeout, a 100-page/200,000-character limit, and Unix resource limits where supported. Encrypted, malformed, scanned/image-only or over-limit documents may have no useful text or be skipped. OCR is not implemented. PDF citations refer to extracted text; page markers are included. Installing a compatible extractor needs owner approval.

The graph supports hover connections, selection, Shift-click shortest paths, dragging, pan, wheel zoom, filters, labels, Fit and Motion controls. Sizes reflect connection counts; colors group document categories and the inspector shows the file type. Source excerpts are labeled rather than presented as AI summaries. Keyboard users can select documents from top-connection/related lists. The graph uses spatial buckets, bounded neighbour visits, label collision cells and limited rendering resolution; layout stops after settling. Disable Motion/Labels on modest hardware. A synthetic 2,000-node cloud check was responsive; arbitrary large/dense datasets and the ASUS laptop remain unbenchmarked.

## Ollama chat and tools

Install [Ollama](https://ollama.com/) separately with your permission and run its local service. If you approve the download, select the preferred model using `ollama pull llama3.2:1b`. JARVIS never downloads it. Set `JARVIS_MODEL` to another **already installed** model if desired. The client only uses `http://127.0.0.1:11434`; Check AI checks connectivity and the model list.

Conversation and Robotics assistance use the local model. About ten turns are retained in memory with an additional 24,000-character history budget and 4,000-character input limit. Long messages reduce retained context. Browser reload restores the active session; inactive sessions expire after one hour. Clear removes session conversation/tasks and pending confirmations, not persistent memories. Model answers can be wrong; review technical advice.

Without Ollama, text file search, memory, planning, demo integrations and explicit limited commands still work. They are labeled as commands rather than AI reasoning:

- `/search words`, `/help`
- `/app vscode` (also calculator, notepad, explorer)
- `/open github` (also youtube, vercel, lovable)
- `/plan`
- `/inbox`, `/calendar today`, `/calendar upcoming`, `/calendar robotics`, `/brief`
- `/research public query`
- `/remember exact fact`, `/memory`, `/recall words`

App/website launches require a separate Confirm action button. Confirmation tokens expire after two minutes, are single-use and session-bound. URLs are restricted to approved HTTPS homepages; dangerous schemes, extra arguments and local files are rejected. No model-generated shell commands, installers, registry changes or arbitrary scripts run. VS Code is located only in its normal user/system installation locations. A launch/browser acceptance is reported accurately, without claiming that a window or webpage was verified. Desktop actions act on the PC running Python and return an unsupported-platform result in Linux cloud.

Plan accepts actual owner-supplied tasks, marking urgency/category explicitly. It returns at most five priorities: owner-marked urgency first, then school, commitments, robotics, websites and content. It does not invent commitments, sales, customers or deadlines. Robotics assistance explains Arduino, ESP32, MicroPython, Python and electronics; it never uploads firmware or controls hardware.

For slow AI, use the small preferred model, close memory-heavy apps and check Ollama logs. Only one slow assistant request runs at a time; the UI reports progress and rejects overlapping requests. AI timeouts/malformed output do not execute tools.

## Voice: microphone, Scribe and speech

No browser Web Speech API is used. Current Edge/Chrome at the local dashboard use MediaRecorder and Web Audio. **Test mic locally** requests microphone permission, shows measured audio levels, then discards the recording without an upload; it works in demo mode and without keys.

**Mic** starts a turn. “Listening…” is capture status, not live transcription. Pausing for approximately 900 ms after speech finishes the turn; **Finish turn** can end it explicitly. Mic again discards capture. Quiet turns stop after eight seconds; recordings are capped at 45 seconds/6 MB. Named constants `SILENCE_DURATION_MS` and `SILENCE_THRESHOLD_RMS` in `ui/voice.js` control silence detection. `setInterval` avoids dependence on animation frames, but browser suspension/throttling can still delay detection.

Real voice requires non-demo mode and private server settings `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`. Choose an available voice ID from your own ElevenLabs account; none is invented or fetched automatically. The key never goes to the browser. Capture stops/releases before the approval dialog. Approve transcription to send that recording to Scribe (`scribe_v1`); declining/expiry discards it. The returned transcript goes through your selected chat/search/robotics mode. Then a separate approval requests TTS (`eleven_multilingual_v2`). Typed results also have Speak response buttons. Long/code answers use a short spoken notice rather than reading detailed cards.

**Both transcription and synthesis consume credits even on free tiers and may incur charges.** Failed/interrupted requests may already have used credits. There are no automatic paid retries. JARVIS writes no recording files; buffers remain transient. Generated speech is delivered once and removed from retained results, or discarded on the next session request after 60 seconds. ElevenLabs has its own retention policy; JARVIS does not promise provider-side zero retention.

Capture is disabled during inference/speech output. Mic, Space and Escape interrupt voice; text inputs/dialogs retain their normal editing behavior. Space retains button activation when voice is inactive. Mute stops/suppresses speech. Continue listening is off by default, capped at five turns if explicitly enabled, and asks fresh approval before every paid request. It stops across errors and pending action/task confirmation. There is no background wake-word listener.

Permission denied: allow localhost in browser microphone settings and Windows privacy settings. No mic: connect/enable the intended input device. Recording failed: close conflicting apps and retry the local test. Silence problems: reduce room noise or adjust the named threshold. Playback blocked: allow sound for localhost and check your output device. Authentication, missing key/voice ID, credit exhaustion, rate limit and network errors have explicit feedback. Text output remains usable.

## Gmail and Google Calendar

Connections shows configuration and saved authorization separately from successful reads. These are **separate local OAuth flows**; ChatGPT account connections are not inherited. No OAuth libraries are needed or installed.

Owner-performed setup:

1. In your Google Cloud project enable Gmail API and Google Calendar API. Configure the OAuth consent audience and your account as a test user where required. Testing-mode authorizations can expire; Google may require verification before wider distribution, particularly for Gmail scopes.
2. Create a **Desktop app** OAuth client and download its JSON. Keep it private at `~/AppData/Local/JARVIS/auth/oauth-client.json` under your Windows user home, containing Google's `installed` configuration. Do not place it in the repository, UI or knowledge folder. Raw server configuration `JARVIS_GOOGLE_CLIENT_ID`/`JARVIS_GOOGLE_CLIENT_SECRET` is an alternative. A cloud proxy placeholder must not be assumed usable as a raw OAuth form-field secret; the private client file is the recommended Windows path.
3. After approving real mode, run with `JARVIS_DEMO=0` and `--approve-real-knowledge`. In Connections explicitly approve starting the chosen Gmail or Calendar flow, follow Continue to Google read-only consent, and review Google's permissions. Never enter your Google password into JARVIS.
4. Keep the server running for Google's redirect to `http://127.0.0.1:8765/oauth/google/callback`, then refresh Connections. Browser and server must run on the same PC; a remote cloud loopback callback cannot connect your local accounts.

Scopes are exactly `gmail.readonly` and `calendar.events.readonly` (under `https://www.googleapis.com/auth/`). OAuth uses expiring one-use state and PKCE S256. Client secrets, codes and tokens remain server-side and are omitted from logs/responses. Account reads use GET only. No sending, deletion, label modification, archiving, event changes or invitations are implemented.

Windows tokens are DPAPI-encrypted under the private auth folder and bound to the Windows user. Encryption failure prevents saving; no plaintext fallback exists. Other platforms retain tokens only in memory. Native DPAPI remains unverified in this Linux environment; storage tests use an encryption double.

Inbox shows at most five unread inbox messages: sender and subject, with provider excerpts/evidence collapsed until opened. The message summary is Gmail's short provider excerpt, not an AI summary of a full body. Bodies/attachments are not fetched. Sender evidence uses an exact address match with actual note filename/line citations; absence of a match does not establish that a sender is unknown. Calendar reads the primary calendar, today or the upcoming seven days, with optional activity search and at most 20 events. Additional results are reported. All-day end dates are exclusive. Dates/day boundaries use Asia/Colombo.

Disconnect requires confirmation, removes the chosen local authorization, cancels its pending grants and clears retrieved account cards/caches/history. It does not revoke Google's server-side grants; use [Google account permissions](https://myaccount.google.com/permissions) for that. The other service's local token is retained. Clear cancels that session's pending authorization attempts without disconnecting accounts.

## Public research and briefing

Set `JARVIS_SEARCH_PROVIDER` explicitly to `wikipedia` for free public reference-article search (not general-web search), or `brave` for general-web search with server-side `BRAVE_SEARCH_API_KEY`. With missing configuration, live research reports unavailable. Research displays the exact query and requires approval before sending it externally. Brave requests may consume credits/incur charges, including free-tier allowances. No automatic retries or secondary webpage fetching occur.

Results cite HTTPS URLs, provider excerpts and retrieval time; excerpts are not guaranteed facts. Never approve sending private mail, credentials or personal document contents as a public query. Retrieved notes, email, events, memory and web text are data, never executable instructions.

Brief combines available calendar events, unread mail, owner-supplied session tasks and approved memories explicitly marked as reminders. Missing/unavailable sections are labeled. It invents no deadlines or tasks. Demo briefings use fictional fixtures rather than real memories/accounts.

Provider destinations: `api.elevenlabs.io`, `accounts.google.com` (browser OAuth), `oauth2.googleapis.com`, `gmail.googleapis.com`, `www.googleapis.com` (Calendar), `en.wikipedia.org` (optional), `api.search.brave.com` (optional). Add only needed destinations in cloud settings. JARVIS is not completely offline when using these services. Saved drafts are not applied runtime settings, connected accounts, paid-call permission or published snapshots.

## Explicit persistent memory

Memory opens an owner-controlled local store. Review exact text and check approval before each save. Sensitive details require extra approval; automatic detection is a safeguard, not a substitute for your review. Passwords, keys, tokens and credential-like values are rejected even if approved. Only `agent/memory.py` writes/deletes memory files.

Each approved fact becomes a dated Markdown file under `memory/`; demo facts use the separate `memory/demo/` store. Save fictional test facts in demo mode. Memories are local plaintext, ignored by Git and excluded from the source ZIP; do not store credentials or unnecessary private details. Choose reminder only when you want that exact fact in a real daily briefing. Relative dates such as “Friday” are stored exactly, without inventing an absolute deadline or calendar event.

Use Memory or `/recall words` to view facts and filenames. `/remember` and model requests only propose facts for a separate approval; they never save silently. Delete asks confirmation and removes the chosen file plus stale memory conversation caches. Clear does not delete approved files; use Memory's delete action. Memories persist after server restarts. They are not automatically inserted into every model prompt or sent to external providers. Treat manually edited files as untrusted; invalid, oversized or linked files are rejected/skipped.

## Security, validation and current limits

The server binds only to 127.0.0.1. Host/Origin/fetch-site checks, strict cookies, session CSRF tokens, JSON/body limits, duplicate-header rejection, timeouts and 32 HTTP slots protect local request handling. Slow work is limited to one worker. Public files come only from explicit UI routes; there are no arbitrary file-path APIs. Keys, tokens, source folders and memory are never served as static assets. This is a single-owner local application, not a hardened Internet-facing or multi-user service; do not expose its port publicly. No independent security audit is claimed.

**86 tests passed** in this cloud instance, including an actual text-PDF extraction using an already installed optional pypdf. Without pypdf that one test is skipped explicitly. Tests cover indexing/search/wikilinks, demo isolation, memory permissions/persistence/secrets, request limits/CSRF, desktop allowlists, model protocol/errors, voice errors/approval, OAuth state/scopes/refresh/failures, briefing and research fixtures. Browser checks cover graph/tool interactions, voice with synthetic audio/provider fixtures, OAuth/search fixtures, mobile layout and memory flows. They do not prove live AI/service behavior.

Real Ollama inference/model downloads, ElevenLabs recognition/synthesis, real Gmail/Calendar OAuth/read operations, live search, native Windows launches/DPAPI, physical microphones/speakers and performance on the ASUS laptop remain unverified. No software/model downloads, account connections or paid calls were made during development. Optional PDF/OCR limitations are described above. Test on the actual Windows PC and authorize optional services before relying on them.

The optional regression `python tests/browser_voice_check.py` uses an **already installed** Playwright/Chromium and a running dashboard. It creates/deletes synthetic tone fixtures, uses provider doubles and checks late-result interruption. It never installs tooling or calls ElevenLabs. `JARVIS_TEST_BROWSER` can select an existing Chromium executable.

References: [Google native OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [Gmail messages](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages), [Calendar events](https://developers.google.com/workspace/calendar/api/v3/reference/events/list), [ElevenLabs SDK reference](https://github.com/elevenlabs/elevenlabs-python).

### General questions and document search

Conversation mode answers general questions using the selected local model; demo mode does not disable general conversation. File search mode and `/search` explicitly search indexed documents. Conversational document retrieval is reserved for requests referring to notes, files, documents, or saved projects/code. General questions such as football facts, maths and coding should not be replaced by an empty document search. Current statistics still require a dated, verified public source through an approved research provider. The default 1B model has limited accuracy and reasoning; this application does not make it equivalent to ChatGPT.

### Reliable basic arithmetic

In Conversation mode, direct arithmetic such as `199 × 599`, `What is 0.1 + 0.2?`, or `Calculate (12 + 8) / 5` uses a bounded local calculator before Ollama. It supports numbers, parentheses, +, -, multiplication, division, modulo, and bounded integer powers. Fractions are calculated exactly internally; rounded decimal output is labeled approximate. Errors do not fall back to a guessed model answer. This is not a general symbolic mathematics or word-problem solver; other maths explanations still depend on the model.

# Immich Memories — Build Plan

> A self-hosted "memories" notification system for Immich.
> Better than Google Photos because it's contextual, private, and tunable to how *your* brain works.

---

## 1. The Idea

Google Photos sends a "memory" every day because it has to — algorithmic, no opinion, can't tell whether today actually mattered. We can do better:

> **Run daily. Send only when the day earned it.**

Silence is a feature. The notification arrives only when something interesting happened on this date in past years, so when it does arrive it actually means something.

### Design principles

1. **Quality > frequency.** Empty days stay silent. No notification fatigue.
2. **Local-first.** No cloud round-trip. Photos never leave the LAN.
3. **Tunable.** A single "specialness threshold" dial controls how often it fires.
4. **Predictable structure, novel content.** Same notification format every time (good for autistic pattern recognition); content always fresh (good for ADHD novelty).
5. **No streaks, no gamification.** ADHD brains punish themselves over broken streaks. None of that.
6. **Easy to dismiss without guilt.** "Hide this memory forever" is one tap away.
7. **No "review your photos" framing.** A memory notification is a moment, not a task.

---

## 2. Architecture Overview

Two cooperating containers on the always-on NAS, plus an opportunistic LLM worker on the Framework Desktop.

```
┌─────────────────── NAS (always on) ───────────────────┐
│                                                       │
│   ┌────────────┐    ┌──────────────────────────┐      │
│   │   Immich   │◄───│  scout (daily cron)      │      │
│   └────────────┘    │  - fetch memories        │      │
│                     │  - score them            │      │
│                     │  - enqueue if special    │      │
│                     └──────────┬───────────────┘      │
│                                │                      │
│                                ▼                      │
│                     ┌──────────────────────┐          │
│                     │   queue.sqlite       │          │
│                     │   (pending / sent /  │          │
│                     │    hidden / blocked) │          │
│                     └──────────┬───────────┘          │
│                                │                      │
│   ┌────────────┐    ┌──────────▼───────────┐          │
│   │    ntfy    │◄───│  sender              │          │
│   └────────────┘    │  - drains queue      │          │
│                     │  - posts to ntfy     │          │
│                     └──────────────────────┘          │
└───────────────────────────────────────────────────────┘
                           ▲
                           │ Tailscale, opportunistic
                           ▼
┌────────────── Framework Desktop (sometimes on) ───────┐
│                                                       │
│   ┌──────────────────────────────────────────┐        │
│   │  enricher                                │        │
│   │  - polls NAS queue                       │        │
│   │  - asks Ollama vision model to:          │        │
│   │      • re-score                          │        │
│   │      • pick the best photo               │        │
│   │      • write 1-sentence caption          │        │
│   │  - writes back: enriched=true            │        │
│   └──────────────────────────────────────────┘        │
└───────────────────────────────────────────────────────┘
```

Three independent jobs, one shared SQLite queue. Each can fail without breaking the others.

### Why three jobs not one

- **scout** is fast, deterministic, runs on a schedule. Always works.
- **sender** is dumb on purpose. If it can reach ntfy, it sends.
- **enricher** is opportunistic. Framework offline? No problem — sender still has heuristic-quality content to ship. Framework online? Notifications get richer automatically.

This means **Phase 1 is fully functional without Framework**, and **Phase 2 layers on without rewriting anything**.

---

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Best ecosystem for image / EXIF / LLM glue. Fast enough. |
| HTTP client | `httpx` | Async-capable, modern, sane API. |
| Queue | **SQLite** (single file) | Zero ops. ACID. Both NAS jobs share one file via volume mount; enricher accesses via Tailscale-exposed lightweight API. |
| Scheduler | `cron` inside the container | One container per job. `supercronic` if we want logs in stdout. |
| Notifications | **ntfy** (already self-hosted) | 15MB attachments, action buttons, custom URL schemes — all native. |
| Reverse geocoding | `reverse_geocoder` (offline) | 1MB dataset, no API keys, no rate limits, returns city + country. |
| LLM runtime | **Ollama** on Framework | Already running. |
| Vision model | **qwen2.5vl:7b** (primary), `moondream2` (fallback) | Qwen 2.5-VL is state of the art for size; moondream is tiny and fast for backup. |
| Container orchestration | Portainer (existing) | Already in place. |
| Config | YAML + env overrides | Easy to read, easy to override per env. |

### Python libraries

```
httpx          # HTTP
pydantic       # config + DTO validation
pyyaml         # config file
reverse_geocoder
sqlite-utils   # ergonomic SQLite
ollama         # Phase 2 client
structlog      # JSON logs
```

No web framework needed. No ORM. No Celery. Keep it small.

---

## 4. Immich API — Verified Contract

Researched directly from `immich-app/immich` source. Endpoints we'll use:

### `GET /api/memories?for=<ISO date>&type=on_this_day`

Returns array of `MemoryResponseDto`:

```ts
{
  id: string,
  memoryAt: string,            // ISO date
  ownerId: string,
  type: "on_this_day",
  data: { year: number },      // which year this memory is from
  isSaved: boolean,            // user marked as saved
  seenAt?: string,             // null if unseen
  showAt?: string,
  hideAt?: string,             // null if not hidden
  assets: AssetResponseDto[]   // photos for this memory
}
```

For "today's memories across all years" we hit it with `for=YYYY-MM-DD` and get back one entry per year that has photos on this date.

### `GET /api/assets/{id}/thumbnail?size=thumbnail`

Returns JPEG thumbnail (~50–150KB). Use this for ntfy `Attach` header. Avoid `preview` (larger) and full-res download.

### Auth

`x-api-key: <key>` header. Generated from Immich web UI per user.

### Deep link

`immich://asset/{id}` — confirmed in mobile app source. Works on Android & iOS.

---

## 5. ntfy — Verified Contract

| Header | Use |
|---|---|
| `Title` | "3 years ago in Barcelona" |
| `Message` | Caption (template or LLM) |
| `Attach` | URL of thumbnail (NAS-internal Immich URL) |
| `Click` | `immich://asset/{id}` — taps the notification, opens the photo |
| `Actions` | Up to 3 buttons. `view, Hide forever, http://memories/hide?id=...` etc. |
| `Priority` | `default` (3). Don't use `high` — this is not urgent. |
| `Tags` | `frame_with_picture` for the camera emoji |

Limits to know:
- Attachment max **15MB** (we send ~100KB thumbnails — fine)
- Attachments expire after **3 hours** on ntfy server, but the phone caches them
- No base64 — must be a URL

---

## 6. Phase 1 — Heuristic Scout (MVP)

> Goal: working daily contextual notifications, no LLM, fully on NAS.

### 6.1 Scoring algorithm

When scout wakes at 09:00, it asks: *for each memory returned for today's date, is this day worth a notification?*

```python
def score(memory: Memory) -> int:
    s = 0

    # Volume — was something happening?
    n = memory.photo_count
    if   n >= 20: s += 3
    elif n >= 10: s += 2
    elif n >=  5: s += 1

    # Curation signals — past-you already voted
    if memory.has_starred_photo:                       s += 3
    if memory.has_named_album:                         s += 3
    if memory.is_saved:                                s += 2  # user saved this memory in Immich

    # Context signals
    if memory.gps_distance_from_home_km > 50:          s += 3
    if memory.face_count >= 3:                         s += 2
    if memory.spans_hours >= 4:                        s += 1

    # Hard overrides
    if memory.is_anniversary(years=[1, 2, 5, 10, 20]): s += 99

    return s

THRESHOLD = 5  # configurable
```

A "boring" day (3 random snapshots at home) scores 0–1 → silent.
A "real" day (15 photos, GPS in another city, named album) scores 8+ → fires.
An exact 5-year anniversary always fires regardless.

### 6.2 Notification template

```
📸 3 years ago in Barcelona
You spent the day around the Gothic Quarter
[thumbnail]
```

Title pattern: `<years> years ago [in <city>]`
Body pattern: dynamic, picks the most informative template that fits:

| Available signals | Template |
|---|---|
| GPS + spans-day | `You spent the day in <city>` |
| GPS + album name | `<album_name> — <city>` |
| GPS only | `You were in <city>` |
| Album only | `<album_name>` |
| Photo count only | `A day full of photos` |
| Anniversary | `<n> years ago today` (prepended) |

No "47 photos" framing. Replaced with experience framing.

### 6.3 Photo selection

Inside a special-enough memory, pick **one** photo using this priority:

1. Starred photo (if any)
2. Photo with most detected faces (Immich exposes `people` on assets)
3. Photo with GPS that matches the memory's main cluster
4. Random fallback

### 6.4 SQLite schema

```sql
CREATE TABLE queue (
  id INTEGER PRIMARY KEY,
  memory_id TEXT NOT NULL,             -- Immich memory id
  memory_date TEXT NOT NULL,           -- YYYY-MM-DD (the actual date in past)
  year INTEGER NOT NULL,
  asset_id TEXT NOT NULL,              -- chosen photo
  score INTEGER NOT NULL,
  city TEXT,
  caption TEXT,                        -- generated template or LLM caption
  status TEXT NOT NULL,                -- pending | enriched | sent | failed | skipped
  enriched_at TEXT,
  sent_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(memory_id)
);

CREATE TABLE hidden (
  asset_id TEXT PRIMARY KEY,           -- "Hide this memory forever" tap
  hidden_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE config (
  key TEXT PRIMARY KEY,
  value TEXT
);
```

The `UNIQUE(memory_id)` constraint guarantees no duplicates. Re-running scout on the same day is idempotent.

### 6.5 "Hide forever" endpoint

A tiny Flask/FastAPI app on NAS exposes `POST /hide?asset_id=X`. ntfy action button calls it. Asset goes into `hidden`, scout skips anything in there.

This is the ADHD-safe "ugh, not this memory" button. No guilt, one tap.

### 6.6 Phase 1 deliverables

- [ ] `scout.py` — daily cron, Immich → score → queue
- [ ] `sender.py` — drains queue, posts to ntfy
- [ ] `hide_server.py` — tiny HTTP endpoint for the Hide button
- [ ] `config.yaml` — Immich URL, API key, ntfy topic, threshold, home GPS
- [ ] `Dockerfile` + `docker-compose.yml`
- [ ] `--dry-run` flag on scout (prints what would be queued, doesn't write)
- [ ] `--force` flag on scout (ignores threshold, useful for testing)
- [ ] Logs to stdout in JSON, picked up by Portainer

**Estimated: 2–3 evenings.**

---

## 7. Phase 2 — LLM Enricher

> Goal: replace heuristics with actual photo understanding when Framework is reachable. Heuristic version remains the safe floor.

### 7.1 What changes

The scout's score becomes a **gate**, not a verdict. If score ≥ threshold, queue with `status=pending` and a template caption. Then:

- If Framework is online → enricher upgrades it (`status=enriched`)
- Sender always reads from queue regardless of `enriched` status

### 7.2 The enricher loop

```
every 30 minutes on Framework:
  if NAS reachable on Tailscale:
    pending = GET nas:8080/queue/pending
    for memory in pending:
      thumbnails = fetch top-5 candidate photos at preview size
      response = ollama.chat(qwen2.5vl, [
        system="You are scoring memory-worthiness for a personal photo app.",
        user=[
          "Here are 5 photos from <date>, <years> years ago in <city>.",
          "Metadata: <album_name>, <face_count> faces, ...",
          "1) Score this day 0-10 for 'worth surfacing as a memory'.",
          "2) Pick the single best photo (return its index).",
          "3) Write one sentence (max 12 words) describing the moment.",
          "Reply as JSON.",
          ...thumbnails
        ]
      ])
      if response.score >= 5:
        update queue: chosen_asset_id, caption, status=enriched
      else:
        update queue: status=skipped
```

### 7.3 Why qwen2.5vl:7b

Researched: best small vision model in 2026 for photo understanding. Beats LLaVA at same size. Runs comfortably on Framework Desktop. Fallback to `moondream2` if memory pressure (it's a fraction the size, captions are good if simpler).

### 7.4 Structured output, not free-form

Always JSON. Strict schema: `{score: int, best_index: int, caption: string}`. Parse with pydantic; on parse failure, drop back to heuristic version. No "creative" LLM ramblings ending up in your notifications.

### 7.5 Caption guidelines (prompt-level)

In the system prompt, hard rules:
- Maximum 12 words
- No exclamation marks
- No "amazing!" / "beautiful!" — describe, don't editorialize
- Past tense, second person ("You were…")
- If unsure, return shorter

### 7.6 Phase 2 deliverables

- [ ] `enricher.py` (runs on Framework, polls NAS)
- [ ] Queue HTTP endpoint on NAS (`/queue/pending`, `/queue/update`) — auth with shared secret
- [ ] Tailscale ACL for Framework → NAS:8080
- [ ] Prompt + JSON schema for the vision call
- [ ] Fallback to moondream if qwen fails / OOM
- [ ] Metrics: enrichment success rate, avg latency

**Estimated: 2–3 evenings.**

---

## 8. Phase 3 — Optional Polish

Only build these if Phase 1+2 reveal a need.

- **Weekly digest mode** — Sunday 10am, "best memory from this week across all years." Useful if daily even-with-threshold feels too much.
- **Multi-year notification** — when 2+ years on the same date both score high, send one notification covering both ("You loved this date — 2019 in Lisbon, 2022 in Barcelona").
- **Sentiment filter** — give Ollama context about which dates / albums are hard ones, and have it pre-skip. Manually maintained list.
- **Self-tuning threshold** — track skip rate vs send rate, slowly adjust to hit a target cadence (e.g., "send roughly twice a week").
- **Apple Watch action** — ntfy iOS app surfaces actions on Watch automatically. Just confirm UX.
- **Album auto-blacklist** — if an album has >500 photos, treat as a dump (Screenshots, Documents, etc.) and ignore unless explicitly allowlisted.

---

## 9. Configuration

```yaml
# /config/config.yaml

immich:
  base_url: "http://immich-server:2283"
  api_key: "${IMMICH_API_KEY}"

ntfy:
  base_url: "http://ntfy"
  topic: "memories"

scout:
  schedule: "0 20 * * *"          # 8pm daily
  threshold: 5
  home_gps: [45.8150, 15.9819]    # Zagreb — for "far from home" signal

enricher:
  enabled: true
  poll_interval_minutes: 30
  ollama_url: "http://framework.tailnet:11434"
  vision_model: "qwen2.5vl:7b"
  fallback_model: "moondream2"
  timeout_seconds: 60

filters:
  album_blacklist:
    - "Screenshots"
    - "Documents"
    - "Work"
    - "WhatsApp"

notification:
  language: "en"
  emoji: true
```

---

## 10. Risks & Edge Cases

| Risk | Mitigation |
|---|---|
| No memories for today | Scout exits cleanly, no notification — by design. |
| Same photo somehow queued twice | `UNIQUE(memory_id)` constraint blocks it. |
| Framework offline forever | Heuristic captions ship. Quality slightly lower; system still works. |
| Hard memory surfaces (loss, breakup) | Hide button works in one tap; goes into permanent blocklist. |
| ntfy attachment fetch fails | Notification still sends with text only — degraded but not broken. |
| Reverse geocoder misses (rural GPS) | Body falls back to "<years> years ago today". |
| Immich API changes | Pin Immich version in compose; integration tests against a fixture. |
| LLM hallucinates wrong place / wrong people | Strict prompt: "Only state what you can see. No invented names." JSON parse failure → heuristic fallback. |
| Notification at 9am on a workday is bad timing | Configurable schedule. Default could be 8pm — wind-down time, calmer brain. *(Decide together.)* |

---

## 11. What's Better Than Google Photos

| Dimension | Google Photos | This |
|---|---|---|
| Frequency | Daily, fixed | Only when day earned it |
| Album control | Limited | Full allow/blocklist |
| Hide a memory | Per-photo, awkward | One-tap "Hide forever" |
| Location context | Needs Maps history | EXIF GPS, fully offline |
| AI captions | Cloud Gemini | Local Qwen2.5-VL |
| Privacy | Cloud | Never leaves LAN |
| Algorithm | Black box | Score function in `scout.py` |
| Anniversary handling | Implicit | Explicit override, 1/2/5/10/20 yr |
| ADHD-safe dismiss | No | Yes — Hide button |
| Streaks / counters | Yes (subtle) | Deliberately none |

---

## 12. Build Order

1. **Day 1 (evening 1):** Repo scaffold, Docker compose, hit Immich `/api/memories` from container, parse first response into Python.
2. **Day 1 (evening 2):** SQLite schema, scoring function with `--dry-run`, run against last 30 days of dates to sanity-check the threshold.
3. **Day 2 (evening 1):** Sender + ntfy integration. First real notification on phone. Tune templates.
4. **Day 2 (evening 2):** Hide endpoint + action button. Polish Phase 1.
5. **Live with Phase 1 for 1–2 weeks.** Tune threshold from real data.
6. **Day 3 (evening 1):** Enricher skeleton on Framework, queue API on NAS.
7. **Day 3 (evening 2):** Vision model integration, prompt tuning.
8. **Live with Phase 2 for 1–2 weeks.** Then decide on Phase 3.

The 1–2 weeks of "just live with it" between phases is **intentional**. Tuning a memory system in the abstract is impossible — you only know what you want once you've been getting notifications for real.

---

## 13. Decisions

| # | Question | Decision | Notes |
|---|---|---|---|
| 1 | Notification time | **8pm** | Evening, wind-down mode. Config: `0 20 * * *` |
| 2 | `isSaved` memories | **Boost (+3)** | Past-you voted. Already in score function. |
| 3 | Multiple years same day | **Send both** | Queue all that score ≥ threshold. In Phase 2: rethink to spread them across the evening (e.g. 8pm and 9pm) for special high-score days rather than batch-sending. |
| 4 | Caption language | **English** | All template strings and LLM prompts in English. |
| 5 | Notification sound | **Default** | No custom sound. |
| 6 | Hide button scope | **Entire memory** | `memory_id` goes into `hidden` table. If you dated someone and don't want that trip surfacing again, the whole day is gone — not just one photo from it. |

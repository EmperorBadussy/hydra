<div align="center">

# HYDRA

**Harvesting Your DRM Resource Archives**

*Multi-headed streaming ripper with self-healing modules. Cut off one head, two more grow back.*

[![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python&logoColor=white)](https://python.org)
[![Electron](https://img.shields.io/badge/Electron-33-green?logo=electron&logoColor=white)](https://electronjs.org)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-powered-red)](https://github.com/yt-dlp/yt-dlp)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

</div>

## Overview

HYDRA is a multi-service streaming video ripper with a self-healing plugin architecture. Each streaming service is a separate "head" — a hot-swappable Python module that can be updated independently without touching the core application.

When a streaming service changes its API or DRM, HYDRA automatically pulls updated modules from the `hydra-modules` repository on startup. If a new module fails validation, it automatically rolls back to the last working version. Cut off one head, two more grow back.

### Key Features

- **Self-healing modules** — Service plugins auto-update from GitHub on every launch
- **Multi-service support** — YouTube, Crunchyroll, and 1800+ sites via yt-dlp (more heads coming)
- **Plugin architecture** — Each service is a separate Python module with a standard interface
- **Auto-rollback** — Broken modules revert to last working version automatically
- **Health monitoring** — Continuous validation with auto-disable after repeated failures
- **Download queue** — Concurrent downloads with progress tracking
- **Quality selection** — 4K, 1080p, 720p, 480p, audio-only
- **Electron GUI** — OLED-black interface with green accent theme

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Electron GUI (Green)                   │
│   Search │ Queue │ Module Status │ Settings               │
├────────────────────────┬────────────────────────────────┤
                         │ JSON IPC (stdin/stdout)
├────────────────────────┼────────────────────────────────┤
│                  Python Bridge                            │
│                                                           │
│  ┌──────────────┐  ┌─────────────────────────────────┐  │
│  │   Module      │  │      Service Modules (Heads)     │  │
│  │   Updater     │  │                                   │  │
│  │              │  │  ┌─────────┐ ┌─────────┐         │  │
│  │  • Check     │  │  │  ytdlp  │ │  more   │ ...     │  │
│  │  • Download  │──│  │  .py    │ │  .py    │         │  │
│  │  • Validate  │  │  └─────────┘ └─────────┘         │  │
│  │  • Rollback  │  │                                   │  │
│  └──────────────┘  └─────────────────────────────────┘  │
│         │                                                 │
│    GitHub API                                             │
│    hydra-modules repo                                     │
└─────────────────────────────────────────────────────────┘
```

## Self-Healing System

On every launch, HYDRA:

1. **CHECK** — Fetches `manifest.json` from the `hydra-modules` GitHub repo
2. **COMPARE** — Compares remote module hashes against local copies
3. **DOWNLOAD** — Pulls any changed modules
4. **VALIDATE** — Imports and validates the new module (checks interface, tries instantiation)
5. **ACTIVATE** — Replaces old module with new one
6. **ROLLBACK** — If validation fails, restores the backup automatically

```
LAUNCH → CHECK → COMPARE → [no changes] → READY
                          → [changes found] → DOWNLOAD → VALIDATE → ACTIVATE → READY
                                                       → [fail]   → ROLLBACK → READY
```

## Requirements

### Software
- Python 3.12+
- Node.js 20+
- FFmpeg (for video merging)

### Python Dependencies
```bash
pip install yt-dlp
```

## Installation

```bash
# Clone the repository
git clone https://github.com/EmperorBadussy/hydra.git
cd hydra

# Install Electron dependencies
npm install

# Install Python dependencies
pip install yt-dlp

# Launch
npm start
```

Or use the batch file:
```bash
launch-hydra.bat
```

## Usage

1. **Search** — Type a movie/show name or paste a URL
2. **Select** — Choose quality and format
3. **Queue** — Add to download queue
4. **Download** — HYDRA handles the rest

### Supported Sites

Via yt-dlp: YouTube, Crunchyroll, Vimeo, Dailymotion, Twitch, Reddit, Twitter/X, Instagram, TikTok, Bilibili, and 1800+ more.

## Adding Service Modules

Service modules live in the [hydra-modules](https://github.com/EmperorBadussy/hydra-modules) repo. Each module implements the `BaseService` interface:

```python
class MyService(BaseService):
    def get_info(self) -> ModuleInfo: ...
    def validate(self) -> dict: ...
    def search(self, query, media_type, limit) -> list: ...
    def get_metadata(self, url) -> dict: ...
    def download(self, url, output_dir, quality, progress_callback) -> dict: ...
```

## Part of THE SUITE

HYDRA is part of **THE SUITE** — a collection of tools by EmperorBadussy:

- [**AETHER**](https://emperorbadussy.github.io/aether/) — The Future of Music (player + visualizers)
- [**CHARON**](https://emperorbadussy.github.io/charon/) — The Ferryman of Music (Tidal ripper)
- [**FACELESS**](https://emperorbadussy.github.io/faceless/) — Real-Time Face Swap Engine
- [**HYDRA**](https://emperorbadussy.github.io/hydra/) — Multi-Headed Streaming Ripper

## License

MIT License. See [LICENSE](LICENSE) for details.

## Disclaimer

This software is intended for personal archival and educational purposes. Users are responsible for ensuring their use complies with all applicable laws and the terms of service of content providers. The developers do not condone the use of this software for piracy or illegal distribution.
</div>

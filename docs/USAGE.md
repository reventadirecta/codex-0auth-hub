# Usage and Configuration Guide

This project is a local OAuth/API hub for content workflows. It was originally built for Codex as the first autonomous coding agent, but the architecture is intentionally local, file-based, and command-driven, so it can be reused by other autonomous agents such as Hermes Agent, OpenClaw, Agent Zero, Claude Code, Aider, OpenHands, or any agent that can read files, run shell commands, and follow project-specific instructions.

It is not a SaaS product. It does not upload secrets, and the current workflows only generate local reports and structured files. By default, it does not modify YouTube videos or publish content. If a future workflow is meant to do that, it should state it explicitly.

## 1. What This Project Is

The hub provides a reusable local layer for OAuth and API access across Google services and related content workflows.

It is designed for autonomous agents, but it can also be driven manually from a terminal. Codex was the first use case, not the only one.

The core value is simple:

- local OAuth/API handling
- reproducible commands
- private secrets stored outside version control
- structured reports and exports for analysis
- workflow code that can be adapted to other niches

## 2. What Is Generic And What You Adapt

Generic parts:

- OAuth/API handling
- `secrets/`
- `tokens/`
- config examples
- workflow structure
- `reports/`
- `data/`
- `scripts/`
- Python modules under `oauth_hub/`

Adaptable parts:

- editorial taxonomy
- competitor list
- channel strategy
- workflow prompts
- title and thumbnail rules
- niche and topic priorities

The default workflows are currently optimized for AI, local AI, autonomous agents, ComfyUI, AI video/image generation, AI hardware, and technical creator workflows. To use the hub for another niche, change the taxonomy, competitors config, and workflow criteria.

## 3. Requirements

- Python 3.12 recommended
- Google Cloud project
- OAuth client JSON for Google APIs
- YouTube Data API v3
- YouTube Analytics API
- YouTube Reporting API optional
- Blogger API optional
- Search Console API optional
- Google Custom Search optional and requires `engineId` / `CX`
- Git
- terminal access
- an autonomous agent or manual execution

## 4. Folder Structure

- `oauth_hub/`: shared Python modules and workflow logic
- `scripts/`: command entry points
- `config/`: versioned examples and local config files
- `secrets/`: local OAuth JSON and API key files
- `tokens/`: generated OAuth tokens
- `data/`: generated JSON and CSV exports
- `reports/`: generated Markdown reports
- `docs/`: documentation and usage guides
- `services/`: optional service-specific assets or helpers

The following paths must not be committed:

- `secrets/`
- `tokens/`
- `data/`
- `reports/`
- local config files such as `config/accounts.local.json` and `config/competitors.local.json`

## 5. Initial Setup

1. Clone the repository.
2. Create a virtual environment.
3. Install dependencies.
4. Copy `config/accounts.local.example.json` to `config/accounts.local.json`.
5. Place OAuth JSON files inside `secrets/`.
6. Place API key files inside `secrets/` if needed.
7. Run bootstrap.
8. Inspect the secret filenames.
9. Authenticate the Google services you need.

Example commands:

```powershell
python -m pip install -r requirements.txt
python -m scripts.bootstrap
python -m scripts.inspect_secrets
python -m scripts.auth_google youtube
python -m scripts.test_youtube
```

## 6. Account And API Configuration

The repository includes versioned examples such as `config/accounts.example.json` and `config/accounts.local.example.json`.

Use `config/accounts.local.json` for your real local setup. Never commit it.

OAuth client JSON files belong in `secrets/`. The OAuth flow will create token JSON files in `tokens/`. Never commit either one.

API keys can also live in `secrets/` as `.txt` files or plain files, depending on how the local loader is configured.

The general rule is:

- example config files can be versioned
- local config files stay private
- OAuth JSON files stay private
- token JSON files stay private
- API keys stay private

## 7. Competitor Configuration

`config/competitors.example.json` is versionable.

`config/competitors.local.json` is local only and ignored by Git.

The intended flow is:

1. run `competitor_discovery`
2. review the suggested channels manually
3. curate a small useful competitor list
4. run `competitor_content_scan`

Do not copy hundreds of channels automatically. The competitor list should be small, curated, and relevant.

Example `config/competitors.local.json`:

```json
{
  "channels": [
    {
      "id": "worldofai",
      "name": "WorldofAI",
      "youtubeChannelId": "UC000000000000000001",
      "url": "https://www.youtube.com/@WorldofAI",
      "category": "ai_tutorial",
      "priority": "A",
      "notes": "AI tutorials and packaging ideas."
    },
    {
      "id": "hermesagentexamples",
      "name": "Hermes Agent Examples",
      "youtubeChannelId": "UC000000000000000002",
      "url": "https://www.youtube.com/@HermesAgentExamples",
      "category": "autonomous_agents",
      "priority": "A",
      "notes": "Useful for local agent workflows."
    }
  ]
}
```

## 8. Recommended Workflow Order

Current pipeline:

`channel_diagnosis`
↓
`channel_opportunities`
↓
`video_rewrite_candidates`
↓
`competitor_discovery`
↓
`competitor_content_scan`
↓
`video_rewrite_proposals`

### `channel_diagnosis`

- What it does: analyses the connected channel and writes the base diagnosis.
- Command: `python -m scripts.channel_diagnosis`
- Inputs: YouTube OAuth, YouTube Data API, YouTube Analytics API.
- Outputs: `reports/channel_diagnosis_YYYY-MM-DD.md`, `data/channel_diagnosis/*.json`, `data/channel_diagnosis/*.csv`.
- External APIs: yes.
- Touches real channel: no. It only reads and reports.

### `channel_opportunities`

- What it does: turns the diagnosis into a prioritized action queue.
- Command: `python -m scripts.channel_opportunities`
- Inputs: latest `channel_diagnosis` data.
- Outputs: `reports/channel_opportunities_YYYY-MM-DD.md`, `data/channel_opportunities/*.json`, `data/channel_opportunities/*.csv`.
- External APIs: usually no.
- Touches real channel: no.

### `video_rewrite_candidates`

- What it does: identifies videos that may need editorial changes.
- Command: `python -m scripts.video_rewrite_candidates`
- Inputs: diagnosis and opportunities data.
- Outputs: `reports/video_rewrite_candidates_YYYY-MM-DD.md`, `data/video_rewrite_candidates/*.json`, `data/video_rewrite_candidates/*.csv`.
- External APIs: usually no.
- Touches real channel: no.

### `competitor_discovery`

- What it does: suggests possible competitor channels from the channel context.
- Command: `python -m scripts.competitor_discovery`
- Inputs: rewrite candidate data.
- Outputs: `reports/competitor_discovery_YYYY-MM-DD.md`, `data/competitor_discovery/*.json`.
- External APIs: YouTube Data API v3 public search/read endpoints.
- Touches real channel: no.

### `competitor_content_scan`

- What it does: compares your candidate videos against curated competitor content.
- Command: `python -m scripts.competitor_content_scan`
- Inputs: rewrite candidates plus curated competitors.
- Outputs: `reports/competitor_content_scan_YYYY-MM-DD.md`, `data/competitor_content_scan/*.json`, `data/competitor_content_scan/*.csv`.
- External APIs: YouTube Data API v3 public data only.
- Touches real channel: no.

### `video_rewrite_proposals`

- What it does: generates final editorial rewrite proposals from the full local analysis stack.
- Command: `python -m scripts.video_rewrite_proposals`
- Inputs: diagnosis, opportunities, rewrite candidates, competitor discovery, competitor content scan.
- Outputs: `reports/video_rewrite_proposals_YYYY-MM-DD.md`, `data/video_rewrite_proposals/*.json`, `data/video_rewrite_proposals/*.csv`.
- External APIs: only if Search Intent is available and configured.
- Touches real channel: no.

## 9. What Each Workflow Generates

Workflows write their results to:

- `reports/*.md`
- `data/**/*.json`
- `data/**/*.csv`

Generated reports and data are ignored by Git because they may contain private channel metrics or strategy.

## 10. Adapting The Hub To Another Niche

The default taxonomy is AI-content focused. That is useful if your channel is about:

- AI
- local AI
- autonomous agents
- ComfyUI
- AI video/image generation
- AI hardware
- technical tutorials
- content automation

To adapt the hub to another niche:

For a cooking channel, change taxonomy to recipes, ingredients, appliances, meal prep, and technique.

For a gaming channel, change taxonomy to games, guides, updates, builds, clips, and streams.

For a hardware channel, change taxonomy to GPUs, CPUs, benchmarks, price/performance, and local AI setups.

For an AI creator channel, the defaults are already close.

Review these files first:

- `oauth_hub/rewrite_candidates.py`
- `oauth_hub/rewrite_proposals.py`
- `config/competitors.local.json`
- README strategy notes
- any workflow-specific prompt or criteria blocks

## 11. Security

Never commit:

- `secrets/`
- `tokens/`
- `config/accounts.local.json`
- `config/competitors.local.json`
- `data/`
- `reports/`
- OAuth client JSON
- API keys
- token JSON files
- refresh tokens
- access tokens

Useful checks:

```powershell
git status --short --ignored
git grep -i "AIza"
git grep -i "ghp_"
git grep -i "client_secret"
git grep -i "refresh_token"
git grep -i "access_token"
git grep -i "private_key"
git grep -i "api_key"
```

## 12. Current Workflow State

The current system is editorial and recommendation-driven.

- It does not modify YouTube videos.
- It does not update titles.
- It does not upload thumbnails.
- It does not publish posts.
- It only generates local reports and structured files.

## 13. Known Limitations

- Google Custom Search / Search Intent requires a configured `CX` / `engineId`.
- Competitor analytics are public-only.
- YouTube competitor metrics are limited to public data.
- Editorial recommendations still need human review.
- The default taxonomy is AI-content focused.
- Shorts retention can exceed 100% because of loops.

## 14. Quick Start

Minimum order:

1. Install dependencies.
2. Configure accounts.
3. Authenticate YouTube.
4. Run `channel_diagnosis`.
5. Run `channel_opportunities`.
6. Run `video_rewrite_candidates`.
7. Run `competitor_discovery`.
8. Curate `config/competitors.local.json`.
9. Run `competitor_content_scan`.
10. Run `video_rewrite_proposals`.

## 15. Notes For Future Agents

This repository works well when an autonomous agent follows the local prompt structure, reads the generated reports, and keeps the workflow outputs inside the workspace.

If you switch the niche, update the taxonomy, competitor list, and scoring rules before trusting the recommendations.

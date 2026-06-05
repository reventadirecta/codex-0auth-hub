# OAuth Hub

Local workspace for managing OAuth and API key connections across multiple Google services and accounts.

Everything stays inside this folder:

```text
C:\Workspaces\Codex\oauth-hub
```

## Layout

- `config/`: account, channel, blog, and search engine mapping.
- `secrets/`: OAuth JSON files and API key text files. Ignored by Git.
- `tokens/`: generated OAuth login tokens. Ignored by Git.
- `oauth_hub/`: shared local Python helpers.
- `scripts/`: commands for setup, login, and connection tests.
- `data/`: raw exports and derived datasets for repeatable analysis.
- `reports/`: generated Markdown reports.

## Setup

Install dependencies from this folder:

```powershell
python -m pip install -r requirements.txt
```

Create the local config:

```powershell
python -m scripts.bootstrap
```

Your Google OAuth JSON can stay in `secrets/`. If `googleClientSecretFile` is set to `auto`, the scripts use the first `.json` file found there.

API key files can be stored either with or without `.txt` in the config. The loader accepts both forms and looks in `secrets/`.

## Supported APIs

- `youtube`: YouTube Data API v3 through OAuth. Already working with `youtube.readonly`.
- `youtube_data`: YouTube Data API v3 through API key. Useful for read-only public channel checks.
- `youtube_analytics`: OAuth only. Needs `youtube.readonly` and `yt-analytics.readonly`.
- `youtube_reporting`: OAuth only. Needs `yt-analytics.readonly` for standard reports.
- `blogger`: Blogger API through OAuth.
- `search`: Google Custom Search JSON API through API key plus `engineId`.
- `search_console`: Google Search Console API through OAuth with `webmasters.readonly`.

## Commands

Show configured connections:

```powershell
python -m scripts.list_connections
```

Inspect secret filenames without printing their contents:

```powershell
python -m scripts.inspect_secrets
```

Authenticate YouTube:

```powershell
python -m scripts.auth_google youtube
```

Test YouTube:

```powershell
python -m scripts.test_youtube
```

Test YouTube Data API v3 with the API key in `secrets/`:

```powershell
python -m scripts.test_youtube_data_api
```

Authenticate Blogger:

```powershell
python -m scripts.auth_google blogger
```

Test Blogger:

```powershell
python -m scripts.test_blogger
```

Test Google Custom Search:

```powershell
python -m scripts.test_search "test search"
```

Authenticate Search Console:

```powershell
python -m scripts.auth_google search_console
```

Test Search Console:

```powershell
python -m scripts.test_search_console
```

Authenticate YouTube Analytics:

```powershell
python -m scripts.auth_google youtube_analytics
```

Test YouTube Analytics:

```powershell
python -m scripts.test_youtube_analytics
```

Authenticate YouTube Reporting:

```powershell
python -m scripts.auth_google youtube_reporting
```

Test YouTube Reporting:

```powershell
python -m scripts.test_youtube_reporting
```

Generate the channel diagnosis report:

```powershell
python -m scripts.channel_diagnosis
```

Generate the editorial opportunities queue from the latest diagnosis:

```powershell
python -m scripts.channel_opportunities
```

Use a specific diagnosis date:

```powershell
python -m scripts.channel_opportunities --date 2026-06-05
```

## Current Constraints

- Google Custom Search also needs a Programmable Search Engine ID in `engineId`.
- Search Console does not work from an API key alone for the main account/site methods in this hub. It needs OAuth plus access to at least one property.
- YouTube Analytics and YouTube Reporting do not use the existing `youtube.readonly` token by themselves. They need additional OAuth scopes and will create separate token files the first time you authorize them.
- YouTube and Blogger existing tokens are reused and are not regenerated unless you explicitly authorize a different scope set.

## Security Notes

- Never commit files from `tokens/`, `secrets/`, or `credentials/`.
- Keep one clear entry per account/channel/blog/project in `config/accounts.local.json`.
- Do not paste real secrets into chat unless there is no other option.

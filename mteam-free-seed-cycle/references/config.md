# Configuration

Store this JSON outside the skill and Git repository:

```json
{
  "mteam_base": "https://api.m-team.io/api",
  "mteam_api_key": "replace-with-api-access-token",
  "qbittorrent_url": "http://127.0.0.1:8080",
  "save_path": "D:\\PT\\MTeam",
  "max_active_downloads": 3,
  "max_torrent_gib": 10
}
```

Get the API Access Token through M-Team's official control panel. Use an allowed qBittorrent version and a local Web API endpoint that is authenticated or otherwise safely restricted. Do not put a token in source control, shell history, screenshots, or chat.

The script uses `mteam_base`, `mteam_api_key`, `qbittorrent_url`, and `save_path`. The two limits are optional and default to 3 active downloads and 10 GiB.

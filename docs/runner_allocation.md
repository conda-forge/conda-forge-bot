# GitHub Runner Allocation

Last Updated: 2025-05-29

The bot has moved to `conda-forge` which has many more runners available than the `regro` GitHub org.
Thus, we could increase these runner counts. For now, we have left them the same until the bot has
stabilized.

These are split across our workflows as follows:

- `bot-bot` - 1 runner
- `bot-cache` - currently disabled
- `bot-events` (on demand, responds to GitHub webhook events) - any available runner
- `bot-feedstocks` - 1 runner
- `bot-make-graph` - 1 runner
- `bot-make-migrators` - 1 runner
- `bot-prs` - 4 runners
- `bot-pypi-mapping` - 1 runner
- `bot-update-status-page` - 1 runner
- `bot-update-nodes` - 3 runners
- `bot-versions` - 6 runners
- `docker` (on demand) - 1 runner
- `bot-keepalive` (periodic) - 1 runner
- `relock` - 1 runner
- `test-model` (daily for ~4 minutes, on demand) - 1 runner
- `tests` (on demand) - 1 runner

Total: 16 runners used permanently, 4 runners can be used on demand.

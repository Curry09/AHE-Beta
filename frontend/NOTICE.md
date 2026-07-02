# Third-party attribution

The pixel-town rendering engine and its art assets under:

- `src/components/game/**`
- `src/lib/{events,logger,constants}.ts`
- `src/types/game.ts`
- `public/{maps,tilesets,characters,sprites,fonts}/**`

are adapted from **Agent Town** (https://github.com/geezerrrr/agent-town),
licensed under the MIT License. Original copyright © the Agent Town authors.

We reuse the Phaser scene/entities/systems and pixel assets, and drive them
from our own backend data (agents / issues / commits / sessions) instead of the
upstream OpenClaw gateway. The upstream gateway / HUD / task-execution layers
are not included.

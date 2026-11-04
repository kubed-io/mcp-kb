---
name: hooked
description: Has deep frontmatter.
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: echo never-run
metadata:
  owners: [a, b]
  limits: {depth: 3, nested: {ok: true}}
---
Hooked.

---
name: project_test
description: Compile every project Python file without executing it, and run import and configuration checks.
parameters:
  scope:
    type: string
    description: syntax, imports, config, or all. Default all.
    default: all
examples:
  - action: project_test
    arguments:
      scope: syntax
usage_notes:
  - Use syntax after code edits; use all before declaring a change complete.
---

---
name: project_test
description: Compile project Python files, check imports and configuration, and run the unittest suite.
parameters:
  scope:
    type: string
    description: syntax, imports, config, tests, or all. Default all.
    default: all
examples:
  - action: project_test
    arguments:
      scope: syntax
usage_notes:
  - Use syntax for a fast compile check, tests for the deterministic unittest suite, and all before declaring a change complete.
---

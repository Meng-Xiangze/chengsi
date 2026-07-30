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
  - This is an opt-in tool. Use it only when the user asks for project tests, health checks, syntax checks, imports, or configuration validation.
  - Do not call it automatically after edits or ordinary file operations.
---

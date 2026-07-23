---
name: tool_creator
description: Create, update, or delete tools in the tools/ directory.
parameters:
  action:
    type: string
    description: "One of: 'create', 'delete', 'template'."
  tool_name:
    type: string
    description: The unique name for the new tool (no .py suffix).
  code:
    type: string
    description: "[create] Full Python source for the tool class."
  description:
    type: string
    description: "[create] One-line description for the TOC catalog."
examples:
  - action: tool_creator
    arguments:
      action: template
  - action: tool_creator
    arguments:
      action: create
      tool_name: "weather_fetcher"
      description: "Fetch weather info for a city"
      code: "from tools.base import BaseTool\n\nclass WeatherFetcher(BaseTool):\n    @property\n    def tool_name(self): return 'weather_fetcher'\n    @property\n    def description(self): return 'Fetch weather info'\n    @property\n    def parameters(self): return {'city': {'type': 'string', 'description': 'City name'}}\n    def run(self, args): return f'Weather in {args[\"city\"]}: Sunny 25C'\n"
  - action: tool_creator
    arguments:
      action: delete
      tool_name: "weather_fetcher"
usage_notes:
  - "STEP 1: Call action='template' to get the skeleton."
  - "STEP 2: Fill in the skeleton with your logic."
  - "STEP 3: Call action='create' with the filled code."
  - The tool class MUST inherit from BaseTool and implement: tool_name, description, parameters, run.
  - create auto-generates: .py file + .md doc + TOC.md entry.
  - delete removes: .py + .md + TOC.md entry.
---

# tool_creator

A meta-tool that lets you create, update, or delete tools at runtime.

## Workflow

1. **Get the template** — call `action: "template"` to receive a ready-to-fill skeleton
2. **Fill in** the skeleton with your tool logic
3. **Create** — call `action: "create"` with your filled `code`

## Parameters

| Name | Type | Description |
|------|------|-------------|
| `action` | string | `template`, `create`, or `delete` |
| `tool_name` | string | Tool name (used as filename, no `.py`) |
| `code` | string | (create) Full Python source for the tool class |
| `description` | string | (create) One-liner for TOC catalog |

## Required Structure

Your code **must** have:
- Class inheriting from `BaseTool`
- `tool_name` property returning the tool's name string
- `description` property returning a one-line description
- `parameters` property returning a dict of parameter schemas
- `run(self, arguments: dict) -> str` method

## Validation

If your code is missing any required part, creation will fail with specific errors pointing out what's missing.

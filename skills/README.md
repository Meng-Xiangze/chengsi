# Local Skills

Create one directory per optional capability:

```text
skills/
  my-skill/
    SKILL.md
    references/
    scripts/
```

`SKILL.md` must begin with `name:` and `description:` front matter. Chengsi loads only these two fields into the system prompt. The full file remains on disk for the model to read when the skill is relevant.

Keep skills focused on reusable instructions and references. Put executable model-callable capabilities in `tools/` as Python `BaseTool` implementations.

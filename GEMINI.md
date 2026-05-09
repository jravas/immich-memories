# immich-memories

immich-memories project.

## Commands

```bash
pnpm dev          # Start dev server
pnpm build        # Production build
pnpm lint:fix     # ESLint auto-fix
pnpm sync:llm-config   # Sync rules -> all AI tool directories
```

## AI Config Architecture

Source of truth for all AI tool configuration lives in `llm/`:

- `llm/rules/` — scoped rules (frontmatter: `description`, `scope`)
- `llm/agents/` — specialist agent definitions
- `llm/skills/` — on-demand skill workflows

Run `pnpm sync:llm-config` to generate tool-specific files in `.cursor/rules/`, `.claude/rules/`, `.github/instructions/`, `.gemini/context/`. These generated files should not be edited directly.

## Boundaries

### Always

- Run lint after editing code files
- Follow existing patterns and conventions

### Ask First

- Adding new dependencies
- Changing database schema or migrations

### Never

- Edit generated files (types, schemas)
- Commit `.env` or secrets

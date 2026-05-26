# Docs index: configurable grouping and sorting

Date: 2026-05-25
Status: Approved (design)
Scope: `web/src/memory_web/routes/docs.py`, `web/src/memory_web/templates/docs_index.html`, i18n strings.

## Problem

`/docs` currently hardcodes:

- grouping by `type` (with `markdown` / `html` fallback for unregistered files);
- intra-group sorting by lowercase `title`.

Users want to also browse docs grouped by **project** and sorted by **time** without losing the existing modes.

## Goals

- Add two independent dropdowns on `/docs`:
  - `group` ∈ {`type`, `project`}, default `type`.
  - `sort` ∈ {`name`, `modified`}, default `name`.
- All four combinations work.
- Selection survives via query parameters (`?group=...&sort=...`) and composes with existing filters (`type`, `format`, `project`, `tag`, `indexed`, `q`).
- Backwards compatible: visiting `/docs` with no new params behaves exactly as today.

## Non-goals

- No `created` field added to `docs/index.json`. Time-based sort uses the existing `modified` field.
- No ascending/descending toggle. `name` is ascending, `modified` is descending (newest first). These are the standard expectations for those keys; one switch is enough.
- No change to `adapter.list_docs()` shape. Existing fields (`title`, `modified`, `projects`, `rel`) are sufficient.
- No change to `docs/index.json` schema, the single-doc view, or the filter/search behavior.
- No new behavior for raw unregistered .md/.html files beyond what already exists.

## Data sources

| Field used     | Source                                                              | Notes                                              |
| -------------- | ------------------------------------------------------------------- | -------------------------------------------------- |
| `title`        | `adapter.list_docs()[*]["title"]` (with `rel` fallback already done) | Sort key for `sort=name`.                          |
| `modified`     | `adapter.list_docs()[*]["modified"]`                                | ISO date string `YYYY-MM-DD`. Missing for unindexed raw files. |
| `projects`     | `adapter.list_docs()[*]["projects"]` (list, may be empty)           | Group key for `group=project`.                     |
| `type`         | `adapter.list_docs()[*]["type"]`                                    | Group key for `group=type` (unchanged).            |

## Route changes — `routes/docs.py`

### New query params

```python
group: str | None = None   # "type" | "project", default "type"
sort: str | None = None    # "name" | "modified", default "name"
```

Normalize identically to existing params (strip, empty → None, then fall back to defaults). Unknown values fall back to defaults (no 400). This matches the lenient handling already used for the other filter selects.

### Grouping

Replace the current `by_type` block with a single grouping pass parameterized by `group`:

- `group=type`: key = `item.get("type") or "wiki"` — preserves current behavior, including the `markdown`/`html` fallback that `adapter.list_docs()` already assigns to unregistered raw files.
- `group=project`:
  - For each item, iterate `item.get("projects") or []` and append the item to each project's bucket.
  - If the list is empty, append the item to a special bucket keyed by a sentinel constant `NO_PROJECT_KEY = "__no_project__"` (an unambiguous string that cannot appear as a real project name).

A single doc appearing in N projects appears in N groups. This is intentional and was confirmed with the user.

### Intra-group sorting

- `sort=name`: sort ascending by `(item.get("title") or item.get("rel") or "").lower()` — identical to current.
- `sort=modified`: sort by `modified` **descending**. Items with missing/empty `modified` sort to the end of the group. Tiebreaker: lowercase `title` ascending, so identical dates remain deterministic.

Implementation note: build a sort key that pushes `None`/`""` to the end regardless of direction, e.g. `(0, "-" + modified) if modified else (1, "")` with `reverse=False`, or equivalent.

### Inter-group ordering

- For `group=type`: alphabetical by group key, ascending. Matches current.
- For `group=project`: alphabetical by project name, ascending; the `NO_PROJECT_KEY` group is appended last regardless of locale.

Render the sentinel group with an i18n label (`docs.group.no_project`, e.g. `(无项目)` / `(no project)`).

### Template context additions

Add to the existing `TemplateResponse` context:

```python
"selected": {
    ...
    "group": group_value,   # "type" | "project"
    "sort": sort_value,     # "name" | "modified"
},
"no_project_key": NO_PROJECT_KEY,   # so the template can detect the special group
```

Rename the existing `by_type` key to `groups` (or leave it as `by_type` — see Open Questions). The template iteration is unchanged in structure.

## Template changes — `docs_index.html`

Add two `<select>` controls inside the existing `<form class="filters">`, placed before the `q` text input so the visual order reads: type / format / project / tag / indexed / **group / sort** / q.

```html
<label>{{ t('docs.filter.group') }}
  <select name="group">
    <option value="type"    {% if selected['group'] == 'type'    %}selected{% endif %}>{{ t('docs.group.type') }}</option>
    <option value="project" {% if selected['group'] == 'project' %}selected{% endif %}>{{ t('docs.group.project') }}</option>
  </select>
</label>
<label>{{ t('docs.filter.sort') }}
  <select name="sort">
    <option value="name"     {% if selected['sort'] == 'name'     %}selected{% endif %}>{{ t('docs.sort.name') }}</option>
    <option value="modified" {% if selected['sort'] == 'modified' %}selected{% endif %}>{{ t('docs.sort.modified') }}</option>
  </select>
</label>
```

The section header continues to render the group key:

```html
<h2>{% if key == no_project_key %}{{ t('docs.group.no_project') }}{% else %}{{ key }}{% endif %} · {{ group|length }}</h2>
```

Reset link (`/docs`) must not include `group` or `sort` — clicking reset returns to defaults.

## i18n keys

New keys (add to whatever translation file currently holds `docs.filter.type` and siblings):

| Key                       | en (suggested)   | zh (suggested) |
| ------------------------- | ---------------- | -------------- |
| `docs.filter.group`       | Group by         | 分组           |
| `docs.filter.sort`        | Sort             | 排序           |
| `docs.group.type`         | type             | 类型           |
| `docs.group.project`      | project          | 项目           |
| `docs.group.no_project`   | (no project)     | (无项目)       |
| `docs.sort.name`          | name             | 名称           |
| `docs.sort.modified`      | modified ↓       | 修改时间 ↓     |

The `↓` glyph in `docs.sort.modified` hints to the user that this key sorts descending without needing a separate control.

## Edge cases

- **No items match filters**: existing empty-state branches (`grand_total > 0` vs `else`) are unchanged.
- **`sort=modified` with missing `modified`**: such items sort to the end of their group. Common for raw unregistered files; their `modified` is `None` from `adapter.list_docs()`.
- **Duplicate doc across project groups**: `total` and "n docs" counter at the top remain the count of *unique* filtered items (computed before grouping), so they don't inflate when `group=project`.
- **Reset button**: `<a class="row" href="/docs">` already discards all query params — no change needed.
- **Unknown `group` / `sort` values**: fall back to defaults silently.

## Testing strategy

Add tests under whatever test layout `web/` uses for routes (or extend existing `test_memory_tool.py` if web routes aren't tested separately — to be confirmed during implementation):

1. `/docs?group=type&sort=name` → identical to today's behavior (regression guard).
2. `/docs?group=project` → docs with N projects appear in N groups; docs with no project appear in the special group at the end.
3. `/docs?sort=modified` → within a group, items ordered by `modified` descending; missing `modified` at the end.
4. `/docs?group=project&sort=modified` → both effects combine.
5. `/docs?group=garbage&sort=garbage` → falls back to defaults without error.
6. `/docs?group=project&project=X` → existing project filter narrows down first, then groups only by remaining projects (which will all equal X — trivially one group, but verifies the order: filter → group).

If web routes don't yet have tests, the implementation plan should decide whether to add a minimal test scaffold or rely on manual verification.

## Open questions for implementation

1. Whether to rename the template context key `by_type` → `groups`. Renaming is cleaner but touches the template variable names; keeping `by_type` is a misleading name. **Decision:** rename to `groups` during implementation; it's a one-file change.
2. Where i18n keys live and whether en/zh files both need updates — discovered during implementation by following `docs.filter.type`.
3. Whether `web/` has any existing route tests — discovered during implementation.

# `frontend/admin.css`

> Extra styles for the admin page on top of [`style.css`](style.css.md): cards, the mapping table, chips and the filter checkboxes.

**Part of:** [Admin upload](../../flows/admin-upload.md)  ·  **Layer:** UI

## Purpose
The admin page is a form with a wide table, not a chat. It needs a page that grows with its content, card boxes for the three steps, and a table that can scroll sideways. It reuses the colour variables from `style.css`, so dark mode works the same way.

## How it works
1. `body.admin` switches the body from a fixed full-height chat layout to `height: auto`, so the page scrolls normally.
2. `.admin-main` widens the content to 1100 px.
3. The rest styles the step cards, the table and the result.

## Key components
- `.card`, `.card h2`: one box per step.
- `.row`: the upload form in one wrapping line.
- `.muted`, `.small`, `.error` (red), `.ok` (green).
- `input, select`, `button.primary` ("Build index"), `button:disabled`.
- `.chips span`, `.chips span.new`: dimension chips; new dimensions in green.
- `.table-wrap` (horizontal scroll), `table`, `th`, `td`, `td.examples` (cut with an ellipsis), `tr.known td:first-child::after` (adds " ✓" after known columns), `tr.ignored td` (faded), `td input.dim`.
- `#filters .filter`, `#filters label`, `#result ul`.

## Configuration
None.

## Dependencies
- **Used by:** [`admin.html`](admin.html.md).
- **Uses:** CSS variables defined in [`style.css`](style.css.md).

## Example
A row `<tr class="known ignored">` for "Contact person" shows "Contact person ✓" faded to 55% opacity: known from the current mapping and set to `ignore`.

## Known limitations and improvements
- `.muted`, `.error` and the `input, select` rules are global; they also apply to any element with those classes on the admin page. Fine at this size.
- `td.examples` cuts long values; the full list is only in the tooltip, which touch screens do not show.

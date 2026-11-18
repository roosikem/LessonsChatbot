# `frontend/style.css`

> The look of the chat page (and the base look of the admin page): colours, layout, message bubbles, lesson cards and the confidence colours.

**Part of:** [Ask a question](../../flows/ask-a-question.md)  ·  **Layer:** UI

## Purpose
The answer must be easy to scan: which lessons, how sure, why relevant. This file gives each lesson its own card, shows the confidence in green, amber or red, shows "why relevant" reasons as small chips, and greys out the quote. It also gives a dark mode and a narrow-screen layout.

## How it works
1. Colours are CSS variables on `:root` (`--bg`, `--panel`, `--text`, `--muted`, `--border`, `--accent`, `--accent-soft`, `--high`, `--medium`, `--low`, `--quote`).
2. `@media (prefers-color-scheme: dark)` sets darker values for the same variables, so dark mode follows the operating system.
3. `body` is a full-height column: header on top, the thread in the middle scrolls (`main { flex: 1; overflow-y: auto }`), the question form stays at the bottom.
4. Below 640 px width the header stacks and paddings shrink.

## Key components
- Header: `header`, `.brand`, `.sub`, `.header-right`, `.pill` (model badge), `.toggle`.
- Messages: `.msg.user .bubble` (right side, accent colour), `.bot .summary`, `.bot .clarify` (soft box with a left bar, used for clarifying question, "related only" note and next step), `.bot .notfound` (muted italic), `.bot .error` (red).
- Progress: `.steps li` with a `›` prefix, `.steps li.candidates`, `.spinner::after` (a blinking `…`).
- Lesson card: `.lesson`, `.lesson-head`, `.lesson-id` (monospace), `.confidence.high|medium|low` (green/amber/red, upper case), `.learning`, `.reasons li` (round chips), `.quote` (hidden when empty via `.quote:empty`), `.original`, `.context` (two-column grid of dimension and values).
- Actions: `.lesson-actions`, `.spacer`, `.vote`, `.vote.chosen` (the clicked thumb), `.related`, `.answer-actions`.
- `.debug`: monospace block for the debug JSON.
- Form: `form#ask`, `textarea` (max height 160 px), `#send` and `#send:disabled`.

## Configuration
None.

## Dependencies
- **Used by:** [`index.html`](index.html.md) and [`admin.html`](admin.html.md) (the admin page loads this first, then [`admin.css`](admin.css.md)).
- **Uses:** nothing.

## Example
`<span class="confidence high">high</span>` shows "HIGH" in `--high` (`#1d7a46` in light mode, `#5cc489` in dark mode).

## Known limitations and improvements
- Dark mode follows only the system setting; there is no in-page switch.
- `body { height: 100vh }` can be a little too tall on mobile browsers with a moving address bar. Idea: use `100dvh` where supported.
- The confidence colour is the only hint besides the word; the word is always shown, so colour-blind users still get it.

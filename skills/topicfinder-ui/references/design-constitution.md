# TopicFinder design constitution

This is the established visual language extracted from the shipped Profile,
Publish, Create/HEIT, and Contacts admin surfaces on 2026-09-10. Use it as
agent judgment for every TopicFinder UI surface. The brand is the polish.

## System

Use a light theme, white surfaces, one blue accent, generous whitespace, soft
1px borders, rounded corners, and subtle stateful motion. Prefer real data over
decoration. If a screen is busy, remove elements rather than shrinking them.
Use one accent only. No decorative gradients except one hero radial glow per
page. Green, red, and amber are functional status colors only. Dark surfaces
belong only to content chrome such as video players, phone previews, and toasts.

## Tokens

Use CSS variables from `src/app/globals.css` or their Tailwind mappings. Never
paste hex values into components.

| Token | Value | Use |
|---|---|---|
| `--accent` | `#02B2F7` | CTAs, active states, links, focus rings, highlights |
| `--surface-base` | `#FFFFFF` | Page background |
| `--surface-elevated` | `#FFFFFF` | Cards and modals |
| `--surface-raised` | `#F9FAFB` | Wells, input backgrounds, hover fills |
| `--text-primary` | `#0A0A0A` | Headings and key values |
| `--text-secondary` | `#6B7280` | Body copy and descriptions |
| `--text-tertiary` | `#9CA3AF` | Meta, timestamps, placeholders |
| `--border-subtle` | `#E5E7EB` | All borders |

## Type and layout

Use the app sans stack everywhere and mono only for code. Pages begin with a
`text-2xl font-bold` title and one-line `text-sm` tertiary description. Eyebrows
are small, uppercase, tracking-wide, and tertiary. Body is `text-sm`; meta is
`text-xs`; never go below `text-xs`. Use the 4px spacing rhythm, `py-8` between
major sections, and `mx-auto max-w-6xl px-4 sm:px-6` for content columns. Use
sentence case. UI copy contains no em dashes.

## Shape and icons

Use `rounded-full` for pills, chips, avatars, and small buttons; `rounded-2xl`
for cards and modals; `rounded-xl` for inputs and small panels. Elevation is a
subtle border plus shadow, never gray-on-gray. Use lucide-react stroke icons at
16-20px. lucide has no brand icons. Extend
`src/components/publish/platform-icons.tsx` for social marks; do not paste
random SVGs.

## Motion

Use the existing `animate-fade-in`, `animate-fade-in-up`, `animate-shimmer`,
`animate-pulse-cyan`, and `animate-pulse-accent` utilities. Use CSS only. Keep
interactive transitions at or below 200ms ease-out. Motion communicates state:
in-progress pulses and done settles. Animate real values only. Respect
`prefers-reduced-motion`.

## States

Every list, grid, and detail surface should have a layout-matched shimmer
skeleton, a designed empty state with an icon, warm sentence, and filling CTA,
inline loading during actions with an in-flight guard, an actionable error with
Retry where appropriate, and success feedback. Cheap-to-reverse destructive
actions use an Undo toast. Use `window.confirm` only for hard deletes.

## Overlays

Fullscreen overlays portal to `<body>` through
`src/components/publish/body-portal.tsx`. Use z-index 30 for the sidebar, 50
for overlays, and 60 for toasts. Do not invent tiers. Overlays have a
`rgba(4,10,20,0.6)` scrim, click-outside and Escape close, a top-right close
button, and a rounded card with fade-in-up. Fullscreen HEIT and Publish modes
own the whole viewport with a title bar and no app chrome.

## Interaction

For row-to-detail, make the name or title the button target rather than making
the whole row clickable. Use pills for platform toggles, filters, and statuses.
Use segmented controls for two or three view switches. Dragging shows a live
drop target and ends with an Undo toast. Status chips use a dot and label, with
pulsing in-progress states. Validate inputs live with block or warn severity,
explain the rule, show character counters, disable invalid submits, and put
errors under fields. Never use `alert()`.

## Media and data

Use platform chrome for previews when showing how content will look; otherwise
use plain rounded 9:16 frames. Images need alt text, decorative images use
`alt="" aria-hidden`, new marketing images use `next/image`, and images over
400KB need attention. Use real data, medians for analytics, `n` beside aggregate
claims, percentages for engagement, sortable tables over roughly ten rows, and
raised table headers with row hover.

## Accessibility and copy

Show focus states on every focusable element. Give icon-only buttons an
`aria-label`; dialogs have roles; Escape works. Verify actual foreground and
background contrast rather than assuming a token is sufficient. The floor is
`--text-tertiary` on white. Run the repository's normal typecheck, lint, and
build checks for changed UI, and confirm the five states are reachable when the
surface supports them. Defer effect state updates with the existing
`requestAnimationFrame` pattern where required by the lint rule.

Copy is short, direct, confident, and actionable. No exclamation marks,
corporate filler, or vague teases. Buttons state their outcome. Empty states
are warm and directive. Errors are honest and actionable. State limits or
costs beside the triggering control.

## References

Open these first when the pattern applies: `src/app/page.tsx` and
`src/components/sidebar.tsx` for tab shells; `src/components/publish-view.tsx`
and `src/components/publish/publish-composer.tsx` for the premium bar;
`src/components/heit-stepper.tsx` for fullscreen work; the Contacts tab in
`src/components/admin-dashboard.tsx` for drawers and tables; and
`src/components/skeletons/` for loading states.

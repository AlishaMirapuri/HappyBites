# HappyBites — Design README

> **Scope:** covers the full UI redesign of the Streamlit frontend, from system thinking to implementation.

---

## TL;DR

HappyBites is a restaurant deal discovery app focused exclusively on **happy hours** and **lunch specials**. I redesigned it end-to-end with a system I call **Candy Glass** — a premium glassmorphic design language that's vibrant enough to feel fun but structured enough to feel trustworthy. The redesign prioritizes speed to first value, scannable deal cards, and a modal interaction that feels native rather than browser-default. Every visual decision was made in-code, so the design system is the implementation.

---

## Context & Problem

HappyBites surfaces AI-ranked restaurant deals — specifically **happy hours** and **lunch specials** — near the user's location. The backend is capable — multi-source ingestion, ML ranking, venue deduplication — but the original frontend was a raw Streamlit default: gray, flat, no visual hierarchy, no delight.

The problem wasn't features. It was **presentation credibility**. A deal app that looks cheap signals cheap deals. Users would land on the page, see a wall of text-based results, and mentally discount the product before reading a single deal.

Secondary problem: Streamlit's default component system is coarse. Everything defaults to full-width, 12px system font, and zero motion. Making it feel like a real product required a fully custom CSS layer injected at runtime.

---

## Users & Jobs-to-be-Done

**Primary user:** Urban diners — people who are already planning to eat out and want to find the best happy hour or lunch deal nearby. They're not coupon-clippers; they're spontaneous, mobile-adjacent, and have high visual standards because they use Airbnb, Uber Eats, and Spotify daily.

| Job to be done | Design implication |
|---|---|
| "Show me something good near me, fast" | Cards above the fold, zero required input on load |
| "Is this deal actually worth it?" | Price, discount %, and distance visible at a glance |
| "I want to book right now" | Modal with reservation slots, no page navigation |
| "I don't want to wade through junk" | Ranking signals surfaced as human-readable reasons |

---

## Design Principles

1. **Scannable before readable.** Every card communicates its value proposition (discount, distance, category) in under 2 seconds without requiring the user to read body text.

2. **Delight without distraction.** Motion exists to give feedback and create perceived quality — not to perform. Animations run once, are short (≤420ms), and never block interaction.

3. **Glass, not plastic.** Glassmorphism signals premium. But it fails when overused. I applied it only to surfaces that float above content (cards, modals, badges) and kept the page background warm and solid.

4. **The system is the component.** Every spacing value, color, and radius comes from a CSS token. I don't write `#6B46C1` twice. This makes QA fast: if something looks wrong, I fix one token and everything heals.

5. **Hierarchy through weight, not size alone.** Deal titles are heavy (800) and compact (−0.45px tracking). Supporting metadata is light and muted. I use font weight as the primary hierarchy signal and size as secondary.

6. **Reduce cognitive load at every branching point.** The tab bar has three items. The deal card has one primary CTA. The modal has one confirm action. Every screen asks the user to make at most one decision.

7. **Mock boldly; label honestly.** Where the backend returns no data (nearby search, reservations), I surface realistic mock data rather than an empty state. Users understand the product's potential; empty states teach nothing.

---

## Visual System

### Color Tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#FFF8F0` | Page background (warm off-white) |
| `--primary` | `#6B46C1` | Brand purple — CTAs, prices, active states |
| `--accent` | `#F953A0` | Hot pink — badges, hover pops, sale indicators |
| `--mint` | `#2DD4BF` | Nearby tab accent, "Coming up" section |
| `--amber` | `#F59E0B` | Profile tab accent, warnings |
| `--gn` | `#10B981` | Positive states (confirmed, saved) |
| `--rd` | `#EF4444` | Errors, expired |
| `--ink` | `#1A0A2E` | Primary text — deep purple-black, not pure black |
| `--muted` | `#7C6E8A` | Secondary text, metadata |
| `--glass` | `rgba(255,255,255,0.65)` | Card / modal surface |
| `--glass-border` | `rgba(255,255,255,0.80)` | Card borders |
| `--grad-brand` | `135deg, #6B46C1 → #9333EA → #F953A0` | Hero elements, primary buttons |

### Typography

- **Display:** `Inter` / `system-ui` — tight tracking (−0.45 to −0.75px) on all headings for a contemporary editorial feel.
- **Monospaced prices:** `DM Mono` — prices read differently from copy. Using a monospace face for `$XX.XX` lets the eye parse numbers faster and reinforces the "data" nature of a price.
- **Scale:** 3 sizes cover 90% of the UI (11px metadata, 13–14px body, 19–20px titles). I deliberately avoid a crowded typographic scale.

### Shape Language

Single radius token ladder: `--r-sm` (8px) → `--r-md` (12px) → `--r-lg` (20px) → `--r-xl` (28px) → `--r-full` (999px). Larger radii on larger surfaces. Buttons and badges use `--r-full` to feel friendly. Cards use `--r-xl` to feel premium.

### Layout

Max content width is 1120px with responsive gutters. Deal cards render in a 2-column grid that collapses gracefully. The nearby search controls use a 4-column row that stacks at <900px. I intentionally don't use a sidebar — the page structure is linear and progressive.

### Components

- **Deal card:** glassmorphic tile with entrance animation, category badge, price delta, discount badge, distance chip, and rank reasons. One primary CTA.
- **Deal modal:** `@st.dialog` — photo hero with a dark scrim overlay, merchant name, reservation slot grid, location pill with Google Maps routing, confirm flow.
- **Stat boxes:** "big number" tiles used in context sections for scannable at-a-glance counts.
- **Section headers:** oversized background label (low opacity) + foreground kicker/title. Adds depth without requiring real imagery.

---

## Interaction & Motion

### What animates

| Element | Animation | Why |
|---|---|---|
| Deal cards | `card-in` — translateY(20px) → 0 + fade, staggered 45ms per card, capped at 5 cards | Signals new content loading; stagger gives structure to a grid |
| Page hero | `hero-item` — translateY(16px) → 0, sequenced across kicker/title/subtitle | Creates a reading rhythm; makes the page feel alive on first load |
| Tab indicator | CSS transition, `--dur-base` (280ms), `ease-out` | Smooth state change without feeling sluggish |
| Modal open | Native Streamlit dialog + backdrop blur | Contextual focus shift; no page-leave |
| Hero photo | `scale(1.03)` on hover, `--dur-slow` (420ms) | Tactile feedback; signals the image is clickable/interactive |

### What I intentionally did NOT animate

- **Hover color transitions** no longer use spring easing (`cubic-bezier(0.34,1.56,0.64,1)`). Spring is right for transforms (it adds physical weight). On `background-color` it creates a jarring bouncy color shift. All color transitions use `ease-out`.
- **Report buttons** (`Wrong?` / `Expired?`) have no hover animation — they're intentionally de-emphasized. Adding motion would increase visual weight.
- **Skeleton loaders** pulse with a shimmer, not a spinner. Spinners imply unknown wait time; shimmer implies content is imminent.

---

## Information Architecture

The original app had a single scrolling page with no hierarchy. I reorganized into three tabs that map to three distinct mental models:

| Tab | Mental model | Primary action |
|---|---|---|
| Discover | "What's new / trending?" | Browse, save, report |
| Nearby | "What's close to me right now?" | Filter by location + open status |
| Profile | "My history and preferences" | Edit settings, view reservations |

The Admin tab was removed for the consumer-facing view. Surfacing ingestion controls, venue deduplication, and pipeline stats to end users adds cognitive load and signals "unfinished." Those tools belong in a separate operator interface.

**Reduced decision points per card:** The original card had a single "View deal →" link that navigated away. I replaced it with a modal so the user never loses their place in the feed. The four-button row (View deal, Save, Wrong?, Expired?) is ordered by expected tap frequency — the most-used action is leftmost and largest.

---

## Accessibility & Responsiveness

**What I did:**
- All color text combinations use `--ink` on `--glass` or `--bg` — both pass WCAG AA at the font sizes used.
- Interactive elements have visible focus states inherited from Streamlit's base styles.
- `white-space: nowrap` on small buttons prevents partial-word line breaks that break scannability.
- `alt` text on modal hero images.
- Section headers use semantic `h2` inside the HTML fragments.
- Responsive breakpoint at 900px collapses the stat box row from 4 columns to 2.

**What I'd improve:**
- The CSS `nth-child` selectors for report buttons are positional, not semantic. A proper system would use `data-*` attributes or ARIA roles to target them, making the selectors resilient to layout changes.
- Glassmorphism (`backdrop-filter: blur`) fails for users with `prefers-reduced-transparency`. I'd add a `@media (prefers-reduced-transparency)` fallback that replaces glass with a solid equivalent.
- Keyboard navigation through reservation slot buttons hasn't been explicitly tested.
- Color is used to convey state in several places (green = saved, red = expired). Each needs a non-color backup (icon or label) for colorblind users.

---

## Tradeoffs & Decisions

**Cut: real-time DB calls in the Profile tab.** Profile edit, reservation history, and photo upload are mock-only. Building the full CRUD loop would take days and add zero design signal. The UI demonstrates the interaction model; the backend work is straightforward when needed.

**Cut: infinite scroll.** Pagination with a load-more button is simpler to reason about and easier to instrument (I know exactly which page a user is on). Infinite scroll optimizes for time-on-site, which isn't this app's goal.

**Kept: Streamlit.** A React rebuild would give me more control but would also take 5× longer and obscure the AI/backend story. The constraint of Streamlit forced creative CSS problem-solving (e.g., `transform: scale()` to bypass browser minimum font size, `nth-child` selectors to target coarse column primitives) — which is a better design engineering story than "I used Tailwind."

**Risk: CSS injection fragility.** The entire design system is injected via `st.html('<style>...')`. If Streamlit changes its DOM structure (e.g., column `data-testid` names), selectors break silently. The mitigation is to keep selectors as high-level as possible and document the dependency clearly.

**Risk: Unsplash CDN in production.** Modal hero images are pulled from Unsplash at runtime. In a real product, I'd either cache these at build time or use a proper image CDN with fallbacks.

---

## Before / After Highlights

- **Hero section:** Was absent — the page started with a raw `st.title()`. Now a full-bleed hero with animated kicker, headline, and supporting copy sets the product context immediately.
- **Deal cards:** Were unstyled `st.markdown()` strings. Now glassmorphic tiles with entrance animations, category badges, price deltas, and rank reasons — all composable via a single `card_html()` function.
- **"View deal" CTA:** Was a plain `<a href>` that opened a new tab and lost the user's feed position. Now a modal (`@st.dialog`) with a photo hero, reservation slots, and distance info — the user never navigates away.
- **Report buttons (Wrong? / Expired?):** Were the same visual weight as the Save button. Redesigned to be intentionally small and low-contrast — they exist for data quality, not for users to discover.
- **Empty states:** Were Python `st.warning()` banners. Now illustrated with icon + headline + subtext, matching the page's visual language. Mock data fills nearby results so users see what the product does on first load.
- **Navigation:** Was a 4-tab bar including "Admin." Replaced with a 3-tab structure (Discover / Nearby / Profile) that maps cleanly to user mental models.

---

## What I'd Do Next

### Product iterations
- **Saved deals tab:** Users can save deals but have nowhere to view them. A fourth tab or modal drawer for saved items closes the loop and creates return visits.
- **Push / notification opt-in:** On deal save, offer to notify the user 1 hour before the deal expires. High-intent moment; low friction ask.
- **Deal ratings post-reservation:** After a reservation confirms, surface a one-tap rating card (1–5 stars) 24 hours later. This feeds quality scores back into the ranking model.

### Experiments (with success metrics)
1. **Hero CTA button on Discover:** Add a "Find deals near me" primary CTA in the hero. Hypothesis: users who click it (granting location) have 2× higher session depth. Metric: click-through rate + deals viewed per session.
2. **Card photo thumbnails:** Test adding a small category photo thumbnail to each deal card (not just in the modal). Hypothesis: images increase perceived relevance and tap rate. Metric: "View deal" modal open rate per card impression.
3. **"Open now" default ON:** Default the nearby search to filter open venues. Hypothesis: reducing irrelevant results increases conversion from search to "View deal" click. Metric: funnel completion rate (search → modal open).

---

## Implementation Notes

The design system is implemented entirely in CSS custom properties injected via a single `st.html('<style>...</style>')` block at app startup. There is no build step, no preprocessor, no framework — just vanilla CSS variables and one inject point.

**Token architecture:**
- Spacing and radii are on a named ladder (`--r-sm/md/lg/xl/full`) so you can reason about intent, not pixels.
- Shadow tokens (`--shadow-sm/md/lg/btn`) are pre-composed. Changing the brand's shadow depth is a one-line edit.
- Easing tokens separate motion intent: `--spring` is for transforms only; `--ease-out` is for color/opacity. This prevents the "bouncy background-color" bug.
- Duration tokens (`--dur-fast/.15s`, `--dur-base/.28s`, `--dur-slow/.42s`) keep motion consistent across components.

**Reusable Python functions:**
- `card_html(deal, idx)` — pure function, deal dict in, HTML string out. Stateless and testable.
- `deal_modal(deal)` — `@st.dialog`-decorated function. Called by passing the deal dict; manages its own session state for slot selection.
- `_hero_img(deal_id, cat)` — deterministic Unsplash URL from deal ID + category. Same deal always gets the same image.
- `_mock_slots(deal_id)` / `_mock_dist(deal_id)` — seeded by deal ID so slots and distance are stable across reruns.

**Theming:** Swapping the entire color scheme requires editing one `:root {}` block (~20 lines). The rest of the UI adapts automatically.

---

## Design QA Checklist

- [ ] All heading levels follow a logical semantic order (h1 → h2, no skips)
- [ ] No text uses a color with less than 4.5:1 contrast against its background
- [ ] All interactive elements are reachable and operable via keyboard
- [ ] Buttons never have text that wraps mid-word at any viewport width ≥ 360px
- [ ] Entrance animations complete within 500ms total; no animation loops indefinitely
- [ ] Empty states exist for every list view (deals, nearby results, reservations)
- [ ] Modal closes cleanly with no orphaned state in `st.session_state`
- [ ] Color is never the only indicator of state (icons or labels back up red/green usage)
- [ ] All card actions (Save, Wrong?, Expired?) post a structured event — no silent failures
- [ ] New features are tested against the existing CSS token set before introducing new hardcoded values

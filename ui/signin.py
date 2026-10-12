"""The only unauthenticated page: the coordinator sign-in card.

Rendered by Flask (not Dash) so an expired session always lands somewhere that
explains itself. Every asset it references is served from this same origin.
"""

from __future__ import annotations

from html import escape

PRODUCT_NAME = "Beekeeping Swarm Call Dispatcher"

FEATURES = [
    (
        "◉",
        "Log every swarm call",
        "Caller, site, cluster size and urgency land in a triage table the moment the line goes quiet.",
    ),
    (
        "◆",
        "Rank collectors by distance",
        "Available beekeepers whose coverage radius reaches the site, nearest first — no routing service needed.",
    ),
    (
        "⚑",
        "Keep one dispatch per report",
        "Confirm, decline, cancel or reassign without ever double-booking a collector.",
    ),
    (
        "◈",
        "Follow the swarm through",
        "Collection, rehoming, lost and not found stay distinct right through to the season funnel.",
    ),
]

DEMO_EMAIL = "cenius@cenius.ai"
DEMO_PASSWORD = "cenius"


def render_signin(
    csrf_token: str,
    next_target: str = "/app",
    error: str | None = None,
    notice: str | None = None,
) -> str:
    features = "\n".join(
        f'<li><span class="seam-icon" aria-hidden="true">{glyph}</span>'
        f"<strong>{escape(title)}</strong><div class=\"muted\">{escape(body)}</div></li>"
        for glyph, title, body in FEATURES
    )
    error_block = (
        f'<div class="error-banner" role="alert" style="display:flex">{escape(error)}</div>'
        if error
        else ""
    )
    notice_block = (
        f'<div class="notice notice--info" role="status">{escape(notice)}</div>' if notice else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sign in · {PRODUCT_NAME}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/theme.css">
</head>
<body>
<main class="signin-page">
  <div class="signin-shell">
    <section class="signin-pitch" aria-labelledby="pitch-title">
      <div class="row">
        <span class="brand-mark" aria-hidden="true">SC</span>
        <div class="brand-copy">
          <div class="brand-title">{PRODUCT_NAME}</div>
          <div class="brand-sub">Avon Valley swarm hotline</div>
        </div>
      </div>
      <h1 id="pitch-title" class="mt-4">Every swarm call, one board.</h1>
      <p class="muted">
        This is the coordinator's console for a volunteer honeybee swarm-collection service:
        take the call, log the report against a named site, dispatch the nearest available
        beekeeper, and follow the swarm through to rehoming — all offline, on one screen at a time.
      </p>
      <ul>
        {features}
      </ul>
    </section>

    <section class="signin-card" aria-labelledby="signin-title">
      <h2 id="signin-title">Coordinator sign-in</h2>
      <p class="muted tiny">Sessions are held server-side. Every page and every dashboard callback is checked.</p>
      {notice_block}
      {error_block}
      <div class="demo-hint">
        <div><strong>Demo: {DEMO_EMAIL} / {DEMO_PASSWORD}</strong></div>
        <div class="tiny">Seeded coordinator account — the sign-in form is prefilled with it.</div>
      </div>

      <form method="post" action="/signin" novalidate data-enter-form="signin">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input type="hidden" name="next" value="{escape(next_target)}">
        <div class="field">
          <label for="identity">Email or username</label>
          <input class="input" id="identity" name="identity" type="text" value="{DEMO_EMAIL}"
                 autocomplete="username" autocapitalize="none" spellcheck="false" required
                 inputmode="email">
        </div>
        <div class="field mt-3">
          <label for="password">Password</label>
          <div class="pw-row">
            <input class="input" id="password" name="password" type="password" value="{DEMO_PASSWORD}"
                   autocomplete="current-password" required data-pw-field="password">
            <button class="pw-toggle" type="button" data-pw-toggle="password"
                    aria-pressed="false" aria-label="Show password">Show</button>
          </div>
        </div>
        <div class="field mt-4">
          <button class="btn btn-primary btn-block" type="submit" data-enter-submit="signin-submit"
                  id="signin-submit">Sign in</button>
        </div>
      </form>

      <form method="post" action="/signin">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input type="hidden" name="next" value="{escape(next_target)}">
        <input type="hidden" name="identity" value="{DEMO_EMAIL}">
        <input type="hidden" name="password" value="{DEMO_PASSWORD}">
        <button class="btn btn-ghost btn-block" type="submit">One-click demo sign-in</button>
      </form>

      <p class="signin-foot">
        Prefer an email or username? Either works. Password resets and new accounts are arranged
        out of band by the duty organiser — this hotline console has a single seeded coordinator.
      </p>
    </section>
  </div>
</main>
<script src="/static/app-behaviour.js" defer></script>
</body>
</html>
"""

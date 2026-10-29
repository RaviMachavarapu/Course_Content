# Login protection: better UX without weaker security — design

Date: 2026-10-29 · Status: owner-approved (all four improvements + moderate sign-up/reset limits) · Branch: feature/pdf-sources

## Problem
Today (backend/app/auth/login.py): 10 failed logins per 5 min per email OR per IP → hard 5-minute block ("Too many attempts").
Anyone who knows an email (e.g. an admin's) can keep that account locked out; people behind one shared address
(school/office NAT) share one 10-failure bucket.

## Behaviour (applies to student and admin scopes, each namespaced as today)

### 1. Trusted-device cookie
- On every successful login, set `sdp_device_<scope>`: HttpOnly, Secure when app_env != dev, SameSite=Lax, path `/`,
  max-age 180 days. Value = HMAC-signed token over (user id, scope, issued-at, random nonce, credential stamp).
- Credential stamp: a value that changes when the user's password changes (e.g. a short hash of the password hash),
  so a password reset/change invalidates every device cookie for that user.
- Signing secret: new setting `DEVICE_COOKIE_SECRET`; a dev default is allowed only when APP_ENV=dev (extend the
  existing prod-defaults guard in config.py).
- A login attempt that presents a valid device cookie for the SAME account (email → user id matches, scope matches,
  stamp matches) is not subject to the per-email delay (§2). It has its own per-device counter: 10 failures / 15 min
  → then the same growing delays apply to that device only. (Stops brute force with a stolen cookie.)
- The per-IP limit (§3) still applies to device-cookie attempts.

### 2. Growing delays instead of a hard block (per email, for attempts without a valid device cookie)
- Failures counted per email in a sliding 15-minute window. First 5 failures: no delay.
- From the 6th failure on, the next attempt for that email is allowed only after a wait of 2, 4, 8, 16, 32, 60, 60… s
  (doubling, capped at 60 s), measured from the last failure.
- An attempt made before the wait ends is rejected without checking the password: 429, error code `rate_limited`,
  JSON field `retry_after` (integer seconds, ≥1) and `Retry-After` header. It does not count as a failure.
- A successful login clears the email's failure count (and the device's).

### 3. Per-IP limit tuned for shared networks
- Failures only (successes never count), 100 failures per 15 minutes per client IP → 429 `rate_limited` with
  `retry_after` = seconds until the oldest failure in the window expires.
- Settings stay configurable (LOGIN_RATE_LIMIT and new settings for the delay schedule); dev compose may override.

### 4. Countdown and email alert
- Login pages (student + admin): on 429 show "Too many attempts — try again in m:ss" with a live countdown; the
  submit button is disabled until it reaches 0; a "Forgot password?" link is shown next to the message.
- Email alert: when an account reaches 5 consecutive failed attempts (no valid device cookie), send the owner one email
  "Several failed sign-ins to your account" (time in UTC, no IP needed; link to password reset). At most one alert per
  account per hour. Sent off the request path like other mail (batch B pattern). Never reveals anything in the HTTP
  response (unknown emails behave identically: no email, same responses, same timing as today).

### 5. Sign-up and password-reset limits
- Register: 100 per hour per IP (was 30). Reset request: 30 per hour per IP (was 10).
- New: reset emails capped at 3 per hour per email address; requests beyond the cap return the same constant response
  but send nothing.

## Must not regress
- Account enumeration: responses and timing for unknown vs known emails stay indistinguishable (wrong password and
  unknown email both count toward the per-email delay for that address).
- CSRF/session behaviour from batch B; login stays CSRF-exempt.
- The two areas' cookies stay independent.

## Testing
Backend: device cookie set on success; valid cookie bypasses per-email delay; forged/expired/other-user/other-scope/
stale-stamp cookie ignored; password reset invalidates it; per-device counter; delay schedule (5 free, 2/4/8…60 s) and
early attempt → 429 with retry_after and no password check; success clears; IP 100/15 min failures only; alert once per
hour at 5 failures, none for unknown emails; reset 3/hour per email; register/reset per-IP numbers. Use a fake clock.
Frontend: countdown renders from retry_after, disables submit, re-enables at 0, Forgot-password link, both areas.

## Amendment 2026-10-29 (owner decisions, E2E review round)
Supersedes the parts of §1, §2 and §4 it contradicts.

1. **"Remember this device"** — both login pages show a checkbox "Remember this device", ticked by default, with an
   accessible label. The login request carries `remember` (boolean; omitted = false, so API clients get no device
   cookie unless they ask). Only `remember: true` sets `sdp_device_<scope>` (§1). The session records whether it was
   remembered; logging out of a session that was *not* remembered also deletes `sdp_device_<scope>` when that cookie
   belongs to the account logging out (or is unreadable/expired), so a shared PC keeps nothing of that account
   behind. A device cookie of *another* account on that browser stays (controller ruling 2026-10-29). Logging out of
   a remembered session keeps the device cookie.
2. **Alert counts device-cookie guesses** — wrong passwords carrying a valid device cookie still use the per-device
   counter for delays (§1), but they now also count toward the 5-consecutive-failures alert mail (§4). The "no valid
   device cookie" condition in §4 is dropped. At most one mail per account per hour, claimed atomically, so
   concurrent failures can't send two.
3. **Password reset trusts the redeeming browser** — completing a reset (`…/password-reset/confirm`, 204) sets a fresh
   `sdp_device_<scope>` stamped with the new password for the browser that redeemed the link. Every other device
   cookie stays invalid (stamp changed) and every session stays revoked. The reset does not sign the user in.
4. **A trusted-device success doesn't clear the email's count** — it clears the device's counter and the alert streak
   only; the per-email failures (an attacker's) age out of their window instead of being reset each time the owner
   signs in. A success without a device cookie still clears the email's count (§2).
5. **Sign-in ends the browser's previous session** — the session token the browser already held for that area is
   destroyed server-side before the new session is created.

/** Client-side mirror of the server rules (backend `app/auth/passwords.py`,
 * `app/schemas/auth.py`). Keep in sync. */

export const MIN_PASSWORD_LENGTH = 10;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function emailError(value: string): string | null {
  if (!value.trim()) return "Email is required";
  if (!EMAIL_RE.test(value.trim())) return "Enter a valid email address";
  return null;
}

export function passwordError(value: string): string | null {
  if (value.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters`;
  }
  if (!/[a-zA-Z]/.test(value)) return "Password must contain a letter";
  if (!/[^a-zA-Z]/.test(value)) return "Password must contain a number or symbol";
  return null;
}

export function displayNameError(value: string): string | null {
  if (!value.trim()) return "Display name is required";
  if (value.trim().length > 120) return "Display name is too long";
  return null;
}

export function confirmError(password: string, confirm: string): string | null {
  if (!confirm) return "Please re-enter your password";
  if (password !== confirm) return "Passwords do not match";
  return null;
}

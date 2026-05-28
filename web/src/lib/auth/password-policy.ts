/**
 * Shared password policy — mirrors api/src/life_dashboard/auth/password_policy.py.
 *
 * Rules:
 *   - At least 8 characters
 *   - At most 50 characters (generous; 1Password-length passwords welcome)
 *   - At least one digit
 *   - At least one special character (anything that isn't A-Z, a-z, or 0-9)
 */

export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 50;

export function validatePassword(password: string): string | null {
  if (password.length < PASSWORD_MIN)
    return `Password must be at least ${PASSWORD_MIN} characters.`;
  if (password.length > PASSWORD_MAX)
    return `Password must be ${PASSWORD_MAX} characters or fewer.`;
  if (!/\d/.test(password))
    return "Password must contain at least one number.";
  if (!/[^A-Za-z0-9]/.test(password))
    return "Password must contain at least one special character.";
  return null;
}

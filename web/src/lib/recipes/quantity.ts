/**
 * Rendering an ingredient quantity for humans.
 *
 * Quantities are `Numeric` columns, which serialise as full-precision decimal
 * strings — "2.0000000000 cloves garlic" is what a naive render produces (the
 * same class of bug coach-006 fixed on goal progress). Every screen that shows
 * a quantity goes through here so the fix is in one place: the recipe page, and
 * the grocery list that meal-001's planner writes to.
 */

/** Common cooking decimals back to unicode fractions: 0.333… → "⅓", 1.5 → "1½". */
const FRAC_MAP: [number, string][] = [
  [1 / 8, "⅛"], [1 / 4, "¼"], [1 / 3, "⅓"], [3 / 8, "⅜"],
  [1 / 2, "½"], [5 / 8, "⅝"], [2 / 3, "⅔"], [3 / 4, "¾"], [7 / 8, "⅞"],
];
const EPS = 0.02;

/** A display string, or null when there is no usable quantity to show. */
export function formatQuantity(qty: number | string | null | undefined): string | null {
  if (qty == null) return null;
  const n = Number(qty);
  if (isNaN(n) || n <= 0) return null;
  const whole = Math.floor(n);
  const frac = n - whole;
  if (frac < EPS) return String(whole);
  const fracChar = FRAC_MAP.find(([v]) => Math.abs(frac - v) < EPS)?.[1] ?? null;
  if (!fracChar) return n.toFixed(2).replace(/\.?0+$/, "");
  return whole > 0 ? `${whole}${fracChar}` : fracChar;
}

/** "7 cloves garlic"-style label from the three parts, skipping missing ones. */
export function formatQuantityUnit(
  qty: number | string | null | undefined,
  unit: string | null | undefined,
): string | null {
  const parts = [formatQuantity(qty), unit?.trim() || null].filter(Boolean);
  return parts.length ? parts.join(" ") : null;
}

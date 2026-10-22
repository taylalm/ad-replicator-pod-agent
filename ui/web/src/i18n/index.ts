import { en, type Strings } from "./en";

const locales: Record<string, Strings> = { en };

let current = "en";

/** Switch the active locale (add `vi` to `locales` to enable Vietnamese). */
export function setLocale(code: string) {
  if (locales[code]) current = code;
}

/** `t()` returns the typed strings object for the active locale: `t().history.title`. */
export function t(): Strings {
  return locales[current] ?? en;
}

// Path redaction: names that look sensitive and anything that looks like a key never reach a record.

const SENSITIVE_NAME: RegExp[] = [
  /^\.env/i,
  /\.pem$/i,
  /\.key$/i,
  /^id_/i,
  /secret/i,
  /token/i,
  /credential/i,
];

const KEY_PATTERNS: RegExp[] = [
  /AKIA[0-9A-Z]{12,}/g,
  /gh[pousr]_[A-Za-z0-9]{20,}/g,
  /github_pat_[A-Za-z0-9_]{20,}/g,
  /sk-[A-Za-z0-9_-]{16,}/g,
  /xox[a-z]-[A-Za-z0-9-]{8,}/g,
  /[0-9a-fA-F]{32,}/g,
  /[A-Za-z0-9+/=_-]{40,}/g,
];

export function isSensitiveName(component: string): boolean {
  return SENSITIVE_NAME.some((re) => re.test(component));
}

export function redactPath(p: string): string {
  const parts = p.split("/").map((part) => {
    if (part === "" || part === "." || part === "..") return part;
    if (isSensitiveName(part)) return "[redacted-name]";
    let s = part;
    for (const re of KEY_PATTERNS) s = s.replace(re, "[redacted]");
    return s;
  });
  return parts.join("/");
}

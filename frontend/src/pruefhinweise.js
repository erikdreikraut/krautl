// Normalize display only: do not change the server's send/approval decision.
export function pruefhinweise(value, depth = 0) {
  const fallback = "Pruefhinweis nicht lesbar. Bitte die Antwort erneut pruefen.";
  if (depth > 8) return [fallback];
  if (value == null) return [];
  if (Array.isArray(value)) return [...new Set(value.flatMap(v => pruefhinweise(v, depth + 1)))];
  if (typeof value === "object") {
    for (const key of ["beschreibung", "probleme", "problem", "message", "detail"]) {
      if (key in value) return pruefhinweise(value[key], depth + 1);
    }
    return [fallback];
  }
  const text = String(value).trim().replace(/^```(?:json)?\s*|\s*```$/g, "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (parsed !== value) return pruefhinweise(parsed, depth + 1);
  } catch { /* Some older responses contain invalid JSON with unescaped quotes. */ }
  if (/^[\[{]/.test(text) && /"(?:typ|beschreibung|probleme)"\s*:/.test(text)) {
    const descriptions = [...text.matchAll(/"beschreibung"\s*:\s*"([\s\S]*?)"\s*(?=[,}])/g)]
      .map(match => match[1].replace(/\\"/g, '"').replace(/\\n/g, " ").trim()).filter(Boolean);
    return descriptions.length ? descriptions : [fallback];
  }
  return text.split(/\r?\n/).map(line => line.replace(/^\s*[-•]\s*/, "").trim()).filter(Boolean);
}

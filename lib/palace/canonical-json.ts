/** Stable nested JSON for physical-model provenance. Twelve significant digits
 * remove runtime trigonometry noise; authored input hashes use seventeen digits
 * to retain every distinct IEEE-754 input. Byte hashes are kept separately.
 * Object keys are sorted; array order and all finite numeric values are retained.
 */
export function canonicalJson(value: unknown, digits = 12): string {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Non-finite provenance value")
    return value === 0 ? "0" : value.toExponential(digits - 1)
  }
  if (Array.isArray(value))
    return `[${value.map((item) => canonicalJson(item ?? null, digits)).join(",")}]`
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      .filter(([, item]) => item !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(
        ([key, item]) =>
          `${JSON.stringify(key)}:${canonicalJson(
            key === "physicalModelSignature" && typeof item === "string"
              ? JSON.parse(item)
              : item,
            digits,
          )}`,
      )
      .join(",")}}`
  return JSON.stringify(value) ?? "null"
}

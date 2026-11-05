export function shiftedCheckout(start, nights) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) return '';
  const parsed = new Date(`${start}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== start) return '';
  parsed.setUTCDate(parsed.getUTCDate() + Number(nights));
  return parsed.toISOString().slice(0, 10);
}

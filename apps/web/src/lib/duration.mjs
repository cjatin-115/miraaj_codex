export function durationChoices(estimate) {
  const values = [...new Set([estimate.recommended_duration, 45, 60, 70])].sort((a, b) => a - b);
  return values.map((seconds) => ({ seconds, recommended: seconds === estimate.recommended_duration }));
}

export function durationWarning(estimate, target) {
  if (!estimate || !Number.isFinite(Number(target))) return null;
  const max = Number(estimate.estimated_max_duration);
  if (target > max * 1.15) {
    return `This script naturally supports about ${estimate.estimated_min_duration}–${max} seconds. Reaching ${target} seconds would require adding content.`;
  }
  const min = Number(estimate.estimated_min_duration);
  if (target < min * 0.75) return `This script naturally supports about ${min}–${max} seconds; ${target} seconds may require cutting content.`;
  return null;
}

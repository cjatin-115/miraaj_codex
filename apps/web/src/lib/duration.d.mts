export interface DurationEstimate {
  estimated_min_duration: number;
  estimated_max_duration: number;
  recommended_duration: number;
  confidence: number;
}
export function durationChoices(estimate: DurationEstimate): Array<{ seconds: number; recommended: boolean }>;
export function durationWarning(estimate: DurationEstimate, target: number): string | null;

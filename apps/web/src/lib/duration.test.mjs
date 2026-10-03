import assert from "node:assert/strict";
import test from "node:test";
import { durationChoices, durationWarning } from "./duration.mjs";

const estimate = { estimated_min_duration: 54, estimated_max_duration: 63, recommended_duration: 59, confidence: 0.82 };

test("duration choices include recommendation and requested presets without duplicates", () => {
  assert.deepEqual(durationChoices(estimate), [
    { seconds: 45, recommended: false },
    { seconds: 59, recommended: true },
    { seconds: 60, recommended: false },
    { seconds: 70, recommended: false },
  ]);
});

test("duration warning explains when target requires adding script content", () => {
  assert.match(durationWarning({ ...estimate, estimated_min_duration: 35, estimated_max_duration: 40 }, 70), /would require adding content/);
  assert.equal(durationWarning(estimate, 60), null);
});

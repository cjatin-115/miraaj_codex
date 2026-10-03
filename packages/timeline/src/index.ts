import type { Timeline } from "@miraaj/shared";

export interface RenderProfile {
  id: "vertical_1080" | "vertical_4k";
  width: 1080 | 2160;
  height: 1920 | 3840;
  fps: 30;
  codec: "h264";
}

export const renderProfiles: Record<RenderProfile["id"], RenderProfile> = {
  vertical_1080: { id: "vertical_1080", width: 1080, height: 1920, fps: 30, codec: "h264" },
  vertical_4k: { id: "vertical_4k", width: 2160, height: 3840, fps: 30, codec: "h264" },
};

export function createTimeline(duration: number, styleId = "modern_creator_v1"): Timeline {
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new RangeError("Timeline duration must be a positive number of seconds.");
  }
  return {
    version: 1,
    width: renderProfiles.vertical_1080.width,
    height: renderProfiles.vertical_1080.height,
    fps: renderProfiles.vertical_1080.fps,
    duration,
    style_id: styleId,
    scenes: [],
  };
}

export type Scene = {
  id: string; type: string; start: number; duration: number; source_start: number; source_end: number;
  layer: "base" | "overlay"; channel: string; crop: {mode?: string; scale?: number; focus_x?: number; focus_y?: number};
  text?: string; emphasis?: string[]; transition_in?: string; transition_out?: string;
  asset_request?: {type: string; data: Record<string, unknown>}; layout?: Record<string, unknown>;
};
export type Timeline = {version: 1; width: number; height: number; fps: number; duration: number; style_id: string; scenes: Scene[]};
export type WordTimestamp = {word: string; start: number; end: number; confidence?: number | null};
export type RenderProps = {timeline: Timeline; sourceUrl: string; sourceHasAudio?: boolean; wordTimestamps: WordTimestamp[]; assetUrls?: Record<string,string>; volume: number; style: Record<string, any>; outputWidth?: number; outputHeight?: number};

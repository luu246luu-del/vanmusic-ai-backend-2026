// Kiểu dữ liệu cho VanMusic Prediction API (khớp api-contract.json).
export interface VanMusicPredictionRequest {
  channel_id: string;
  title: string;
  description: string;
  duration_seconds: number;
  tags: string[];
  publish_datetime: string;
  category_id: string;
  is_hd: boolean;
  has_caption: boolean;
  user_id: string | null;
  client_request_id: string | null;
}

export interface ChannelSummary {
  channel_id: string;
  channel_title: string;
  subscriber_count: number | null;
  channel_age_days: number;
  channel_video_count: number;
  channel_total_views: number;
  avg_previous_views: number;
  median_previous_views: number;
  previous_video_count_used: number;
}

export interface VideoInputSummary {
  title: string;
  duration_seconds: number;
  tag_count: number;
  publish_datetime: string;
  publish_hour: number;
  publish_day_of_week: number;
  category_id: string;
}

export interface ModelSummary {
  name: string;
  version: string;
  trained_at: string;
  target: "views_after_3_days";
}

export interface PredictionData {
  predicted_views_after_3_days: number;
  lower_estimate: number | null;
  upper_estimate: number | null;
  estimate_method: "test_residual_quantiles" | null;
  channel: ChannelSummary;
  video_input: VideoInputSummary;
  model: ModelSummary;
  warnings: string[];
}

export interface ApiError {
  code: string;
  message: string;
  details: unknown | null;
}

export type VanMusicPredictionResponse =
  | { success: true; data: PredictionData; error: null; request_id: string }
  | { success: false; data: null; error: ApiError; request_id: string };

export interface VanMusicPredictorConfig {
  apiBaseUrl: string;
  integrationKey: string;
  timeoutMs: number;
}

export async function predictYouTubeViews(
  req: VanMusicPredictionRequest,
  cfg: VanMusicPredictorConfig
): Promise<VanMusicPredictionResponse> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), cfg.timeoutMs);
  try {
    const res = await fetch(`${cfg.apiBaseUrl.replace(/\/+$/, "")}/api/v1/vanmusic/predict`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(cfg.integrationKey ? { "X-VanMusic-Key": cfg.integrationKey } : {}),
      },
      body: JSON.stringify(req),
      signal: ctrl.signal,
    });
    return (await res.json()) as VanMusicPredictionResponse;
  } finally {
    clearTimeout(timer);
  }
}

/* VanMusicPredictionClient - gọi Prediction API. Không giữ YouTube API Key, không giả lập kết quả. */
(function (global) {
    "use strict";

    var DEFAULTS = { apiBaseUrl: "http://127.0.0.1:8000", integrationKey: "", timeoutMs: 30000 };

    class PredictionApiError extends Error {
        constructor(code, message, details, status) {
            super(message);
            this.name = "PredictionApiError";
            this.code = code;
            this.details = details || null;
            this.status = status || 0;
        }
    }

    class VanMusicPredictionClient {
        constructor(config) {
            this.config = Object.assign({}, DEFAULTS, global.VANMUSIC_PREDICTOR_CONFIG || {}, config || {});
        }

        _url(path) {
            return String(this.config.apiBaseUrl || "").replace(/\/+$/, "") + path;
        }

        async predictYouTubeViews(videoInput) {
            var controller = new AbortController();
            var timer = setTimeout(function () { controller.abort(); }, this.config.timeoutMs);
            var headers = { "Content-Type": "application/json", "Accept": "application/json" };
            if (this.config.integrationKey) headers["X-VanMusic-Key"] = this.config.integrationKey;

            var response;
            try {
                response = await fetch(this._url("/api/v1/vanmusic/predict"), {
                    method: "POST", headers: headers, body: JSON.stringify(videoInput), signal: controller.signal
                });
            } catch (err) {
                if (err && err.name === "AbortError") {
                    throw new PredictionApiError("TIMEOUT", "Máy chủ phản hồi quá lâu. Vui lòng thử lại.", null, 0);
                }
                throw new PredictionApiError("NETWORK_ERROR", "Không kết nối được tới máy chủ dự báo. Kiểm tra mạng hoặc thử lại sau.", null, 0);
            } finally {
                clearTimeout(timer);
            }

            var payload = null;
            try { payload = await response.json(); } catch (e) { payload = null; }

            if (!payload || typeof payload !== "object" || typeof payload.success !== "boolean") {
                throw new PredictionApiError("BAD_RESPONSE", "Máy chủ trả về dữ liệu không hợp lệ (HTTP " + response.status + ").", null, response.status);
            }
            if (!response.ok || payload.success === false) {
                var e = payload.error || {};
                throw new PredictionApiError(e.code || "HTTP_" + response.status,
                    e.message || "Yêu cầu dự báo thất bại.", e.details, response.status);
            }
            return payload;
        }
    }

    global.PredictionApiError = PredictionApiError;
    global.VanMusicPredictionClient = VanMusicPredictionClient;
})(window);

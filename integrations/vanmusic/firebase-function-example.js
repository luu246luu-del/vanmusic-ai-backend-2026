/**
 * Firebase Cloud Function proxy: VanMusic frontend -> Cloud Function -> Prediction API.
 * Khóa tích hợp nằm ở Firebase Secret, KHÔNG nằm trong JavaScript của website.
 *
 * Cài đặt (trong thư mục functions/ của dự án Firebase):
 *   npm install firebase-functions firebase-admin
 *   firebase functions:secrets:set VANMUSIC_INTEGRATION_KEY
 *   firebase functions:config hoặc biến môi trường: PREDICTION_API_URL=https://backend-cua-ban.example.com
 *   firebase deploy --only functions
 *
 * Trong vanmusic-config.js đặt: apiBaseUrl: "https://<region>-<project>.cloudfunctions.net"
 * và đổi đường dẫn gọi cho khớp (function này phục vụ POST /vanmusicPredict).
 * Đơn giản nhất: dùng rewrite trong firebase.json để /api/v1/vanmusic/predict -> function vanmusicPredict.
 */
const { onRequest } = require("firebase-functions/v2/https");
const { defineSecret, defineString } = require("firebase-functions/params");

const INTEGRATION_KEY = defineSecret("VANMUSIC_INTEGRATION_KEY");
const PREDICTION_API_URL = defineString("PREDICTION_API_URL");
const ALLOWED_ORIGINS = ["https://vanmusic.web.app", "http://localhost:5000", "http://127.0.0.1:5500"];

exports.vanmusicPredict = onRequest(
    { secrets: [INTEGRATION_KEY], cors: ALLOWED_ORIGINS, timeoutSeconds: 60, maxInstances: 10 },
    async (req, res) => {
        if (req.method !== "POST") {
            return res.status(405).json({ success: false, data: null, request_id: "",
                error: { code: "METHOD_NOT_ALLOWED", message: "Chỉ hỗ trợ POST.", details: null } });
        }
        try {
            const upstream = await fetch(`${PREDICTION_API_URL.value().replace(/\/+$/, "")}/api/v1/vanmusic/predict`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-VanMusic-Key": INTEGRATION_KEY.value() },
                body: JSON.stringify(req.body),
                signal: AbortSignal.timeout(45000),
            });
            const text = await upstream.text();
            res.status(upstream.status).type("application/json").send(text);
        } catch (err) {
            // Không log body/khóa; chỉ log loại lỗi.
            console.error("Proxy lỗi:", err && err.name);
            res.status(502).json({ success: false, data: null, request_id: "",
                error: { code: "UPSTREAM_ERROR", message: "Không kết nối được máy chủ dự báo.", details: null } });
        }
    }
);

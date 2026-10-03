// Cấu hình tính năng AI Dự Báo. Sao chép thành vanmusic-config.js rồi chỉnh.
// KHÔNG đặt YouTube API Key ở đây. Khi chạy production hãy trỏ apiBaseUrl tới Firebase Function proxy (HTTPS).
window.VANMUSIC_PREDICTOR_CONFIG = {
    apiBaseUrl: "http://127.0.0.1:8000",
    integrationKey: "",
    timeoutMs: 30000
};

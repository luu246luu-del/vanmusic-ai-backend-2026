/* VanMusic AI Dự Báo - điều khiển giao diện. Toàn bộ nằm trong window.VanMusicPredictor. */
(function (global) {
    "use strict";

    var STATE = { IDLE: "idle", VALIDATING: "validating", LOADING: "loading", SUCCESS: "success", ERROR: "error", MODEL_NOT_READY: "model-not-ready" };
    var CHANNEL_ID_RE = /^UC[\w-]{22}$/;
    var client = null;
    var initialized = false;
    var state = STATE.IDLE;

    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function formatViewCountVI(n) {
        if (n == null || isNaN(n)) return "—";
        return new Intl.NumberFormat("vi-VN").format(Math.round(Number(n)));
    }

    /** Trả về Channel ID (UC...) hoặc "@handle" đã chuẩn hóa; null nếu không hợp lệ. */
    function parseChannelInput(text) {
        var s = String(text || "").trim();
        if (!s) return null;
        if (CHANNEL_ID_RE.test(s)) return s;
        var m = s.match(/youtube\.com\/channel\/(UC[\w-]{22})/i);
        if (m) return m[1];
        m = s.match(/(?:youtube\.com\/)?(@[\w.\-]+)/i);
        if (m) return m[1];
        return null;
    }

    function convertDurationToSeconds(minutes, seconds) {
        var m = parseInt(minutes, 10), s = parseInt(seconds, 10);
        m = isNaN(m) ? 0 : m; s = isNaN(s) ? 0 : s;
        if (m < 0 || s < 0 || s > 59) return NaN;
        return m * 60 + s;
    }

    function parseTags(text) {
        return String(text || "").split(",").map(function (t) { return t.trim(); }).filter(Boolean).slice(0, 100);
    }

    /** "2026-10-02T20:00" (giờ địa phương của trình duyệt) -> ISO có múi giờ, ví dụ 2026-10-02T20:00:00+07:00 */
    function localDateTimeToIso(value) {
        var d = new Date(value);
        if (isNaN(d.getTime())) return null;
        var off = -d.getTimezoneOffset(), sign = off >= 0 ? "+" : "-", a = Math.abs(off);
        var p = function (x) { return String(x).padStart(2, "0"); };
        return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" +
            p(d.getMinutes()) + ":00" + sign + p(Math.floor(a / 60)) + ":" + p(a % 60);
    }

    function setState(next) {
        state = next;
        var loading = next === STATE.LOADING;
        $("vm-predict-form-card").hidden = loading;
        $("vm-predict-loading").hidden = !loading;
        $("vm-predict-result").hidden = next !== STATE.SUCCESS;
        $("vm-predict-error").hidden = !(next === STATE.ERROR || next === STATE.MODEL_NOT_READY);
        var btn = $("vm-predict-submit");
        if (btn) btn.disabled = loading;
    }

    function setFieldError(id, msg) {
        var el = $(id);
        if (el) el.textContent = msg || "";
    }

    /** Trả về { ok, errors, payload }. */
    function validateVanMusicPredictionForm() {
        var errors = {};
        var channel = parseChannelInput($("vm-predict-channel").value);
        if (!channel) errors.channel = "Nhập Channel ID (UC...), URL kênh hoặc @handle hợp lệ.";
        var title = $("vm-predict-title").value.trim();
        if (!title) errors.title = "Vui lòng nhập tiêu đề video.";
        var duration = convertDurationToSeconds($("vm-predict-minutes").value, $("vm-predict-seconds").value);
        if (isNaN(duration) || duration < 1) errors.duration = "Thời lượng phải lớn hơn 0 (giây từ 0 đến 59).";
        var iso = $("vm-predict-datetime").value ? localDateTimeToIso($("vm-predict-datetime").value) : null;
        if (!iso) errors.datetime = "Vui lòng chọn ngày giờ dự kiến đăng.";

        setFieldError("vm-predict-err-channel", errors.channel);
        setFieldError("vm-predict-err-title", errors.title);
        setFieldError("vm-predict-err-duration", errors.duration);
        setFieldError("vm-predict-err-datetime", errors.datetime);

        if (Object.keys(errors).length) return { ok: false, errors: errors, payload: null };
        return {
            ok: true, errors: {},
            payload: {
                channel_id: channel, title: title, description: $("vm-predict-description").value.trim(),
                duration_seconds: duration, tags: parseTags($("vm-predict-tags").value), publish_datetime: iso,
                category_id: $("vm-predict-category").value || "10",
                is_hd: $("vm-predict-hd").checked, has_caption: $("vm-predict-caption").checked,
                user_id: null, client_request_id: null
            }
        };
    }

    function detail(label, value) {
        return '<div class="vm-predict-detail"><dt>' + esc(label) + "</dt><dd>" + esc(value) + "</dd></div>";
    }

    function renderVanMusicPrediction(response) {
        var d = response && response.data;
        if (!d || typeof d.predicted_views_after_3_days !== "number") {
            return renderVanMusicPredictionError({ code: "BAD_RESPONSE", message: "Dữ liệu dự báo không hợp lệ." });
        }
        $("vm-predict-views").textContent = formatViewCountVI(d.predicted_views_after_3_days);
        var range = "";
        if (d.lower_estimate != null && d.upper_estimate != null) {
            range = "Khoảng tham khảo: " + formatViewCountVI(d.lower_estimate) + " – " + formatViewCountVI(d.upper_estimate) + " lượt xem";
        }
        $("vm-predict-range").textContent = range;

        var ch = d.channel || {}, md = d.model || {};
        $("vm-predict-details").innerHTML = [
            detail("Kênh", ch.channel_title || "—"),
            detail("Người đăng ký", ch.subscriber_count == null ? "Ẩn / không có" : formatViewCountVI(ch.subscriber_count)),
            detail("Tuổi đời kênh", formatViewCountVI(ch.channel_age_days) + " ngày"),
            detail("Lượt xem TB các video trước", formatViewCountVI(ch.avg_previous_views)),
            detail("Số video trước đã dùng", String(ch.previous_video_count_used == null ? "—" : ch.previous_video_count_used)),
            detail("Mô hình", md.name || "—"),
            detail("Phiên bản mô hình", md.version || "—")
        ].join("");

        var w = $("vm-predict-warnings");
        w.innerHTML = (d.warnings || []).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("");
        setState(STATE.SUCCESS);
    }

    function renderVanMusicPredictionError(err) {
        var code = err && err.code, msg = (err && err.message) || "Đã xảy ra lỗi. Vui lòng thử lại.";
        if (code === "MODEL_NOT_READY") {
            msg = "Hệ thống dự báo đang được chuẩn bị. Vui lòng thử lại sau.";
            $("vm-predict-error-message").textContent = msg;
            setState(STATE.MODEL_NOT_READY);
            return;
        }
        $("vm-predict-error-message").textContent = msg;
        setState(STATE.ERROR);
    }

    async function submitVanMusicPrediction() {
        if (state === STATE.LOADING) return; // chặn gửi lặp
        setState(STATE.VALIDATING);
        var v = validateVanMusicPredictionForm();
        if (!v.ok) { setState(STATE.IDLE); return; }
        setState(STATE.LOADING);
        try {
            if (!client) client = new global.VanMusicPredictionClient();
            var res = await client.predictYouTubeViews(v.payload);
            renderVanMusicPrediction(res);
        } catch (e) {
            renderVanMusicPredictionError({ code: e && e.code, message: e && e.message });
        }
    }

    /** Về trạng thái nhập liệu; KHÔNG xóa dữ liệu người dùng đã nhập. */
    function resetVanMusicPrediction() {
        $("vm-predict-form-card").hidden = false;
        setState(STATE.IDLE);
        $("vm-predict-form-card").hidden = false;
    }

    function setDefaultDatetime() {
        var el = $("vm-predict-datetime");
        if (!el || el.value) return;
        var d = new Date(Date.now() + 24 * 3600 * 1000);
        var p = function (x) { return String(x).padStart(2, "0"); };
        el.value = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":00";
    }

    function initializeVanMusicPredictor() {
        if (initialized || !$("tab-predictor")) return;
        initialized = true;
        client = new global.VanMusicPredictionClient();
        setDefaultDatetime();
        $("vm-predict-submit").addEventListener("click", submitVanMusicPrediction);
        $("vm-predict-retry").addEventListener("click", resetVanMusicPrediction);
        $("vm-predict-reset").addEventListener("click", resetVanMusicPrediction);
        setState(STATE.IDLE);
    }

    global.VanMusicPredictor = {
        initializeVanMusicPredictor: initializeVanMusicPredictor,
        validateVanMusicPredictionForm: validateVanMusicPredictionForm,
        submitVanMusicPrediction: submitVanMusicPrediction,
        renderVanMusicPrediction: renderVanMusicPrediction,
        renderVanMusicPredictionError: renderVanMusicPredictionError,
        resetVanMusicPrediction: resetVanMusicPrediction,
        formatViewCountVI: formatViewCountVI,
        parseChannelInput: parseChannelInput,
        convertDurationToSeconds: convertDurationToSeconds
    };
    // Chỉ một hàm toàn cục, để switchTab gọi.
    global.initializeVanMusicPredictor = initializeVanMusicPredictor;
})(window);

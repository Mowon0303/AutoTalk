#!/usr/bin/env python3
"""
chat_ocr.py — 聊天截图 → 结构化对话 (speaker-aware OCR)

不是纯文本提取，而是把聊天截图还原成结构化对话，重点解决"左右气泡发言人判断错误"：
OCR 保留 bounding box → 估计气泡 → 检测左右头像候选 → **只用同一水平带(y-range)附近的头像**
判定 speaker，头像失败再 fallback 到气泡中心位置。低置信度保留 confidence + reason，不硬判。

用法:
    python scripts/chat_ocr.py input_screenshots/ --out outputs/chat.json --markdown outputs/chat.md
    python scripts/chat_ocr.py one.png --out outputs/chat.json
    python scripts/chat_ocr.py imgs/ --backend easyocr --me-side right --markdown outputs/chat.md

需要先装一个 OCR 后端（任选其一），详见 references/ocr-backends.md：
    vision (macOS, 推荐) / easyocr / paddleocr / tesseract
"""
import argparse, json, os, re, sys, glob

try:
    import numpy as np
except Exception:
    np = None
try:
    from PIL import Image
except Exception:
    Image = None

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
BACKEND_ORDER = ["vision", "easyocr", "paddleocr", "tesseract"]
_CHOSEN = None          # resolved backend name
_PADDLE = None
_EASY = None


# ----------------------------------------------------------------------------- #
# OCR backends — each returns list of lines: {"text","box":(x0,y0,x1,y1),"conf"}
# ----------------------------------------------------------------------------- #
def _line(text, x0, y0, x1, y1, conf):
    return {"text": str(text), "box": (float(x0), float(y0), float(x1), float(y1)),
            "conf": float(conf)}


def ocr_vision(path, W, H):
    """macOS Vision framework via pyobjc. 中文好、无需下载模型。
    注意：在沙箱/受限环境（如某些 managed shell）Vision 请求可能建不出 CVPixelBuffer 而失败。
    这里检查 performRequests:error: 的返回值，失败就**抛错**，绝不把'请求失败'伪装成'0 行文字'。"""
    import Vision, Quartz
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(os.path.abspath(path)), None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None) if src else None
    if cg is None:
        raise RuntimeError("Vision: 无法解码图片（CGImage 为空）")
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(0)               # 0 = accurate（支持中文）；1 = fast（偏拉丁，会把中文识成乱码）
    req.setUsesLanguageCorrection_(True)
    try:
        req.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en"])
    except Exception:
        pass
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(
            "Vision 请求执行失败（此环境可能不支持，如沙箱建不出 CVPixelBuffer/420f）：%s" % err)
    lines = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        text = cand[0].string()
        conf = float(cand[0].confidence())
        bb = obs.boundingBox()                # normalized, origin bottom-left
        x = bb.origin.x * W
        w = bb.size.width * W
        y = (1.0 - bb.origin.y - bb.size.height) * H
        h = bb.size.height * H
        lines.append(_line(text, x, y, x + w, y + h, conf))
    return lines


def ocr_easyocr(path, W, H):
    import easyocr
    global _EASY
    if _EASY is None:
        _EASY = easyocr.Reader(["ch_sim", "en"], gpu=False)
    out = []
    for box, text, conf in _EASY.readtext(path):
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        out.append(_line(text, min(xs), min(ys), max(xs), max(ys), conf))
    return out


def ocr_paddleocr(path, W, H):
    from paddleocr import PaddleOCR
    global _PADDLE
    if _PADDLE is None:
        _PADDLE = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    res = _PADDLE.ocr(path, cls=True)
    out = []
    for page in (res or []):
        for item in (page or []):
            box, (text, conf) = item[0], item[1]
            xs = [p[0] for p in box]; ys = [p[1] for p in box]
            out.append(_line(text, min(xs), min(ys), max(xs), max(ys), conf))
    return out


def ocr_tesseract(path, W, H):
    import pytesseract
    from pytesseract import Output
    lang = os.environ.get("CHAT_OCR_TESS_LANG", "chi_sim+chi_tra+eng")
    d = pytesseract.image_to_data(path, lang=lang, output_type=Output.DICT)  # pass path, not PIL image (avoids a Pillow decode quirk)
    groups = {}
    for i in range(len(d["text"])):
        t = (d["text"][i] or "").strip()
        c = float(d["conf"][i])
        if not t or c < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        groups.setdefault(key, []).append((t, x, y, x + w, y + h, c / 100.0))
    out = []
    for ws in groups.values():
        text = "".join(w[0] for w in ws) if _looks_cjk(ws) else " ".join(w[0] for w in ws)
        x0 = min(w[1] for w in ws); y0 = min(w[2] for w in ws)
        x1 = max(w[3] for w in ws); y1 = max(w[4] for w in ws)
        conf = sum(w[5] for w in ws) / len(ws)
        out.append(_line(text, x0, y0, x1, y1, conf))
    return out


def _looks_cjk(ws):
    s = "".join(w[0] for w in ws)
    cjk = sum(1 for ch in s if "一" <= ch <= "鿿")
    return cjk >= max(1, len(s) // 2)


_BACKENDS = {"vision": ocr_vision, "easyocr": ocr_easyocr,
             "paddleocr": ocr_paddleocr, "tesseract": ocr_tesseract}


def run_ocr(path, backend, W, H):
    global _CHOSEN
    if backend != "auto":
        try:
            return _BACKENDS[backend](path, W, H)
        except Exception as e:
            raise RuntimeError(f"后端 {backend} 不可用：{type(e).__name__}: {e}\n见 references/ocr-backends.md")
    # auto：优先用已选后端；但若它对这张图读出 0 行，自动换别的后端再试（防某后端对某些图失灵）
    order = ([_CHOSEN] if _CHOSEN else []) + [b for b in BACKEND_ORDER if b != _CHOSEN]
    last, ran_any = None, False
    for b in order:
        try:
            lines = _BACKENDS[b](path, W, H)
        except Exception as e:
            last = f"{b}: {type(e).__name__}: {e}"
            continue
        ran_any = True
        if lines:                       # 只采纳真读出文字的后端
            _CHOSEN = b
            return lines
        last = f"{b}: 0 行"
    if ran_any:
        return []                       # 后端能跑但都没读出文字 → 交给上层按"OCR 失败"处理
    raise RuntimeError(
        "没有可用的 OCR 后端。最后 -> %s\n请先安装一个后端，见 references/ocr-backends.md" % last)


# ----------------------------------------------------------------------------- #
# Avatar detection — pure numpy (no cv2). Find colorful square-ish blocks in the
# far-left / far-right margins (where Chat avatars live).
# ----------------------------------------------------------------------------- #
def detect_avatars(path, W, H):
    if Image is None or np is None:
        return []
    try:
        arr = np.asarray(Image.open(path).convert("RGB")).astype("int16")
    except Exception:
        return []
    mx = arr.max(axis=2); mn = arr.min(axis=2)
    colorful = (mx - mn) > 22                  # 有彩色（纯色头像/合成块/绿气泡）
    gray = arr.mean(axis=2)
    bk = max(6, H // 160)                       # 纹理块大小
    Hc, Wc = (H // bk) * bk, (W // bk) * bk
    g = gray[:Hc, :Wc].reshape(Hc // bk, bk, Wc // bk, bk)
    tex = g.std(axis=(1, 3)) > 18              # 照片头像有纹理；扁平 UI/气泡/背景没有
    textured = np.zeros((H, W), dtype=bool)
    textured[:Hc, :Wc] = np.repeat(np.repeat(tex, bk, axis=0), bk, axis=1)
    colorful = colorful | textured            # 头像 = 彩色 或 有纹理（兼顾深色模式真照片，常是哑色）
    left_x, right_x = int(0.14 * W), int(0.86 * W)
    avatars = []
    for side, (xa, xb) in (("left", (0, left_x)), ("right", (right_x, W))):
        band = colorful[:, xa:xb]
        if band.size == 0:
            continue
        rowcov = band.mean(axis=1)
        runs, s = [], None
        for y, v in enumerate(rowcov > 0.18):
            if v and s is None:
                s = y
            elif not v and s is not None:
                runs.append((s, y)); s = None
        if s is not None:
            runs.append((s, len(rowcov)))
        for y0, y1 in runs:
            h = y1 - y0
            if h < 0.03 * H or h > 0.16 * H:   # plausible avatar height
                continue
            sub = band[y0:y1]
            cols = np.where(sub.mean(axis=0) > 0.15)[0]
            if cols.size == 0:
                continue
            bx0, bx1 = xa + int(cols.min()), xa + int(cols.max())
            w = max(bx1 - bx0, 1)
            ar = w / h
            if ar < 0.5 or ar > 1.8:           # roughly square
                continue
            cov = float(sub.mean())
            conf = round(min(0.95, 0.45 + 0.5 * min(1.0, cov / 0.5)), 3)
            avatars.append({"box": (bx0, int(y0), bx1, int(y1)), "side": side, "conf": conf})
    return avatars


def _content_mask(path, W, H, text_boxes):
    """'视觉内容'掩码（彩色 或 有纹理），已抠掉文字与左右头像栏。给图片/表情检测用。"""
    if Image is None or np is None:
        return None
    try:
        arr = np.asarray(Image.open(path).convert("RGB")).astype("float32")
    except Exception:
        return None
    chroma = (arr.max(axis=2) - arr.min(axis=2)) > 22
    gray = arr.mean(axis=2)
    bk = max(6, H // 160)
    Hc, Wc = (H // bk) * bk, (W // bk) * bk
    g = gray[:Hc, :Wc].reshape(Hc // bk, bk, Wc // bk, bk)
    tex = np.zeros((H, W), dtype=bool)
    tex[:Hc, :Wc] = np.repeat(np.repeat(g.std(axis=(1, 3)) > 11, bk, axis=0), bk, axis=1)
    content = chroma | tex
    for (x0, y0, x1, y1) in text_boxes:
        content[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)] = False
    content[:, :int(0.13 * W)] = False
    content[:, int(0.88 * W):] = False
    return content


# ----------------------------------------------------------------------------- #
# Bubble clustering — group OCR lines into bubbles (vertical proximity + side).
# ----------------------------------------------------------------------------- #
def _side(box, W):
    return "L" if (box[0] + box[2]) / 2 < W * 0.5 else "R"


def cluster_bubbles(lines, W, H):
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: (l["box"][1], l["box"][0]))
    heights = sorted(l["box"][3] - l["box"][1] for l in lines)
    mh = heights[len(heights) // 2] or 20.0
    bubbles, cur = [], [lines[0]]
    for prev, ln in zip(lines, lines[1:]):
        gap = ln["box"][1] - prev["box"][3]
        same = _side(ln["box"], W) == _side(cur[-1]["box"], W)
        if gap > mh * 0.9 or not same:
            bubbles.append(cur); cur = [ln]
        else:
            cur.append(ln)
    bubbles.append(cur)
    return bubbles


def _bubble_box(b):
    return (min(l["box"][0] for l in b), min(l["box"][1] for l in b),
            max(l["box"][2] for l in b), max(l["box"][3] for l in b))


# ----------------------------------------------------------------------------- #
# Speaker assignment — avatar in same y-band first, bubble-center fallback.
# ----------------------------------------------------------------------------- #
def assign_speaker(box, avatars, W, me_side):
    x0, y0, x1, y1 = box
    cx, w = (x0 + x1) / 2, (x1 - x0)
    tol = (y1 - y0) * 0.6 + 10
    near = [a for a in avatars if y0 - tol <= (a["box"][1] + a["box"][3]) / 2 <= y1 + tol]
    left = [a for a in near if a["side"] == "left"]
    right = [a for a in near if a["side"] == "right"]
    me, other = me_side, ("right" if me_side == "left" else "left")
    # 1) 头像优先：同一 y 带内只有一侧头像
    if left and not right:
        return ("me" if me == "left" else "other"), 0.92, "附近左侧头像", "left"
    if right and not left:
        return ("me" if me == "right" else "other"), 0.92, "附近右侧头像", "right"
    # 2) 头像失败 -> 看气泡贴哪边（比"中心 vs 屏幕中线"稳得多）
    left_gap, right_gap = x0, W - x1
    hugs_left, hugs_right = left_gap < W * 0.30, right_gap < W * 0.30
    if hugs_left and not hugs_right:
        return ("me" if me == "left" else "other"), 0.70, "无头像 fallback：气泡贴左边", None
    if hugs_right and not hugs_left:
        return ("me" if me == "right" else "other"), 0.70, "无头像 fallback：气泡贴右边", None
    # 3) 居中且窄、两侧留白对称 -> 系统/时间
    if w < W * 0.5 and abs(left_gap - right_gap) < W * 0.15:
        return "system", 0.6, "居中且窄、两侧留白对称，疑似时间/系统提示", None
    # 4) 兜底：用中心位置，但低置信
    if cx < W * 0.5:
        return ("me" if me == "left" else "other"), 0.5, "兜底：气泡偏左（低置信）", None
    if cx > W * 0.5:
        return ("me" if me == "right" else "other"), 0.5, "兜底：气泡偏右（低置信）", None
    return "unknown", 0.3, "居中/信号冲突，无法判定", None


# ----------------------------------------------------------------------------- #
def _is_status_bar(text):
    """像手机状态栏：只有数字/冒号/%/空格（时间 06:07、电量 76），且不含中文日期字。
    聊天日期戳（含 年/月/日）会被保留。"""
    t = (text or "").strip()
    return bool(t) and bool(re.fullmatch(r"[\d:%\s]+", t)) and not any(c in t for c in "年月日")


def image_size(path):
    if Image is not None:
        with Image.open(path) as im:
            return im.size
    raise RuntimeError("需要 Pillow 读取图片尺寸：pip install pillow")


def process_image(path, backend, me_side, crop_top=0.0, crop_bottom=0.0):
    W, H = image_size(path)
    lines = run_ocr(path, backend, W, H)

    # 状态栏按"内容"识别后丢弃，而不是按固定比例裁——否则没状态栏的截图首/尾消息会被误删
    def _keep(l):
        yc = (l["box"][1] + l["box"][3]) / 2
        if yc < crop_top * H or yc > (1.0 - crop_bottom) * H:
            return False
        if yc < 0.10 * H and _is_status_bar(l["text"]):   # 顶部且只有时间/电量数字 → 状态栏
            return False
        return True
    lines = [l for l in lines if _keep(l)]
    if not lines:
        # OCR 一个字都没读出来（深色截图/红笔标注可能干扰）——别凭头像硬塞一堆〔图片〕，老实报失败
        return [{
            "speaker": "unknown",
            "text": "⚠️ 这张图没读出任何文字（深色截图 / 标注可能干扰 OCR）——换个 OCR 后端，或让带视觉的模型直接看原图",
            "confidence": 0.2, "reason": "OCR 返回 0 行文字",
            "avatar_side": None, "ocr_confidence": 0.0,
            "bbox": [0, 0, int(W), int(H)], "image": os.path.basename(path),
        }]
    avatars = detect_avatars(path, W, H)
    msgs = []
    for b in cluster_bubbles(lines, W, H):
        text = "\n".join(l["text"] for l in b).strip()
        if not text or (len(text) <= 1 and not any("一" <= c <= "鿿" for c in text)):
            continue   # 跳过空 / 单字符 UI 噪声（如 "+"、"V"）；单个中文字(嗯/好)保留
        box = _bubble_box(b)
        sp, conf, reason, av_side = assign_speaker(box, avatars, W, me_side)
        ocr_conf = round(sum(l["conf"] for l in b) / len(b), 3)
        if ocr_conf < 0.4:
            conf = round(conf * 0.7, 3)
            reason += f"；OCR 置信度低({ocr_conf})"
        msgs.append({
            "speaker": sp,
            "text": text,
            "confidence": round(conf, 3),
            "reason": reason,
            "avatar_side": av_side,
            "ocr_confidence": ocr_conf,
            "bbox": [int(round(v)) for v in box],
            "image": os.path.basename(path),
            "_yc": (box[1] + box[3]) / 2,
        })
    # 图片/表情消息：头像锚定——某侧有头像、该 y 行无文字、但确有图像内容
    text_yc = [m["_yc"] for m in msgs]
    content = _content_mask(path, W, H, [l["box"] for l in lines]) if avatars else None
    xa, xb = int(0.13 * W), int(0.88 * W)
    if content is not None:
        for a in avatars:
            atop = a["box"][1]
            ah = max(a["box"][3] - a["box"][1], 20)
            ay = atop + ah / 2
            if any(abs(ty - ay) < ah * 0.8 for ty in text_yc):
                continue                                    # 该行是文字消息
            y0, y1 = int(max(0, atop - 0.3 * ah)), int(min(H, atop + 3.0 * ah))
            band = content[y0:y1, xa:xb]
            if band.size == 0 or float(band.mean()) < 0.05:
                continue                                    # 没图像内容 → 伪头像，跳过
            rows = np.where(band.mean(axis=1) > 0.06)[0]
            cols = np.where(band.mean(axis=0) > 0.06)[0]
            if rows.size == 0 or cols.size == 0:
                continue
            iy0, iy1 = y0 + int(rows.min()), y0 + int(rows.max())
            ix0, ix1 = xa + int(cols.min()), xa + int(cols.max())
            if (ix1 - ix0) < 0.06 * W or (iy1 - iy0) < 0.04 * H:
                continue
            kind = "图片" if ((ix1 - ix0) > 0.30 * W or (iy1 - iy0) > 0.13 * H) else "表情"
            sp = "me" if a["side"] == me_side else "other"
            msgs.append({
                "speaker": sp, "text": f"〔{kind}〕",
                "confidence": 0.6,
                "reason": f"{a['side']}侧头像、该行无文字、有图像内容 → {kind}",
                "avatar_side": a["side"], "ocr_confidence": 0.0,
                "bbox": [ix0, iy0, ix1, iy1],
                "image": os.path.basename(path), "_yc": (iy0 + iy1) / 2,
            })
    msgs.sort(key=lambda m: m["_yc"])
    for m in msgs:
        m.pop("_yc", None)
    return msgs


# ----------------------------------------------------------------------------- #
LABELS = {"other": "对方", "me": "我", "system": "系统", "unknown": "❓未知"}


def to_markdown(messages, sources, backend):
    out = ["# 聊天（OCR 还原）", "",
           f"> 来源：{', '.join(sources)}  ·  后端：{backend}  ·  低置信度项已标注 confidence/reason", ""]
    for m in messages:
        flag = "" if m["confidence"] >= 0.75 else f"  _(conf {m['confidence']} · {m['reason']})_"
        if m["speaker"] == "system":
            out.append(f"*— {m['text']} —*{flag}")
        else:
            body = m["text"].replace("\n", " / ")
            out.append(f"**{LABELS.get(m['speaker'], m['speaker'])}：** {body}{flag}")
        out.append("")
    return "\n".join(out)


def collect_images(inp):
    if os.path.isdir(inp):
        files = [os.path.join(inp, f) for f in os.listdir(inp)
                 if f.lower().endswith(IMG_EXTS)]
        return sorted(files)
    return [inp] if inp.lower().endswith(IMG_EXTS) else []


def main():
    ap = argparse.ArgumentParser(
        description="聊天截图 → 结构化对话 (speaker-aware OCR)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python scripts/chat_ocr.py input_screenshots/ "
               "--out outputs/chat.json --markdown outputs/chat.md")
    ap.add_argument("input", help="一张截图，或一个装满截图的目录（按文件名排序拼接）")
    ap.add_argument("--out", default="outputs/chat.json", help="JSON 输出路径")
    ap.add_argument("--markdown", default=None, help="Markdown 输出路径（可选）")
    ap.add_argument("--backend", default="auto",
                    choices=["auto"] + BACKEND_ORDER, help="OCR 后端，默认 auto")
    ap.add_argument("--me-side", default="right", choices=["right", "left"],
                    help="\"我\"在哪一侧（聊天软件默认 right）")
    ap.add_argument("--crop-top", type=float, default=0.0,
                    help="额外忽略顶部比例（默认 0；状态栏已按内容自动识别）")
    ap.add_argument("--crop-bottom", type=float, default=0.0,
                    help="额外忽略底部比例（默认 0）")
    a = ap.parse_args()

    paths = collect_images(a.input)
    if not paths:
        ap.error(f"没找到截图：{a.input}（支持 {', '.join(IMG_EXTS)}）")

    messages = []
    for p in paths:
        try:
            messages.extend(process_image(p, a.backend, a.me_side, a.crop_top, a.crop_bottom))
        except RuntimeError as e:
            print(str(e), file=sys.stderr); sys.exit(2)
    for i, m in enumerate(messages):
        m["index"] = i

    data = {
        "source_images": [os.path.basename(p) for p in paths],
        "backend": _CHOSEN,
        "me_side": a.me_side,
        "count": len(messages),
        "messages": messages,
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if a.markdown:
        os.makedirs(os.path.dirname(os.path.abspath(a.markdown)), exist_ok=True)
        with open(a.markdown, "w", encoding="utf-8") as f:
            f.write(to_markdown(messages, data["source_images"], _CHOSEN))

    low = sum(1 for m in messages if m["confidence"] < 0.75)
    by = {}
    for m in messages:
        by[m["speaker"]] = by.get(m["speaker"], 0) + 1
    print(f"[chat-ocr] backend={_CHOSEN}  images={len(paths)}  messages={len(messages)}  "
          f"low_conf={low}  by_speaker={by}")
    print(f"[chat-ocr] JSON -> {a.out}" + (f"  Markdown -> {a.markdown}" if a.markdown else ""))


if __name__ == "__main__":
    main()

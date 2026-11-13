# -*- coding: utf-8 -*-
"""Figures 1, 3, 4 for the Seoul AgentCore Runtime V2 post.

Values come from ~/my-project/agentcore-v2/results-seoul/ (2026-11-13, ap-northeast-2):
detail_stats.json, deploy.log, mem_usage.json. Figure 2 (measurement setup) is an
AWS architecture diagram drawn with the aws-diagram skill, not here.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from diagram_lib import *

OUT = os.environ.get("BLOG_IMAGES", os.path.join(os.path.dirname(__file__), "..", "images"))
os.makedirs(OUT, exist_ok=True)
SLUG = "agentcore-runtime-v2-seoul"

# Seoul main round, cold start p75 in seconds (runtime당 새 세션 30개, 동시성 5)
COLD_P75 = [("200 MB", 5.37, 1.77, "3.0배"), ("1 GB", 13.41, 1.74, "7.7배"), ("2 GB", 27.51, 1.81, "15.2배")]
# Seoul elastic-memory round: implied billed footprint (GB) and GB-hours ratio
MEM = [("V1", INK, 1.27, 2.87, "+1.60 GB 잔존", "GB-hours 2.33배"),
       ("V2", SERIES_TEAL, 1.20, 1.28, "+0.08 GB 잔존", "GB-hours 1.10배")]


def px(value, per_unit):
    """Bar height snapped to the 4 px grid the library asserts."""
    return max(4, int(round(value * per_unit / 4.0)) * 4)


def bar(c, x, y_base, w, h, color, dashed=False, fill_op=0.18):
    g4(x, y_base, w, h)
    dash = ' stroke-dasharray="4,3"' if dashed else ""
    c.layers["nodes"].append(
        f'<rect x="{x}" y="{y_base-h}" width="{w}" height="{h}" rx="2" fill="{color}" fill-opacity="{fill_op}" '
        f'stroke="{color}" stroke-width="1.2"{dash}/>')


def hline(c, x1, x2, y, color=RULE, width=0.8, dashed=False):
    g4(x1, x2, y)
    dash = ' stroke-dasharray="6,4"' if dashed else ""
    c.layers["zones"].append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="{width}"{dash}/>')


# --------------------------------------------------------------------------
# 그림 1. V1과 V2의 세션 시작 경로
# --------------------------------------------------------------------------
def fig01():
    c = Canvas(f"{SLUG}-fig01", "V1과 V2의 세션 시작 경로",
               "V1은 세션마다 이미지 pull, 프로세스 기동, 초기화를 반복하고, V2는 런타임 생성 시 한 번 초기화한 환경의 스냅샷을 모든 세션이 복원한다")
    c.text("top", 40, 44, "세션 시작 경로: V1(매 세션 전체 시작)과 V2(스냅샷 복원)", size=20, weight=600)
    # V1 lane
    c.zone(40, 72, 1200, 256, title="platformVersion V1", eyebrow="새 세션마다 전체 시작 절차를 반복")
    xs = [64, 296, 528, 760, 992]
    names = [("새 세션 요청", "input"), ("이미지 pull", "backend"), ("프로세스 기동", "backend"),
             ("초기화 코드 실행", "backend"), ("첫 요청 처리", "backend")]
    for x, (n, k) in zip(xs, names):
        c.node(x, 160, 200, 72, n, kind=k)
    for a, b in zip(xs, xs[1:]):
        c.arrow([(a + 200, 196), (b, 196)], color=INK)
    c.text("zones", 296, 276, "서울 리전 cold start p75 (이미지 크기에 비례)", size=16, fill=SOFT)
    c.text("zones", 296, 304, "200 MB 5.37초 / 1 GB 13.41초 / 2 GB 27.51초", size=16, fill=INK, mono=True)
    # V2 lane
    c.zone(40, 352, 1200, 288, title="platformVersion V2", eyebrow="위 행은 런타임 생성/업데이트 시 1회, 아래 행은 새 세션마다")
    c.node(64, 416, 248, 72, "컨테이너 기동, 초기화", kind="backend")
    # Nodes are narrower than the V1 lane so the measured values fit inside the zone.
    c.node(344, 416, 232, 72, "/ping 정상 응답", sub="120초 이내", kind="backend")
    c.node(608, 416, 168, 72, "스냅샷 촬영", kind="backend")
    c.arrow([(312, 452), (344, 452)], color=SERIES_TEAL)
    c.arrow([(576, 452), (608, 452)], color=SERIES_TEAL)
    c.node(64, 552, 248, 72, "새 세션 요청", kind="input")
    c.node(344, 552, 232, 72, "스냅샷 복원", kind="backend")
    c.node(608, 552, 168, 72, "첫 요청 처리", kind="backend")
    c.arrow([(312, 588), (344, 588)], color=SERIES_TEAL)
    c.arrow([(576, 588), (608, 588)], color=SERIES_TEAL)
    c.arrow([(692, 488), (692, 520), (460, 520), (460, 552)], color=SERIES_TEAL, dashed=True)
    c.text("zones", 808, 440, "런타임 생성에서 READY까지 185초에서 216초", size=16, fill=SOFT)
    c.text("zones", 808, 468, "(V1은 3.1초에서 3.3초)", size=16, fill=SOFT)
    c.text("zones", 808, 576, "서울 리전 cold start p75 (이미지 크기 무관)", size=16, fill=SOFT)
    c.text("zones", 808, 604, "200 MB 1.77초 / 1 GB 1.74초 / 2 GB 1.81초", size=16, fill=SERIES_TEAL, mono=True)
    c.legend([("ink", "V1 시작 경로 (세션마다 반복)"), ("teal", "V2 시작 경로"),
              ("dashed", "스냅샷 촬영 후 세션마다 참조")], y=664)
    c.check()
    c.write(os.path.join(OUT, f"{SLUG}-fig01-start-path.html"), os.path.join(OUT, f"{SLUG}-fig01-start-path.svg"))
    print("OK fig01")


# --------------------------------------------------------------------------
# 그림 3. 이미지 크기별 cold start p75
# --------------------------------------------------------------------------
def fig03():
    v1s = ", ".join(f"{v1:.2f}초" for _, v1, _, _ in COLD_P75)
    v2s = ", ".join(f"{v2:.2f}초" for _, _, v2, _ in COLD_P75)
    c = Canvas(f"{SLUG}-fig03", "서울 리전 이미지 크기별 cold start p75",
               f"V1은 {v1s}로 이미지 크기에 비례해 증가하고 V2는 {v2s}로 2초 아래에 머문다")
    c.text("top", 40, 44, "서울 리전 cold start p75: V1 대 V2 (런타임당 새 세션 30개, 동시성 5)", size=20, weight=600)
    base, per_s = 584, 16  # 0..30 s, 16 px per second
    for s in range(0, 31, 5):
        y = base - s * per_s
        hline(c, 120, 1200, y, color=RULE if s else RULE_SOLID, width=0.8 if s else 1.2)
        c.text("zones", 104, y + 4, str(s), size=16, fill=MUTED, anchor="end", mono=True)
    c.text("zones", 104, 84, "초", size=16, fill=SOFT, anchor="end")
    hline(c, 120, 1200, base - 2 * per_s, color=MUTED, dashed=True)
    centers = [320, 640, 960]
    for cx, (lab, v1, v2, ratio) in zip(centers, COLD_P75):
        h1, h2 = px(v1, per_s), px(v2, per_s)
        bar(c, cx - 136, base, 120, h1, INK, fill_op=0.15)
        bar(c, cx + 16, base, 120, h2, SERIES_TEAL)
        c.text("nodes", cx - 76, base - h1 - 12, f"{v1:.2f}초", size=16, fill=INK, anchor="middle", mono=True)
        c.text("nodes", cx + 76, base - h2 - 12, f"{v2:.2f}초", size=16, fill=SERIES_TEAL, anchor="middle", mono=True)
        c.text("nodes", cx, 616, lab, size=20, weight=600, fill=INK, anchor="middle")
        c.text("nodes", cx, 640, f"V1 ÷ V2 = {ratio}", size=16, fill=ACCENT, anchor="middle", mono=True)
    c.legend([("fill-ink", "V1 cold start p75"), ("fill-teal", "V2 cold start p75"),
              ("dashed", "2초 기준선 (V2는 1.74초에서 1.81초)")], y=664)
    c.check()
    c.write(os.path.join(OUT, f"{SLUG}-fig03-cold-start-p75.html"), os.path.join(OUT, f"{SLUG}-fig03-cold-start-p75.svg"))
    print("OK fig03")


# --------------------------------------------------------------------------
# 그림 4. 탄력 메모리: 해제한 스파이크가 남기는 과금 footprint
# --------------------------------------------------------------------------
def fig04():
    c = Canvas(f"{SLUG}-fig04", "1.5 GB 할당 후 해제한 세션의 과금 footprint",
               "V1은 대조군 1.27 GB에서 2.87 GB로 1.60 GB가 남고 V2는 1.20 GB에서 1.28 GB로 0.08 GB만 남는다")
    c.text("top", 40, 44, "1.5 GB 할당 후 해제한 세션의 과금 footprint (서울 리전, 레그당 4세션, 세션-시간 약 0.10 h)",
           size=20, weight=600)
    base, per_gb = 584, 120  # 0..4 GB
    for g in range(0, 5):
        y = base - g * per_gb
        hline(c, 120, 1200, y, color=RULE if g else RULE_SOLID, width=0.8 if g else 1.2)
        c.text("zones", 104, y + 4, str(g), size=16, fill=MUTED, anchor="end", mono=True)
    c.text("zones", 104, 84, "GB", size=16, fill=SOFT, anchor="end")
    centers = [400, 880]
    for cx, (lab, col, ctrl, alloc, delta, sub) in zip(centers, MEM):
        hc, ha = px(ctrl, per_gb), px(alloc, per_gb)
        bar(c, cx - 184, base, 160, hc, INK, dashed=True, fill_op=0.05)
        bar(c, cx + 24, base, 160, ha, col)
        c.text("nodes", cx - 104, base - hc - 12, f"{ctrl:.2f} GB", size=16, fill=MUTED, anchor="middle", mono=True)
        c.text("nodes", cx + 104, base - ha - 12, f"{alloc:.2f} GB", size=16, fill=col, anchor="middle", mono=True)
        c.text("nodes", cx + 104, base - ha - 36, delta, size=16, fill=ACCENT, anchor="middle", mono=True)
        c.text("nodes", cx, 616, lab, size=20, weight=600, fill=col, anchor="middle")
        c.text("nodes", cx, 640, sub, size=16, fill=MUTED, anchor="middle", mono=True)
    c.text("zones", 1200, 96, "프로세스 RSS: 50.4 MB, 최고 1,593.4 MB, 해제 후 52.5 MB", size=16, fill=SOFT,
           anchor="end", mono=True)
    c.legend([("fill-standby", "대조군 (할당 없음, 같은 세션 모양)"), ("fill-ink", "V1 스파이크 후"),
              ("fill-teal", "V2 스파이크 후")], y=664)
    c.check()
    c.write(os.path.join(OUT, f"{SLUG}-fig04-elastic-memory.html"), os.path.join(OUT, f"{SLUG}-fig04-elastic-memory.svg"))
    print("OK fig04")


if __name__ == "__main__":
    fig01(); fig03(); fig04()

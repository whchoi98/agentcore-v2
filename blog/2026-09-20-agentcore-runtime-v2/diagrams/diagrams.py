# -*- coding: utf-8 -*-
"""Figures for the AgentCore Runtime V2 post. Values come from results/detail_stats.json."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from diagram_lib import *

OUT = os.environ.get("BLOG_IMAGES", os.path.join(os.path.dirname(__file__), "..", "images"))
os.makedirs(OUT, exist_ok=True)
SLUG = "agentcore-runtime-v2"


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
    c.text("zones", 296, 276, "cold start p75 실측 (이미지 크기에 비례)", size=16, fill=SOFT)
    c.text("zones", 296, 304, "200 MB 5.47초 / 1 GB 13.48초 / 2 GB 27.70초", size=16, fill=INK, mono=True)
    # V2 lane
    c.zone(40, 352, 1200, 288, title="platformVersion V2", eyebrow="위 행은 런타임 생성/업데이트 시 1회, 아래 행은 새 세션마다")
    c.node(64, 416, 248, 72, "컨테이너 기동, 초기화", kind="backend")
    c.node(344, 416, 264, 72, "/ping 정상 응답", sub="120초 이내", kind="backend")
    c.node(640, 416, 184, 72, "스냅샷 촬영", kind="backend")
    c.arrow([(312, 452), (344, 452)], color=SERIES_TEAL)
    c.arrow([(608, 452), (640, 452)], color=SERIES_TEAL)
    c.node(64, 552, 248, 72, "새 세션 요청", kind="input")
    c.node(344, 552, 264, 72, "스냅샷 복원", kind="backend")
    c.node(640, 552, 184, 72, "첫 요청 처리", kind="backend")
    c.arrow([(312, 588), (344, 588)], color=SERIES_TEAL)
    c.arrow([(608, 588), (640, 588)], color=SERIES_TEAL)
    c.arrow([(732, 488), (732, 520), (476, 520), (476, 552)], color=SERIES_TEAL, dashed=True)
    c.text("zones", 856, 440, "런타임 생성에서 READY까지 186초에서 217초", size=16, fill=SOFT)
    c.text("zones", 856, 468, "(V1은 3.3초)", size=16, fill=SOFT)
    c.text("zones", 856, 576, "cold start p75 실측 (이미지 크기 무관)", size=16, fill=SOFT)
    c.text("zones", 856, 604, "200 MB 1.97초 / 1 GB 2.10초 / 2 GB 1.98초", size=16, fill=SERIES_TEAL, mono=True)
    c.legend([("ink", "V1 시작 경로 (세션마다 반복)"), ("teal", "V2 시작 경로"),
              ("dashed", "스냅샷 촬영 후 세션마다 참조")], y=664)
    c.check()
    c.write(os.path.join(OUT, f"{SLUG}-fig01-start-path.html"), os.path.join(OUT, f"{SLUG}-fig01-start-path.svg"))
    print("OK fig01")


# --------------------------------------------------------------------------
# 그림 2. 측정 구성
# --------------------------------------------------------------------------
def fig02():
    c = Canvas(f"{SLUG}-fig02", "측정 구성",
               "서울 리전 EC2 클라이언트가 도쿄 리전의 AgentCore Runtime 6개(이미지 3종 × V1, V2)를 호출하고 과금 사용량은 CloudWatch 지표로 수집한다")
    c.text("top", 40, 44, "측정 구성: 서울 리전 클라이언트, 도쿄 리전 AgentCore Runtime 6개", size=20, weight=600)
    # Seoul
    c.zone(40, 72, 272, 552, title="서울 리전", eyebrow="ap-northeast-2")
    c.node(64, 296, 224, 96, "벤치마크 클라이언트", sub="EC2 aarch64", sub2="boto3 1.43.98", kind="input")
    c.text("zones", 64, 436, "InvokeAgentRuntime", size=16, fill=MUTED, mono=True)
    c.text("zones", 64, 460, "새 runtimeSessionId = cold start", size=16, fill=SOFT)
    c.text("zones", 64, 492, "StopRuntimeSession", size=16, fill=MUTED, mono=True)
    c.text("zones", 64, 516, "측정 직후 세션 정지", size=16, fill=SOFT)
    c.text("zones", 64, 560, "리전 간 왕복 중위값", size=16, fill=SOFT)
    c.text("zones", 64, 588, "TCP 34.5 ms / TLS 69.9 ms", size=16, fill=INK, mono=True)
    # Tokyo
    c.zone(424, 72, 816, 552, title="도쿄 리전", eyebrow="ap-northeast-1 (V2 제공 리전)")
    c.zone(448, 136, 768, 96, title="Amazon ECR: 이미지 3종 (linux/arm64)", fill=INK, fill_op=0.02, stroke=INK, stroke_op=0.20)
    cols = [520, 760, 1000]
    for x, n in zip(cols, ["200mb (45.4 MiB)", "1gb (842.6 MiB)", "2gb (1,866.9 MiB)"]):
        c.node(x, 176, 208, 48, n, name_size=16, kind="store")
        c.arrow([(x + 104, 224), (x + 104, 256)], color=MUTED)
    c.zone(448, 256, 768, 232, title="AgentCore Runtime (microVM) 6개", fill=INK, fill_op=0.02, stroke=INK, stroke_op=0.20)
    c.text("zones", 464, 352, "V1", size=20, weight=600, fill=INK)
    c.text("zones", 464, 440, "V2", size=20, weight=600, fill=SERIES_TEAL)
    for x, n in zip(cols, ["200mb", "1gb", "2gb"]):
        c.node(x, 312, 208, 64, f"V1 / {n}", sub="cold 30, burst 50, warm 1", kind="backend")
        c.node(x, 400, 208, 64, f"V2 / {n}", sub="cold 30, burst 50, warm 1", kind="backend")
    c.zone(448, 512, 768, 96, title=None, fill=INK, fill_op=0.02, stroke=INK, stroke_op=0.20)
    c.node(464, 528, 736, 64, "Amazon CloudWatch", sub="AWS/Bedrock-AgentCore: MemoryUsed-GBHours, CPUUsed-vCPUHours (Resource = 런타임 ARN)", kind="store")
    c.arrow([(288, 344), (424, 344)], color=MUTED)
    c.arrow([(288, 344), (392, 344), (392, 432), (424, 432)], color=MUTED)
    c.arrow([(832, 488), (832, 528)], color=MUTED, dashed=True)
    c.legend([("solid", "InvokeAgentRuntime (리전 간 공용 인터넷)"), ("dashed", "과금 사용량 지표 (최대 60분 지연)"),
              ("fill-backend", "런타임 = 이미지 × platformVersion")], y=664)
    c.check()
    c.write(os.path.join(OUT, f"{SLUG}-fig02-bench-setup.html"), os.path.join(OUT, f"{SLUG}-fig02-bench-setup.svg"))
    print("OK fig02")


# --------------------------------------------------------------------------
# 그림 3. 이미지 크기별 cold start p75
# --------------------------------------------------------------------------
def fig03():
    c = Canvas(f"{SLUG}-fig03", "이미지 크기별 cold start p75",
               "V1은 5.47초, 13.48초, 27.70초로 이미지 크기에 비례해 증가하고 V2는 1.97초, 2.10초, 1.98초로 약 2초에 머문다")
    c.text("top", 40, 44, "이미지 크기별 cold start p75: V1 대 V2 (런타임당 새 세션 30개, 동시성 5)", size=20, weight=600)
    base, top = 584, 104  # 0..30 s, 16 px per second
    for s in range(0, 31, 5):
        y = base - s * 16
        hline(c, 120, 1200, y, color=RULE if s else RULE_SOLID, width=0.8 if s else 1.2)
        c.text("zones", 104, y + 4, str(s), size=16, fill=MUTED, anchor="end", mono=True)
    c.text("zones", 104, 84, "초", size=16, fill=SOFT, anchor="end")
    hline(c, 120, 1200, base - 32, color=MUTED, dashed=True)
    data = [("200 MB", 5.47, 1.97, 88, 32, "2.8배"), ("1 GB", 13.48, 2.10, 216, 36, "6.4배"), ("2 GB", 27.70, 1.98, 444, 32, "14.0배")]
    centers = [320, 640, 960]
    for cx, (lab, v1, v2, h1, h2, ratio) in zip(centers, data):
        bar(c, cx - 136, base, 120, h1, INK, fill_op=0.15)
        bar(c, cx + 16, base, 120, h2, SERIES_TEAL)
        c.text("nodes", cx - 76, base - h1 - 12, f"{v1:.2f}초", size=16, fill=INK, anchor="middle", mono=True)
        c.text("nodes", cx + 76, base - h2 - 12, f"{v2:.2f}초", size=16, fill=SERIES_TEAL, anchor="middle", mono=True)
        c.text("nodes", cx, 616, lab, size=20, weight=600, fill=INK, anchor="middle")
        c.text("nodes", cx, 640, f"V1 ÷ V2 = {ratio}", size=16, fill=ACCENT, anchor="middle", mono=True)
    c.legend([("fill-ink", "V1 cold start p75"), ("fill-teal", "V2 cold start p75"), ("dashed", "2초 기준선 (V2는 1.9초에서 2.1초 밴드)")], y=664)
    c.check()
    c.write(os.path.join(OUT, f"{SLUG}-fig03-cold-start-p75.html"), os.path.join(OUT, f"{SLUG}-fig03-cold-start-p75.svg"))
    print("OK fig03")


# --------------------------------------------------------------------------
# 그림 4. 탄력 메모리: 해제한 스파이크가 남기는 과금 footprint
# --------------------------------------------------------------------------
def fig04():
    c = Canvas(f"{SLUG}-fig04", "1.5 GB 할당 후 해제한 세션의 과금 footprint",
               "V1은 대조군 1.69 GB에서 3.64 GB로 1.95 GB가 남고 V2는 1.11 GB에서 1.27 GB로 0.16 GB만 남아 해제한 메모리의 약 92%가 회수된다")
    c.text("top", 40, 44, "1.5 GB 할당 후 해제한 세션의 과금 footprint (레그당 4세션, 세션-시간 약 0.10 h)", size=20, weight=600)
    base = 584  # 0..4 GB, 120 px per GB
    for g in range(0, 5):
        y = base - g * 120
        hline(c, 120, 1200, y, color=RULE if g else RULE_SOLID, width=0.8 if g else 1.2)
        c.text("zones", 104, y + 4, str(g), size=16, fill=MUTED, anchor="end", mono=True)
    c.text("zones", 104, 84, "GB", size=16, fill=SOFT, anchor="end")
    groups = [("V1", INK, 1.69, 3.64, 204, 436, "+1.95 GB 잔존", "GB-hours 2.23배"),
              ("V2", SERIES_TEAL, 1.11, 1.27, 132, 152, "+0.16 GB 잔존", "GB-hours 1.17배, 약 92% 회수")]
    centers = [400, 880]
    for cx, (lab, col, ctrl, alloc, hc, ha, delta, sub) in zip(centers, groups):
        bar(c, cx - 184, base, 160, hc, INK, dashed=True, fill_op=0.05)
        bar(c, cx + 24, base, 160, ha, col)
        c.text("nodes", cx - 104, base - hc - 12, f"{ctrl:.2f} GB", size=16, fill=MUTED, anchor="middle", mono=True)
        c.text("nodes", cx + 104, base - ha - 12, f"{alloc:.2f} GB", size=16, fill=col, anchor="middle", mono=True)
        c.text("nodes", cx + 104, base - ha - 36, delta, size=16, fill=ACCENT, anchor="middle", mono=True)
        c.text("nodes", cx, 616, lab, size=20, weight=600, fill=col, anchor="middle")
        c.text("nodes", cx, 640, sub, size=16, fill=MUTED, anchor="middle", mono=True)
    c.text("zones", 1200, 96, "RSS 실측: 50.8 MB, 최고 1,593.8 MB, 해제 후 52.9 MB", size=16, fill=SOFT, anchor="end", mono=True)
    c.legend([("fill-standby", "대조군 (할당 없음, 같은 세션 모양)"), ("fill-ink", "V1 스파이크 후"), ("fill-teal", "V2 스파이크 후")], y=664)
    c.check()
    c.write(os.path.join(OUT, f"{SLUG}-fig04-elastic-memory.html"), os.path.join(OUT, f"{SLUG}-fig04-elastic-memory.svg"))
    print("OK fig04")


if __name__ == "__main__":
    fig01(); fig02(); fig03(); fig04()

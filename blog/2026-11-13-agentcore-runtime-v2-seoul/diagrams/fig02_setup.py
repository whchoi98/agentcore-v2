# -*- coding: utf-8 -*-
"""Figure 2: measurement setup, drawn with official AWS icons (aws-diagram skill).

Writes a draft SVG with bundle: icon refs, inlines the icons with the skill's
embed.py, then wraps the result in the same HTML shell diagram_lib uses so
render_diagrams.py can check fonts and overflow and produce the PNG.

  python3 fig02_setup.py            # BLOG_IMAGES selects the output folder
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("BLOG_IMAGES", os.path.join(HERE, "..", "images"))
SKILL = "/home/ec2-user/.claude/plugins/cache/my-plugins/my-plugins/1.3.0/skills/aws-diagram"
NAME = "agentcore-runtime-v2-seoul-fig02-bench-setup"

INK, MUTED, SOFT, TEAL = "#232F3E", "#545B64", "#7D8998", "#01A88D"
REGION, VPC = "#00A4A6", "#7AA116"
SANS = "'Amazon Ember', 'Noto Sans CJK KR', 'Helvetica Neue', Helvetica, Arial, sans-serif"
TITLE = "측정 구성"
DESC = ("서울 리전 VPC의 EC2 클라이언트가 같은 리전의 AgentCore Runtime 8개를 InvokeAgentRuntime으로 호출하고, "
        "런타임은 ECR 이미지를 사용하며, 사용량과 OverheadLatency는 CloudWatch 지표로 수집한다")


def t(x, y, s, size=16, weight=400, fill=INK, anchor="start"):
    for v in (x, y):
        assert v % 4 == 0, (s, v)
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'font-family="{SANS}" text-anchor="{anchor}">{s}</text>')


def rect(x, y, w, h, stroke, fill="none", dash=False, width=2, rx=8):
    for v in (x, y, w, h):
        assert v % 4 == 0, (x, y, w, h)
    d = ' stroke-dasharray="8,6"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}"{d}/>')


def icon(ref, x, y, size):
    return f'<image href="bundle:{ref}" x="{x}" y="{y}" width="{size}" height="{size}"/>'


def arrow(points):
    pts = " ".join(f"{x},{y}" for x, y in points)
    return (f'<polyline points="{pts}" fill="none" stroke="{INK}" stroke-width="1.6" '
            f'marker-end="url(#arrow-ink)"/>')


def build():
    e = []
    e.append(t(40, 44, "측정 구성: 클라이언트와 AgentCore Runtime이 모두 서울 리전에 있다", 20, 600))
    # AWS Cloud > Region
    e.append(rect(40, 72, 1200, 560, INK))
    e.append(icon("group/AWS-Cloud_32", 52, 84, 24))
    e.append(t(84, 104, "AWS Cloud", 16, 600))
    e.append(rect(64, 116, 1152, 500, REGION, dash=True))
    e.append(icon("group/Region_32", 76, 128, 24))
    e.append(t(108, 148, "서울 리전 (ap-northeast-2)", 16, 600))
    # VPC with the benchmark client
    e.append(rect(96, 168, 272, 232, VPC))
    e.append(icon("group/Virtual-private-cloud-VPC_32", 108, 180, 24))
    e.append(t(140, 200, "VPC", 16, 600, fill=VPC))
    e.append(icon("service/Amazon-EC2", 200, 216, 64))
    e.append(t(232, 312, "Amazon EC2", 20, 600, anchor="middle"))
    e.append(t(232, 340, "벤치마크 클라이언트", 16, fill=MUTED, anchor="middle"))
    e.append(t(232, 364, "r8g.4xlarge, boto3 1.44.2", 16, fill=MUTED, anchor="middle"))
    # AgentCore Runtime group
    e.append(rect(592, 168, 592, 280, "#D5DBDB", fill="#F7F8F8", width=1.5))
    e.append(icon("agentcore-dark/Runtime", 608, 184, 40))
    e.append(t(660, 204, "Amazon Bedrock AgentCore Runtime", 20, 600))
    e.append(t(660, 228, "PUBLIC 네트워크 모드, 런타임 8개", 16, fill=MUTED))
    labels = ["200mb", "1gb", "2gb", "mem"]
    xs = [624, 760, 896, 1032]
    for row_y, ver, stroke, fill in ((256, "V1", INK, "#FFFFFF"), (336, "V2", TEAL, "#E5F6F3")):
        for x, lab in zip(xs, labels):
            e.append(rect(x, row_y, 120, 56, stroke, fill=fill, width=1.5, rx=6))
            e.append(t(x + 60, row_y + 36, f"{lab} {ver}", 16, 600, fill=stroke, anchor="middle"))
    e.append(t(888, 424, "이미지 3종(200mb, 1gb, 2gb)과 탄력 메모리용 mem", 16, fill=SOFT, anchor="middle"))
    # Client -> runtimes
    e.append(arrow([(288, 248), (584, 248)]))
    e.append(t(480, 212, "InvokeAgentRuntime", 16, fill=MUTED, anchor="middle"))
    e.append(t(480, 236, "StopRuntimeSession", 16, fill=MUTED, anchor="middle"))
    e.append(t(480, 276, "같은 리전 왕복", 16, fill=SOFT, anchor="middle"))
    e.append(t(480, 300, "TCP+TLS 4.3~5.2 ms", 16, fill=SOFT, anchor="middle"))
    # CloudWatch (bottom left)
    e.append(icon("service/Amazon-CloudWatch", 204, 480, 56))
    e.append(t(232, 560, "Amazon CloudWatch", 20, 600, anchor="middle"))
    e.append(t(232, 584, "AWS/Bedrock-AgentCore 지표", 16, fill=MUTED, anchor="middle"))
    e.append(arrow([(232, 472), (232, 408)]))
    e.append(t(244, 444, "지표 조회", 16, fill=MUTED))
    e.append(arrow([(640, 448), (640, 508), (268, 508)]))
    e.append(t(456, 496, "지표 발행", 16, fill=MUTED, anchor="middle"))
    e.append(t(456, 532, "사용량, OverheadLatency", 16, fill=MUTED, anchor="middle"))
    # ECR (bottom right)
    e.append(icon("service/Amazon-Elastic-Container-Registry", 1000, 484, 56))
    e.append(t(1028, 560, "Amazon ECR", 20, 600, anchor="middle"))
    e.append(t(1028, 584, "이미지 태그 4개, arm64", 16, fill=MUTED, anchor="middle"))
    e.append(arrow([(1028, 476), (1028, 452)]))
    e.append(t(1012, 472, "컨테이너 이미지", 16, fill=MUTED, anchor="end"))
    # Legend
    e.append(t(40, 680, "범례", 16, 600, fill=MUTED))
    e.append(rect(112, 664, 40, 24, INK, fill="#FFFFFF", width=1.5, rx=4))
    e.append(t(164, 680, "V1 런타임 (platformVersion=V1)", 16, fill=MUTED))
    e.append(rect(460, 664, 40, 24, TEAL, fill="#E5F6F3", width=1.5, rx=4))
    e.append(t(512, 680, "V2 런타임 (platformVersion=V2 명시)", 16, fill=MUTED))

    defs = (f'<defs><marker id="arrow-ink" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
            f'<polygon points="0 0, 10 4, 0 8" fill="{INK}"/></marker></defs>')
    body = "\n".join(e)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720" '
            f'role="img" aria-labelledby="fig02-title fig02-desc" font-family="{SANS}">\n'
            f'<title id="fig02-title">{TITLE}</title>\n<desc id="fig02-desc">{DESC}</desc>\n{defs}\n'
            f'<rect x="0" y="0" width="1280" height="720" fill="#FFFFFF"/>\n{body}\n</svg>\n')


def main():
    os.makedirs(OUT, exist_ok=True)
    draft = os.path.join(HERE, f"{NAME}.draft.svg")
    final = os.path.join(OUT, f"{NAME}.svg")
    with open(draft, "w", encoding="utf-8") as f:
        f.write(build())
    subprocess.run([sys.executable, os.path.join(SKILL, "scripts", "embed.py"), draft, final], check=True)
    svg = open(final, encoding="utf-8").read()
    if svg.startswith("<?xml"):
        svg = svg.split("?>", 1)[1].lstrip()
    html = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{TITLE}</title>
<style>
@font-face{{font-family:'Amazon Ember';font-weight:400;src:local('Amazon Ember'),local('AmazonEmber-Regular');}}
@font-face{{font-family:'Amazon Ember';font-weight:600;src:local('Amazon Ember Medium'),local('Amazon Ember SemiBold'),local('Amazon Ember Bold');}}
@font-face{{font-family:'Amazon Ember';font-weight:700;src:local('Amazon Ember Bold');}}
@font-face{{font-family:'Amazon Ember Mono';font-weight:400;src:local('Amazon Ember Mono'),local('AmazonEmberMono-Regular');}}
html,body{{margin:0;background:#fff;}} svg{{display:block;width:1280px;height:720px;}}
</style></head><body>{svg}</body></html>
'''
    with open(os.path.join(OUT, f"{NAME}.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("OK fig02")


if __name__ == "__main__":
    main()

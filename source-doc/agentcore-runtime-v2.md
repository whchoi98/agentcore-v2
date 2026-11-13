---
title: "이미지 크기와 무관한 2초 cold start – 새로운 Amazon Bedrock AgentCore Runtime(플랫폼 버전 V2) 소개와 실측"
date: 2026-09-20
author: "Woohyung Choi"
status: draft
---

# 이미지 크기와 무관한 2초 cold start – 새로운 Amazon Bedrock AgentCore Runtime(플랫폼 버전 V2) 소개와 실측

by WOO HYUNG CHOI on 20 9월 2026 in [Advanced (300)](https://aws.amazon.com/ko/blogs/tech/category/learning-levels/advanced-300/), [Amazon Bedrock](https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/amazon-machine-learning/amazon-bedrock/), [Amazon Bedrock AgentCore](https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/amazon-machine-learning/amazon-bedrock/amazon-bedrock-agentcore/), [Best Practices](https://aws.amazon.com/ko/blogs/tech/category/post-types/best-practices/)

에이전트 컨테이너 이미지가 1 GB를 넘으면 새 세션의 첫 응답이 10초 이상 걸리지는 않으신가요? 세션이 모델 응답을 기다리며 유휴 상태로 있는 동안에도 최고점 메모리를 그대로 과금받고 있지는 않으신가요? 2026년 9월 18일 AWS는 Amazon Bedrock AgentCore의 서버리스 microVM 컴퓨트인 AgentCore Runtime의 다음 세대를 발표했습니다. 새로운 런타임은 플랫폼 버전(platformVersion) V2로 제공되며 두 가지를 약속합니다. 컨테이너 이미지 크기와 동시성에 무관한 일관된 cold start, 그리고 세션 중 해제된 메모리를 회수하는 탄력 메모리(Elastic memory)입니다.

이 글은 두 약속이 실제 계정에서 재현되는지 같은 에이전트를 V1과 V2에 나란히 배포해 측정한 결과를 소개합니다. 측정은 2026년 9월 19일 도쿄 리전(ap-northeast-1)에서 진행했습니다. 단가는 2026년 9월 20일 기준 요금 페이지의 공개 단가입니다. 이 글은 AgentCore Runtime에 에이전트를 배포하고 운영하는 개발자와 아키텍트를 대상으로 하며, 세션(runtimeSessionId)마다 microVM이 하나씩 배정된다는 기본 동작을 알고 있다면 무리 없이 읽을 수 있습니다.

## 1. 새로운 AgentCore Runtime이 바꾼 것

### 1.1 스냅샷에서 시작하는 세션

V1에서 새 세션은 매번 처음부터 시작합니다. 컨테이너 이미지를 가져와 풀고 프로세스를 띄우고 의존성을 import하고 초기화 코드를 실행한 뒤에야 첫 요청을 처리합니다. 이미지가 클수록 이 경로가 길어지므로 cold start는 이미지 크기에 비례해 늘어납니다.

V2는 이 경로를 한 번만 밟습니다. 런타임을 생성하거나 업데이트할 때 AgentCore Runtime이 컨테이너를 띄우고 `/ping`이 정상 응답을 낼 때까지 기다린 뒤, 실행 중인 환경 전체의 스냅샷을 촬영합니다. 이후 모든 새 세션은 이 스냅샷을 복원해 시작합니다. 시작 시점의 초기화가 이미 끝난 상태에서 출발하므로 시작 시간이 이미지 크기와 무관해집니다. 동시에 많은 세션이 몰려도 각 세션이 같은 스냅샷을 복원하기만 하면 되므로 동시성에도 영향을 받지 않습니다.

![V1은 세션마다 이미지 pull, 프로세스 기동, 초기화를 반복해 이미지 크기에 비례한 cold start가 생기고, V2는 런타임 생성 시 한 번 초기화한 환경의 스냅샷을 촬영해 모든 세션이 이를 복원하므로 약 2초의 일정한 cold start를 냅니다.](images/agentcore-runtime-v2-fig01-start-path.png)

*그림 1. V1과 V2의 세션 시작 경로. V1은 세션마다 전체 시작 절차를 반복하고, V2는 생성 시 한 번 만든 스냅샷을 세션마다 복원합니다.*

발표 블로그는 사내 측정에서 200 MB부터 2 GB 이미지까지 p75 cold start가 약 2초로 일정했다고 밝혔습니다. V1은 같은 구간에서 약 5.4초에서 30초 가까이 늘었습니다. 이 글의 실측은 이 수치를 다른 리전, 다른 계정에서 다시 확인하는 데서 출발합니다.

### 1.2 필요한 만큼만 잡는 탄력 메모리

V1은 세션이 한 번 확보한 메모리를 세션이 끝날 때까지 유지합니다. 문서 분석 도구가 잠깐 1.5 GB를 사용하고 해제해도 과금 기준은 그 최고점(high watermark)을 따라갑니다. V2는 세션을 작은 메모리 프로필로 시작하고 필요할 때 추가로 할당하며 더 이상 활발히 사용하지 않는 메모리는 회수합니다. 요금 페이지에 따르면 유휴 메모리는 V2에서 120초 뒤 자동으로 회수됩니다. 에이전트 워크로드는 모델 응답과 도구 호출을 기다리는 시간이 대부분이므로 이 차이는 과금 GB-hours에 직접 반영됩니다.

### 1.3 플랫폼 버전, 리전, 단가

플랫폼 버전은 런타임 단위로 지정합니다. 생성이나 업데이트 시 `platformVersion`을 `V2`로 주면 됩니다. 생략하면 생성 시에는 V1이 적용되고 업데이트 시에는 기존 값이 유지됩니다.

```bash
aws bedrock-agentcore-control create-agent-runtime \
  --agent-runtime-name "my_agent" \
  --role-arn "arn:aws:iam::111122223333:role/AgentExecutionRole" \
  --agent-runtime-artifact '{"containerConfiguration": {"containerUri": "111122223333.dkr.ecr.ap-northeast-1.amazonaws.com/my-agent:latest"}}' \
  --network-configuration '{"networkMode": "PUBLIC"}' \
  --platform-version V2

aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id my_agent-ABCDE12345 --query platformVersion
```

생성 응답은 `platformVersion`을 돌려주지 않으므로 두 번째 명령처럼 `get-agent-runtime`으로 적용된 버전을 확인합니다.

V2는 발표 시점에 us-east-1, us-east-2, us-west-2, eu-west-1, ap-northeast-1 다섯 리전에서 제공됩니다. 서울 리전(ap-northeast-2)은 아직 포함되지 않아 이 글의 측정은 도쿄 리전에서 진행했습니다.

단가는 V2가 더 높습니다. 요금 페이지에는 소비 기준(consumption) 단가와 함께 2026년 10월까지 출시 예정인 약정 기준(committed baseline) 단가도 실려 있습니다. 이 글의 계산은 현재 적용되는 소비 기준 단가만 사용합니다.

| 항목 | V1 | V2 (소비 기준) | V2 증가율 |
|---|---|---|---|
| vCPU-hour | 0.0895 USD | 0.1276 USD | +42.6% |
| GB-hour | 0.00945 USD | 0.0169 USD | +78.8% |

*표 1. AgentCore Runtime microVM 단가 (USD, 세전, 2026년 9월 20일 요금 페이지 기준). 초 단위로 계량되며 최소 1초, 메모리 최소 과금 128 MB입니다.*

단가가 올랐는데 총비용이 내려갈 수 있는지가 이 글의 두 번째 질문입니다. 답은 계량되는 단위 수에 달려 있습니다.

## 2. 실측 방법

### 2.1 측정 대상과 이미지 3종

측정 대상은 모델을 호출하지 않는 FastAPI echo 에이전트입니다. 무거운 의존성도 없으므로 측정값은 애플리케이션 작업이 아니라 플랫폼의 시작 경로를 반영합니다. 핸들러 자체의 처리 시간은 p75 0.1 ms로 전체 지연에서 무시할 수 있습니다.

같은 에이전트에 `/dev/urandom` 패딩을 더해 이미지 3종을 만들었습니다. `/dev/zero`를 사용하지 않은 이유는 Amazon ECR이 레이어를 gzip으로 압축 저장하므로 0으로 채운 패딩은 압축되어 사라지고 크기별 pull 비용을 측정하는 의미가 없어지기 때문입니다. 패딩 값은 AWS 샘플(agentcore-samples의 measure-your-runtime)과 같은 매핑을 사용해 공개 수치와 비교할 수 있게 했습니다.

| 라벨 | 패딩(MB) | ECR 압축 크기 | 비압축 추정 |
|---|---|---|---|
| 200mb | 0 | 45.4 MiB | 약 230 MB |
| 1gb | 797 | 842.6 MiB | 약 1,027 MB |
| 2gb | 1,821 | 1,866.9 MiB | 약 2,051 MB |

*표 2. 측정에 사용한 컨테이너 이미지 (linux/arm64, python:3.13-slim 기반). 압축 크기는 ECR DescribeImages 값이며 MiB = 2^20 바이트입니다.*

![서울 리전 EC2 벤치마크 클라이언트가 도쿄 리전의 AgentCore Runtime 6개(이미지 3종 × V1, V2)를 InvokeAgentRuntime으로 호출하고, 런타임은 같은 ECR 이미지를 참조하며, 과금 사용량은 CloudWatch의 AWS/Bedrock-AgentCore 지표로 수집합니다.](images/agentcore-runtime-v2-fig02-bench-setup.png)

*그림 2. 측정 구성. 클라이언트와 런타임이 다른 리전에 있으므로 모든 지연 수치에 리전 간 왕복이 포함됩니다.*

### 2.2 스냅샷 복원을 증명하는 진단 필드

V2가 정말 스냅샷에서 복원되는지 확인하기 위해 에이전트는 import 시점, 즉 스냅샷 촬영 전에 값을 만들어 응답에 실어 보냅니다. `boot_id`는 import 시 `os.urandom()`으로 만든 난수입니다. V1은 세션마다 새 프로세스이므로 매번 다릅니다. V2는 모든 인스턴스가 같은 스냅샷을 복원하므로 같아야 합니다. `uptime_mono_s`는 `time.monotonic()` 기준 경과 시간으로, 복원을 넘어 전진하지 않으므로 V2에서는 스냅샷 촬영 시점 값에 고정됩니다. `uptime_wall_s`는 `time.time()` 기준이라 흐르므로 V2에서는 인스턴스의 나이가 아니라 스냅샷의 나이를 나타냅니다.

요청마다 달라야 하는 `req_id`와 `served_at`은 핸들러 안에서 생성했습니다. V2 최적화 가이드가 요구하는 방식이며 시작 시점에 만든 값은 스냅샷에 얼어붙어 모든 인스턴스에서 반복되기 때문입니다.

### 2.3 세션 처리와 네트워크 기준선

모든 cold start 측정은 새 `runtimeSessionId`로 1회 호출한 뒤 즉시 `StopRuntimeSession`을 호출합니다. AgentCore Runtime은 세션 수명 전체를 과금하고 벤치마크 세션은 그 대부분을 유휴로 보내므로 방치하면 측정 목적과 무관한 비용이 대부분을 차지합니다. `idleRuntimeSessionTimeout`과 `maxLifetime`은 API 최소값인 60초로 설정했습니다.

클라이언트는 서울 리전 EC2 r8g.4xlarge(aarch64, Python 3.12, boto3 1.43.98)이고 런타임은 도쿄 리전이므로 모든 수치에 같은 리전 간 왕복이 포함됩니다. 측정 시점 중위값은 TCP 핸드셰이크 34.5 ms, TCP와 TLS 합산 69.9 ms였습니다. 절대값을 읽을 때 이만큼은 플랫폼이 아니라 경로 비용입니다.

## 3. Cold start는 이미지 크기와 동시성에 무관한가

### 3.1 새 세션 30개, 동시성 5

런타임마다 새 세션 30개를 동시성 5로 호출했습니다. 모든 호출이 cold start입니다.

| 이미지 | V1 p75 | V2 p75 | V1 ÷ V2 |
|---|---|---|---|
| 200mb | 5.47초 | 1.97초 | 2.8배 |
| 1gb | 13.48초 | 2.10초 | 6.4배 |
| 2gb | 27.70초 | 1.98초 | 14.0배 |

*표 3. cold start p75 (런타임당 새 세션 30개, 동시성 5, 리전 간 왕복 포함).*

![이미지 크기 200 MB, 1 GB, 2 GB에 대한 cold start p75 막대 비교. V1은 5.47초, 13.48초, 27.70초로 이미지 크기에 비례해 증가하고, V2는 1.97초, 2.10초, 1.98초로 약 2초 밴드에 머뭅니다.](images/agentcore-runtime-v2-fig03-cold-start-p75.png)

*그림 3. 이미지 크기별 cold start p75. V1은 크기에 비례해 늘고 V2는 1.9초에서 2.1초 밴드 안에 머뭅니다.*

핵심은 개별 수치가 아니라 모양입니다. V1의 cold start는 이미지 크기에 비례해 커집니다. V2는 200 MB부터 2 GB까지 1.9초에서 2.1초 사이에 머뭅니다. AWS가 공개한 수치(V1 5.4초에서 30초, V2 약 2초)와 거의 일치합니다. 일관성을 숫자로 보면 변동계수(CV)가 V2는 0.099에서 0.116으로 이미지 크기와 무관하게 일정하고, V1은 0.685에서 1.226입니다. V2가 6배에서 12배 안정적입니다.

| 이미지 | 버전 | p50 (ms) | p75 (ms) | p99 (ms) | CV | 성공 | `boot_id` 개수 | `uptime_mono_s` | `uptime_wall_s` |
|---|---|---|---|---|---|---|---|---|---|
| 200mb | V1 | 762 | 5,467 | 5,537 | 0.807 | 30/30 | 30 | 3.1 | 7.9 |
| 200mb | V2 | 1,910 | 1,972 | 2,771 | 0.116 | 30/30 | 2 | 68.9 | 2,662 |
| 1gb | V1 | 677 | 13,478 | 15,687 | 1.226 | 30/30 | 30 | 3.7 | 16.7 |
| 1gb | V2 | 1,940 | 2,101 | 2,420 | 0.099 | 30/30 | 1 | 69.3 | 2,506 |
| 2gb | V1 | 27,622 | 27,705 | 29,724 | 0.685 | 30/30 | 30 | 0.7 | 0.7 |
| 2gb | V2 | 1,935 | 1,984 | 2,568 | 0.106 | 30/30 | 1 | 68.4 | 2,416 |

*표 4. cold start 분포와 스냅샷 증거 (동일 30세션). CV는 변동계수(표준편차 ÷ 평균), `uptime_mono_s`와 `uptime_wall_s`는 세션별 값의 중위값(초)이며, throttle은 전 구간 0건입니다.*

이 표는 세 가지를 말합니다.

첫째, V1의 p50과 p75가 크게 벌어집니다. 200 MB에서 p50은 762 ms인데 p75는 5,467 ms입니다. 분포가 이봉형(bimodal)이라는 뜻이고 원인은 사전 초기화된 환경입니다. 발표 블로그도 이미 초기화된 환경에 착륙한 세션은 100 ms 안에 시작한다고 밝히고 있습니다. 초기 몇 건은 그 여유 용량을 흡수하고 소진되면 진짜 cold start가 나타납니다. 2 GB에서는 p50조차 27.6초인데, 여유 용량이 즉시 고갈되기 때문입니다. 빠른 군집의 중위값은 567 ms에서 659 ms로 이미지 크기와 무관합니다. V1에서 이미지 크기가 만드는 페널티는 전적으로 이미지 전송과 전개 비용이며 프로세스 시작 비용이 아닙니다. 실무적으로 중요한 함정이 여기 있습니다. 적은 표본으로 V1을 측정하면 실제보다 훨씬 빠르게 나옵니다. 처음 3회만 순차 실행했을 때 V1 200 MB는 638 ms로 측정됐습니다. 같은 런타임을 30세션으로 압박하자 5,467 ms가 됐습니다. V1 벤치마크는 여유 용량을 소진시켜야 의미가 있습니다. V2의 실질적 이점도 여기서 드러납니다. V1의 빠른 군집 567 ms는 V2의 1,910 ms보다 빠르지만, V2에는 이봉성이 없어 최악값이 예측 가능합니다.

둘째, `boot_id`가 스냅샷을 증명합니다. V1은 30세션에서 서로 다른 `boot_id` 30개가 나왔습니다. 프로세스가 30번 새로 시작했다는 뜻입니다. V2는 30세션에서 1개에서 2개만 나왔습니다. 모든 인스턴스가 같은 준비된 환경을 복원했습니다.

셋째, V2의 두 시계가 갈라집니다. `uptime_mono_s`는 68초에서 69초에 고정되고 `uptime_wall_s`는 2,400초에서 2,700초입니다. 스냅샷은 부팅 후 약 69초 지점에서 촬영됐습니다. 측정 시점에 그 스냅샷은 약 40분 된 상태였습니다. monotonic 시계는 복원을 넘어 전진하지 않는다는 문서 설명이 그대로 관측됩니다. 시작 시점 기준으로 경과 시간을 재는 코드가 V2에서 조용히 틀리는 이유이기도 합니다. 반대편 확인도 통과했습니다. cold와 burst를 합쳐 V2에서 처리한 240개 요청의 `req_id`는 전부 서로 달랐습니다. 핸들러에서 `os.urandom()`으로 만든 값은 복원 후에도 정상적으로 새 엔트로피를 받습니다. 문제가 되는 것은 시작 시점에 읽은 난수뿐입니다.

### 3.2 동시 세션 50개

동시성과 무관하다는 주장을 직접 시험하기 위해 런타임마다 새 세션 50개를 한꺼번에 호출했습니다.

| 이미지 | V1 p75 | V2 p75 | V1 ÷ V2 |
|---|---|---|---|
| 200mb | 5.58초 | 2.05초 | 2.7배 |
| 1gb | 13.63초 | 1.98초 | 6.9배 |
| 2gb | 27.74초 | 2.03초 | 13.7배 |

*표 5. 동시 cold start p75 (런타임당 새 세션 50개 동시 호출). 150건 시도 중 throttle 0건, 실패 0건입니다.*

양쪽 모두 동시성 5일 때와 사실상 같습니다. 다른 점은 V1의 p50이 5,549 ms로 올라간 것뿐입니다. 50건이 동시에 도착하면 여유 용량이 즉시 고갈되어 이봉 분포의 빠른 쪽이 사라지기 때문입니다. V2의 p50은 1,864 ms에서 1,887 ms로 저압 측정과 차이가 없습니다. 동시성 5와 50의 p50과 p75를 나란히 놓으면 V2의 변화는 전 구간 ±6% 안입니다. 동시성이 10배 늘어도 실질적 차이가 없습니다.

동시 50세션에서는 세 이미지 모두 빠른 군집이 정확히 10건이었습니다. 런타임당 사전 초기화 환경이 약 10개 유지된다는 해석이 자연스럽지만, 관측에서 추론한 값이며 문서화된 값이 아니므로 설계 근거로 삼지 않는 것을 권고합니다.

### 3.3 V1의 진짜 cold start는 이미지 크기에 선형

느린 군집만 따로 보면 V1의 cold start는 압축 이미지 크기에 거의 완전한 선형입니다. 표본이 더 많은 동시 50세션 측정의 느린 군집 중위값(5,565 ms, 13,605 ms, 27,691 ms)을 ECR 압축 크기에 최소제곱 회귀하면 다음 식이 나옵니다.

```
V1 cold start(ms) ≈ 4,397 + 12.22 × 압축 이미지 크기(MiB)      R² = 0.993
```

절편 4.4초는 이미지와 무관한 microVM 부팅과 초기화 비용, 기울기 12.22 ms/MiB는 이미지 전송과 전개 비용으로 읽힙니다. V1에서 이미지를 100 MiB 줄이면 cold start가 약 1.2초 줄어드는 셈입니다. V2에서는 스냅샷 복원 시간이 이미지 크기에 거의 반응하지 않으므로 이 최적화의 효과가 사라집니다. 세 점으로 구한 회귀이므로 방향성 참고로 볼 것을 권고합니다.

### 3.4 AWS 공개 수치와의 비교

AWS 샘플은 us-east-1에서 컨테이너 5종 크기와 zip 배포를 에이전트당 5,000세션으로 측정했습니다. 이 글은 ap-northeast-1에서 컨테이너 3종을 런타임당 30세션으로 측정했습니다.

| 이미지 | AWS V1 p75 | 이 글 V1 p75 | AWS V2 p75 | 이 글 V2 p75 |
|---|---|---|---|---|
| 200mb | 5.37초 | 5.47초 | 1.94초 | 1.97초 |
| 1gb | 15.48초 | 13.48초 | 2.13초 | 2.10초 |
| 2gb | 29.72초 | 27.70초 | 2.16초 | 1.98초 |

*표 6. AWS 샘플(us-east-1, 에이전트당 5,000세션, 2026년 9월)과 이 글(ap-northeast-1, 런타임당 30세션)의 cold start p75 비교.*

V1은 -13%에서 +2%, V2는 -8%에서 +2% 범위에서 일치합니다. 리전, 계정, 표본 수가 다른데도 이 정도로 맞는 것은 두 측정 모두 플랫폼의 시작 경로를 재고 있다는 뜻입니다.

## 4. Warm 지연과 세션 재사용

한 세션을 유지하며 30회 순차 호출했습니다. 이 표의 첫 열에는 V1의 함정이 다시 보입니다. 런타임당 세션이 하나뿐이라 V1이 전부 사전 초기화 환경에 착륙해 547 ms에서 840 ms가 나옵니다. 같은 런타임의 진짜 cold start는 5.5초에서 27.7초입니다.

| 이미지 | 버전 | 첫 호출(cold) | warm p50 | warm p75 | warm p99 |
|---|---|---|---|---|---|
| 200mb | V1 | 547 ms | 186 ms | 203 ms | 229 ms |
| 200mb | V2 | 1,960 ms | 196 ms | 212 ms | 266 ms |
| 1gb | V1 | 840 ms | 165 ms | 189 ms | 224 ms |
| 1gb | V2 | 2,021 ms | 200 ms | 217 ms | 240 ms |
| 2gb | V1 | 549 ms | 171 ms | 188 ms | 211 ms |
| 2gb | V2 | 1,979 ms | 195 ms | 205 ms | 240 ms |

*표 7. 세션 재사용 시 지연 (세션 1개, cold 1회 + warm 30회, 리전 간 왕복 포함).*

warm 경로에서 V1과 V2는 같습니다. 차이는 20 ms에서 30 ms 수준으로 리전 간 왕복 변동과 같은 크기입니다. 핸들러는 양쪽 모두 0.1 ms입니다. V2는 정상 요청 처리에 불이익이 없고 차이는 전부 시작 경로에서 발생합니다. warm 205 ms 대 cold 1,980 ms라는 비율은 세션 재사용이 여전히 가장 큰 지연 해법이라는 사실도 보여줍니다. cold start는 재사용이 불가능할 때 내는 값입니다. 발표 블로그의 실무 팁도 같은 방향입니다. 사용자가 채팅 화면을 여는 순간, 입력하기 전에 세션을 시작해 두면 첫 메시지를 입력하는 동안 환경이 준비되어 시작 시간이 사실상 감춰집니다.

## 5. 단가는 올랐는데 총비용은 내려가는가

과금 사용량은 CloudWatch `AWS/Bedrock-AgentCore` 네임스페이스의 `MemoryUsed-GBHours`와 `CPUUsed-vCPUHours` 지표로 조회했습니다. 차원은 `Resource`(런타임 ARN)와 `Service`(`AgentCore.Runtime`)입니다. 문서에 따르면 이 지표는 최대 60분 지연될 수 있어 측정 종료 후 충분히 기다린 뒤 수집했습니다. 앞의 세 시나리오를 합쳐 런타임당 81세션이며 V1과 V2에 완전히 동일한 워크로드입니다.

```
세션당 비용(USD) = GB-hours ÷ 세션 수 × GB-hour 단가 + vCPU-hours ÷ 세션 수 × vCPU-hour 단가
추정 footprint(GB) = GB-hours ÷ 관측 세션-시간
```

| 이미지 | 버전 | 세션 | GB-hours | vCPU-hours | 추정 footprint | 비용 |
|---|---|---|---|---|---|---|
| 200mb | V1 | 81 | 0.1449 | 0.1152 | 1.60 GB | 0.0117 USD |
| 200mb | V2 | 81 | 0.0863 | 0.0578 | 1.93 GB | 0.0088 USD |
| 1gb | V1 | 81 | 1.0025 | 0.3856 | 5.06 GB | 0.0440 USD |
| 1gb | V2 | 81 | 0.0857 | 0.0563 | 1.90 GB | 0.0086 USD |
| 2gb | V1 | 81 | 2.7899 | 0.7391 | 5.95 GB | 0.0925 USD |
| 2gb | V2 | 81 | 0.0867 | 0.0563 | 1.93 GB | 0.0086 USD |

*표 8. 동일 워크로드(cold 30 + burst 50 + warm 1세션)의 과금 사용량과 비용 추정치 (USD, 세전, 소수 넷째 자리, 표 1 단가 적용). footprint는 GB-hours를 클라이언트가 관측한 세션-시간으로 나눈 참고값입니다.*

2 GB 이미지에서 V2는 GB-hour 단가가 78.8% 높은데도 GB-hours가 32배 적어 총비용이 10.8배 낮습니다. V2의 GB-hours는 이미지 크기와 무관하게 0.086에서 0.087로 평탄합니다. V1은 200 MB에서 2 GB로 가며 19배 늘어납니다. 컨테이너 전체를 세션 내내 메모리에 상주시키는 대신 필요한 부분만 로드한다는 설명과 일치합니다. vCPU-hours도 같은 방향입니다. V2는 0.056에서 0.058로 평탄하고 V1은 200 MB에서 2 GB로 가며 6.4배 늘어납니다. 느린 cold start는 지연 문제만이 아니라 CPU 과금 문제이기도 합니다. microVM 부팅과 이미지 전개 중에 사용한 CPU도 요청 처리 CPU와 같은 단가로 과금됩니다.

주의할 점이 두 가지 있습니다. footprint 열은 V1과 V2의 세션 수명이 다르다는 점을 감안해서 읽어야 합니다. V1 2 GB 세션은 cold start 자체가 30초라 그만큼 오래 살았습니다. 이 워크로드에서 V1은 메모리를 더 많이 잡고 그 상태를 더 오래 유지하는 두 효과가 함께 작용합니다. 순수 footprint 비교는 세션 수명을 맞춘 탄력 메모리 측정에서 따로 다룹니다. 그리고 200 MB에서는 V2 우위가 좁습니다. footprint만 보면 V2(1.93 GB)가 V1(1.60 GB)보다 오히려 큽니다. 로드할 이미지가 작으면 온디맨드 로딩으로 아낄 것이 없고 단가 인상만 남습니다. 이 구간에서 V2가 그래도 싼 이유는 세션이 짧게 끝나서입니다. 에이전트가 실제로 건드리지 않는 이미지 부분이 많을수록 V2가 유리합니다.

세션 수가 같으므로 세션당으로 정규화하면 규모에 무관한 비교가 됩니다.

| 이미지 | V1 1,000세션 | V2 1,000세션 | V2 절감률 |
|---|---|---|---|
| 200mb | 0.144 USD | 0.109 USD | 24% |
| 1gb | 0.543 USD | 0.107 USD | 80% |
| 2gb | 1.142 USD | 0.107 USD | 91% |

*표 9. 측정한 세션당 사용량으로 정규화한 1,000세션당 비용 추정치 (USD, 세전, 소수 셋째 자리, 표 1 단가 적용). 측정과 같은 세션 수명 가정(세션당 호출 1회 후 즉시 종료)을 유지한 두 버전 간 비교이며 실제 청구서 예측이 아닙니다.*

작은 이미지에서는 절감이 24%에 그칩니다. 이미지가 없는 직접 코드(zip) 배포는 온디맨드 로딩으로 아낄 것이 없어 V2에 가장 불리한 조건에 가깝습니다. AWS 샘플의 zip 측정에서도 cold start 격차는 V1 2.85초 대 V2 1.96초로 컨테이너보다 훨씬 좁습니다.

cold, burst, warm 486세션의 실험 비용은 0.17 USD였고, 탄력 메모리 측정의 메모리 과금은 0.01 USD 미만이었습니다.

## 6. 해제한 메모리를 정말 회수하는가

앞의 시나리오는 이 질문에 답하지 못합니다. echo 에이전트는 메모리를 할당하지 않습니다. 그래서 별도 런타임 한 쌍을 만들고 세션 모양을 맞췄습니다. 호출 1회에서 1,536 MB를 할당하고 모든 페이지에 실제로 값을 써서 상주시킨 뒤 해제하고 응답합니다. 이어서 클라이언트가 90초간 세션을 유휴로 유지하고 정지시킵니다. 대조군은 할당 없이 같은 세션 모양과 같은 유휴 시간을 반복해, 스파이크 자체의 기여분을 기준선 세션 비용과 분리합니다. 레그마다 150초 정적 구간을 두어 CloudWatch 분 버킷이 섞이지 않게 했습니다.

에이전트가 보고한 프로세스 RSS는 50.8 MB에서 1,593.8 MB로 올랐다가 52.9 MB로 돌아왔습니다. 할당도 해제도 실제였습니다. 플랫폼이 과금한 값은 아래와 같이 나타났습니다.

| 레그 | 버전 | 세션 | 세션-시간 | GB-hours | 추정 footprint |
|---|---|---|---|---|---|
| 1,536 MB 할당 후 해제 | V1 | 4 | 0.1043 | 0.3802 | 3.64 GB |
| 대조군 (할당 없음) | V1 | 4 | 0.1008 | 0.1702 | 1.69 GB |
| 1,536 MB 할당 후 해제 | V2 | 4 | 0.1054 | 0.1339 | 1.27 GB |
| 대조군 (할당 없음) | V2 | 4 | 0.1026 | 0.1144 | 1.11 GB |

*표 10. 탄력 메모리 측정의 레그별 과금 사용량 (레그당 4세션, 각 세션은 호출 1회 + 유휴 90초). 세션-시간 단위는 시간(h)입니다.*

| 버전 | 대조군 footprint | 스파이크 후 footprint | 스파이크 기여분 | GB-hours 비율 |
|---|---|---|---|---|
| V1 | 1.69 GB | 3.64 GB | +1.95 GB | 2.23배 |
| V2 | 1.11 GB | 1.27 GB | +0.16 GB | 1.17배 |

*표 11. 해제된 1.5 GB 스파이크가 세션 과금 footprint에 남기는 양. 세션-시간을 0.10 h 수준으로 맞췼으므로 수명이 아니라 footprint 차이입니다.*

![V1과 V2의 대조군 대비 스파이크 후 과금 footprint 막대. V1은 1.69 GB에서 3.64 GB로 1.95 GB가 남고, V2는 1.11 GB에서 1.27 GB로 0.16 GB만 남아 해제한 메모리의 약 92%가 회수됩니다.](images/agentcore-runtime-v2-fig04-elastic-memory.png)

*그림 4. 1.5 GB를 할당 후 해제한 세션의 과금 footprint. 두 버전 모두 대조군과 세션 수명을 맞춘 비교입니다.*

V1은 1.5 GB 스파이크가 해제된 뒤에도 세션이 끝날 때까지 과금 footprint에 1.95 GB로 남습니다. V2는 0.16 GB만 남아 해제된 메모리의 약 92%를 회수했습니다. 분당 시계열에서도 같은 모양이 보입니다. V1의 할당 레그는 두 번째 분에 GB-hours가 0.2262로 올라가는데, 스파이크가 해제된 뒤의 유휴 구간에서도 과금이 이어지고 있다는 뜻입니다. V2의 할당 레그와 대조군은 분당 값이 사실상 구분되지 않습니다. V2의 대조군 footprint 1.11 GB는 AWS 샘플이 5,000세션 측정에서 보고한 약 1.2 GB 평탄값과 일치합니다.

덧붙여 관찰된 점으로, 할당 작업 자체는 V2가 더 빨랐습니다. 대조군 중위값과 2초 hold를 빼면 1,536 MB 할당과 페이지 쓰기에 V1은 약 1.1초, V2는 약 0.5초를 사용했습니다. 표본이 레그당 4세션이므로 방향성 참고 수준으로만 볼 것을 권고합니다.

## 7. 배포 시간, V2가 내는 비용

| 런타임 | platformVersion | API 호출 | READY 도달 |
|---|---|---|---|
| 200mb | V1 | 0.93초 | 3.30초 |
| 200mb | V2 | 0.73초 | 185.68초 |
| 1gb | V1 | 0.85초 | 3.27초 |
| 1gb | V2 | 0.70초 | 200.92초 |
| 2gb | V1 | 0.75초 | 3.34초 |
| 2gb | V2 | 0.75초 | 216.59초 |

*표 12. 런타임 생성 API 호출 시간과 READY 상태 도달 시간 (get_agent_runtime 3초 간격 폴링).*

V2가 명확히 불리한 항목은 배포 시간 하나입니다. 컨테이너를 띄우고 첫 정상 `/ping`을 기다린 뒤 스냅샷을 떠야 하므로 V1보다 56배에서 65배 오래 걸리고 이미지 크기에 따라 소폭 늘어납니다. 런타임 수명 전체로 보면 한 번만 내는 비용이지만 CI 파이프라인이 배포마다 3분 이상 기다려야 한다는 뜻입니다.

운영에서 걸리는 지점도 함께 확인했습니다. `create`와 `update`는 `CREATING`이나 `UPDATING` 상태에서 즉시 반환합니다. 터미널 상태가 되기 전에 `update`나 `delete`를 호출하면 `ConflictException`이 발생하므로 `get_agent_runtime`을 폴링해야 합니다. 컨테이너는 시작 후 120초 안에 정상 응답해야 하고 초과하면 헬스 체크 오류로 생성이 실패합니다. 환경 변수 총량 제한은 V1의 4 KB보다 작아 컨테이너 2.5 KB, 직접 코드 배포 1.5 KB이며 초과 시 `ValidationException`이 발생합니다. 문서는 이 한도를 V1 수준으로 올릴 예정이라고 밝혔습니다. AWS CloudFormation과 AWS CDK는 아직 `platformVersion`을 지원하지 않아 AWS CLI나 SDK로만 설정할 수 있습니다. 측정 당시 로컬 AWS CLI(botocore 1.42.86)에는 `--platform-version` 옵션이 없어 별도 가상 환경에 boto3 1.43.98을 설치해 SDK로 호출했습니다. 사용 중인 CLI와 SDK 버전을 먼저 확인하는 것을 권고합니다.

V2 스냅샷은 직접 삭제하지 않습니다. 런타임이나 엔드포인트를 지우면 참조가 끊기고 이미 실행 중인 세션이 끝난 뒤 제거됩니다. 세션 최대 수명인 8시간까지 걸릴 수 있습니다.

## 8. V2로 옮길 때 코드에서 챙길 것

스냅샷 복원은 실행 모델을 바꾸므로 코드 구조에 영향을 줍니다. V2 최적화 가이드의 원칙은 하나입니다. 스냅샷 수명 동안 같은 값이면 시작 시점에 계산하고 요청마다 다르거나 만료될 수 있으면 핸들러에서 계산합니다. 측정 중 직접 관측한 사례로 그 원칙을 확인합니다.

시작 시점에 만든 값은 모든 인스턴스에서 동일합니다. `boot_id`가 1개에서 2개로 관측된 것이 그 증거입니다. 난수, 식별자, 토큰은 핸들러에서 `os.urandom()`, `secrets`, `uuid.uuid4()`로 생성해야 합니다. `random` 모듈도 시작 시점에 시드되므로 복원된 인스턴스들이 같은 수열을 반복합니다.

`time.monotonic()`은 복원을 넘지 않습니다. `uptime_mono_s`가 68초에서 69초에 고정된 것이 그 증거입니다. 시작 시점 기준으로 경과 시간을 재면 틀린 값이 나오고 틀려 보이지도 않습니다. 기준 시각은 핸들러 안에서 잡아야 합니다.

hostname과 PID를 인스턴스 식별자로 사용할 수 없습니다. 관측값은 모든 인스턴스에서 `localhost`와 PID 1이었습니다. 메트릭, 로그 스트림, 락 소유자가 전체 플릿에서 하나로 뭉개집니다.

암호 라이브러리는 스냅샷 안전(snapsafe) 빌드가 필요합니다. 시작 시점에 난수 상태를 캐시한 라이브러리는 인스턴스 간에 그 상태를 재사용합니다. Amazon Linux 2023에서는 `openssl-snapsafe-libs`가 그 빌드입니다. 직접 코드 배포의 서비스 관리 베이스 이미지는 이미 포함하고 있으나 컨테이너에 직접 넣는 경우 직접 챙겨야 합니다.

시작 시점에 캐시하면 안 되는 값도 있습니다. AgentCore Gateway에서 가져온 도구 카탈로그처럼 느리고 비싼 값은 시작 시점 캐싱 후보로 보이지만 그러면 에이전트의 도구 목록이 스냅샷 시점에 고정됩니다. 단기 자격증명도 인스턴스가 시작되기 전에 만료될 수 있습니다. 반대로 boto3 클라이언트처럼 재사용 가능한 객체는 시작 시점에 만들고 한 번 호출까지 해 두는 것이 좋습니다. 소켓은 복원을 넘지 못하지만 엔드포인트 해석과 커넥션 풀 설정은 스냅샷에 담기고 복원 후 첫 호출이 투명하게 재연결합니다.

```python
import os, time
from bedrock_agentcore.runtime import BedrockAgentCoreApp

client = build_client()   # 시작 시점: 재사용 객체는 여기서 만들고 워밍업
warm_up(client)

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload):
    creds = get_credentials()          # 만료 시 갱신, 시작 시점 값 사용 금지
    request_id = os.urandom(16).hex()  # 요청마다 새 값
    t0 = time.monotonic()              # 경과 시간 기준은 핸들러 안에서
    ...

app.run()  # 8080 포트 리슨 후 첫 정상 /ping 시점에 스냅샷 촬영
```

## 9. 한계

이 측정은 계정 1개, 리전 1개(ap-northeast-1), 2026년 9월 19일 하루의 결과입니다. 컨테이너 배포 경로만 측정했고 직접 코드(zip) 배포는 다루지 않았습니다. 네트워크 모드는 PUBLIC만 측정했고 VPC 모드는 다루지 않았습니다. 세션 수명이 60초로 짧아 수십 분 이상 이어지는 세션에서 메모리 회수가 유지되는지도 측정하지 않았습니다. 모델을 호출하지 않는 echo 에이전트이므로 플랫폼을 측정한 것이고 에이전트를 측정한 것이 아닙니다. 실제 에이전트에서 사용자가 체감하는 시간은 대부분 에이전트 루프와 모델 호출입니다. 여기서 측정한 cold start는 그 앞에 더해지는 플랫폼 몫입니다.

표본은 cold와 burst가 런타임당 30세션과 50세션이고 탄력 메모리는 레그당 4세션입니다. AWS 공개 수치는 에이전트당 5,000세션입니다. 방향성은 명확하나 정밀도는 낮습니다. 클라이언트가 리전 밖에 있어 모든 수치에 리전 간 왕복이 포함됩니다. footprint는 GB-hours를 클라이언트 관측 세션-시간으로 나눈 파생값입니다. 절대값은 리전, 이미지 내용, 계정 이력, 클라이언트 위치에 따라 달라집니다. 재현되어야 하는 것은 V1 대 V2의 비율입니다.

## 10. 마치며

글머리의 두 질문에 답하겠습니다. 1 GB를 넘는 이미지의 cold start는 V2에서 약 2초로 내려왔고 2 GB 이미지에서는 27.7초가 2.0초가 되었습니다. 세션 50개가 동시에 도착해도 그 값은 변하지 않았습니다. 30세션의 `boot_id`가 하나로 관측되어 스냅샷 복원이 실제로 일어남을 확인했습니다. 유휴 중 최고점 메모리 과금은 해제한 1.5 GB의 약 92%가 회수되는 것으로 답이 나왔습니다. 단가가 42.6%와 78.8% 올랐음에도 동일 워크로드의 총비용은 2 GB 이미지에서 10.8배 낮아졌습니다.

대가는 배포 시간 3분과 코드 구조의 변화입니다. 시작 시점 값은 모든 인스턴스가 공유한다는 한 가지 원칙만 지키면 난수, 시계, 식별자, 자격증명 문제는 모두 같은 자리에서 해결됩니다. 이미지가 크거나 세션 중 메모리 사용이 들쭉날쭉한 에이전트, 트래픽이 몰리는 시간대가 뚜렷한 에이전트가 V2의 이점을 가장 크게 봅니다. 이런 에이전트라면 `platformVersion`을 V2로 바꾸고 이 글과 같은 방식으로 자신의 워크로드를 한 번 측정해 보는 것을 권고합니다. 이 글의 측정 방법과 표가 여러분의 AgentCore Runtime V2 전환 검토에 실질적인 참고가 되기를 바랍니다.

## 참고 자료

- [The new AgentCore Runtime is now available in Amazon Bedrock AgentCore – What's New (2026년 9월 18일)](https://aws.amazon.com/about-aws/whats-new/2026/09/new-agentcore-runtime-generally-available/)
- [The new AgentCore runtime: Elastic, optimized, and consistently fast starts – AWS Artificial Intelligence Blog (2026년 9월 18일)](https://aws.amazon.com/blogs/machine-learning/the-new-agentcore-runtime-elastic-optimized-and-consistently-fast-starts/)
- [microVMs (Platform versions) – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)
- [Optimize your agent for Amazon Bedrock AgentCore Runtime V2 – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-v2-optimize.html)
- [Configure Amazon Bedrock AgentCore lifecycle settings – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [AgentCore generated runtime observability data – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- [AWS::BedrockAgentCore::Runtime – AWS CloudFormation Template Reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-runtime.html)
- [Amazon Bedrock AgentCore Pricing – 요금 페이지](https://aws.amazon.com/bedrock/agentcore/pricing/)
- [05-measure-your-runtime – awslabs/agentcore-samples (GitHub)](https://github.com/awslabs/agentcore-samples/tree/main/01-features/02-host-your-agent/01-runtime/05-measure-your-runtime)

*본문의 금액은 2026년 9월 20일 기준 AgentCore Runtime 공개 소비 기준 단가와 2026년 9월 19일 ap-northeast-1 리전 실측 사용량을 바탕으로 계산한 세전 USD 추정치입니다. 지연과 사용량 수치는 계정 1개, 하루의 측정이며 리전, 이미지 내용, 클라이언트 위치에 따라 달라질 수 있습니다.*

## 저자 소개

**최우형 (Woohyung Choi)** 님은 AWS Korea의 Principal Solutions Architect로, 국내 주요 엔터프라이즈 및 디지털 기업의 클라우드 전환과 아키텍처 현대화를 지원하고 있습니다. 특히 클라우드 네이티브 아키텍처와 Agentic AI 분야에 전문성을 가지고 있으며, 고객이 Amazon Bedrock을 비롯한 AWS의 생성형 AI 및 Agentic AI 기술을 안정적이고 비용 효율적으로 도입하고 확장할 수 있도록 아키텍처 설계와 기술 자문을 제공하고 있습니다.

컨테이너, 네트워킹, 비용 최적화를 비롯한 클라우드 핵심 기술부터 Agentic AI를 활용한 업무 혁신과 지능형 시스템 구축까지 폭넓은 영역에서 AWS 아키텍처 모범 사례를 제시하고 있습니다. 이를 통해 고객의 복잡한 기술적 과제를 해결하고, AI와 클라우드를 기반으로 지속 가능한 기술 전략을 수립하고 실행할 수 있도록 기술 리더십을 발휘하고 있습니다.

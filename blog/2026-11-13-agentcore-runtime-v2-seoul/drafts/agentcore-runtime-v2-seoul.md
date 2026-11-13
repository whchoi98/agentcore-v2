---
title: "이미지 크기와 무관한 2초 미만 cold start – 서울 리전에서 측정한 새로운 Amazon Bedrock AgentCore Runtime(플랫폼 버전 V2)"
date: 2026-11-13
author: "Woohyung Choi"
status: draft
---

# 이미지 크기와 무관한 2초 미만 cold start – 서울 리전에서 측정한 새로운 Amazon Bedrock AgentCore Runtime(플랫폼 버전 V2)

by WOO HYUNG CHOI on 13 11월 2026 in [Advanced (300)](https://aws.amazon.com/ko/blogs/tech/category/learning-levels/advanced-300/), [Amazon Bedrock](https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/amazon-machine-learning/amazon-bedrock/), [Amazon Bedrock AgentCore](https://aws.amazon.com/ko/blogs/tech/category/artificial-intelligence/amazon-machine-learning/amazon-bedrock/amazon-bedrock-agentcore/), [Best Practices](https://aws.amazon.com/ko/blogs/tech/category/post-types/best-practices/)

에이전트 컨테이너 이미지가 1 GB를 넘으면 새 세션의 첫 응답이 10초 이상 걸리지는 않으신가요? 세션이 모델 응답을 기다리며 유휴 상태로 있는 동안에도 최고점 메모리를 그대로 과금받고 있지는 않으신가요? AWS는 2026년 9월 18일 Amazon Bedrock AgentCore의 서버리스 microVM 컴퓨트인 AgentCore Runtime의 새 세대를 발표했습니다. 11월 12일에는 서울 리전을 포함한 19개 리전에서 새 런타임을 기본값으로 전환한다고 발표했습니다. 새 런타임은 두 가지를 약속합니다. 컨테이너 이미지 크기와 동시성에 무관한 일관된 cold start, 그리고 세션 중 해제된 메모리를 회수하는 탄력 메모리(Elastic memory)입니다.

이 글은 두 약속이 서울 리전(ap-northeast-2)에서 재현되는지 확인한 결과를 소개합니다. 같은 에이전트를 V1과 V2에 나란히 배포하고 2026년 11월 13일에 측정했습니다. 클라이언트와 런타임이 모두 서울 리전에 있으므로 수치에 리전 간 왕복이 들어 있지 않습니다. 단가는 2026년 11월 12일에 게시된 서울 리전 가격표를 기준으로 합니다. 이 글은 AgentCore Runtime에 에이전트를 배포하고 운영하는 개발자와 아키텍트를 대상으로 합니다. 세션(runtimeSessionId)마다 microVM이 하나씩 배정된다는 기본 동작을 알고 있다면 무리 없이 읽을 수 있습니다.

## 1. 새로운 AgentCore Runtime이 바꾼 것

### 1.1 스냅샷에서 시작하는 세션

V1에서 새 세션은 매번 처음부터 시작합니다. 컨테이너 이미지를 가져와 풀고 프로세스를 띄우고 의존성을 import하고 초기화 코드를 실행한 뒤에야 첫 요청을 처리합니다. 이미지가 클수록 이 경로가 길어지므로 cold start는 이미지 크기에 비례해 늘어납니다.

V2는 이 경로를 한 번만 밟습니다. 런타임을 생성하거나 업데이트할 때 AgentCore Runtime이 컨테이너를 띄우고 `/ping`이 정상 응답을 낼 때까지 기다린 뒤, 실행 중인 환경의 스냅샷을 촬영합니다. 이후 모든 새 세션은 이 스냅샷을 복원해 시작합니다. 초기화가 이미 끝난 상태에서 출발하므로 시작 시간이 이미지 크기와 무관해집니다. 세션이 한꺼번에 몰려도 각 세션은 같은 스냅샷을 복원하기만 하면 되므로 동시성에도 영향을 받지 않습니다.

![V1은 세션마다 이미지 pull, 프로세스 기동, 초기화를 반복해 서울 리전 cold start p75가 200 MB 5.37초, 1 GB 13.41초, 2 GB 27.51초로 이미지 크기에 비례하고 V2는 런타임 생성 시 한 번 초기화한 환경의 스냅샷을 모든 세션이 복원해 1.77초, 1.74초, 1.81초로 일정합니다.](images/agentcore-runtime-v2-seoul-fig01-start-path.png)

*그림 1. V1과 V2의 세션 시작 경로. V1은 세션마다 전체 시작 절차를 반복하고 V2는 생성 시 한 번 만든 스냅샷을 세션마다 복원합니다. 수치는 이 글의 서울 리전 측정값입니다.*

AWS의 9월 발표문은 200 MB부터 2 GB 이미지까지 p75 cold start가 1.9초에서 2.0초였다고 밝혔고 11월 발표문은 2 GB 이미지에서 p75 2초 미만(이전 세대 29.7초)을 제시합니다. 이 글의 측정은 이 수치를 서울 리전에서 다시 확인하는 데서 출발합니다.

### 1.2 필요한 만큼만 잡는 탄력 메모리

V1은 세션이 한 번 확보한 메모리를 세션이 끝날 때까지 유지합니다. 문서 분석 도구가 잠깐 1.5 GB를 사용하고 해제해도 과금 기준은 그 최고점(high watermark)을 따라갑니다. V2는 더 이상 사용하지 않는 메모리를 세션 도중에 회수합니다. 요금 페이지에 따르면 V2에서 유휴 메모리는 120초 뒤 자동으로 회수됩니다. 11월 발표문은 다중 턴 에이전트에서 세션당 청구 메모리가 최대 68% 줄어든다고 밝혔습니다. 에이전트는 모델 응답과 도구 호출을 기다리는 시간이 대부분이므로 이 차이는 과금 GB-hours에 바로 반영됩니다.

### 1.3 서울 리전 지원과 기본값 전환

이 기능은 발표문에서 "새로운 AgentCore Runtime"으로 불리고 개발자 가이드에서는 Platform versions 페이지가 설명합니다. API 설정에서는 런타임 단위 `platformVersion` 필드에 `V1`이나 `V2`를 지정합니다. 11월 12일 발표문에 따르면 새로 만드는 런타임에는 V2가 기본으로 적용되고 기존 런타임은 옮기기 전까지 현재 버전에 남습니다.

다만 개발자 가이드는 11월 13일 현재 "필드를 생략하면 V1"이라고 적고 있고 V2 지원 리전 목록에도 서울이 아직 없습니다. 발표문과 문서가 다르므로 필자는 서울 리전에서 API 동작을 직접 확인했습니다. 각 런타임을 새 세션 3개로 호출해 적용된 버전이 실제 동작과 맞는지도 함께 보았습니다.

| 요청 | 적용된 `platformVersion` | READY 도달 | 동작 근거 |
|---|---|---|---|
| 생성, 필드 생략 (boto3 2회, AWS CLI 1회) | V1 | 1.4초에서 3.2초 | cold start 5.3초에서 5.5초, 세션마다 다른 `boot_id` |
| 생성, `V1` 지정 | V1 | 3.2초 | cold start 5.3초에서 5.4초, 세션마다 다른 `boot_id` |
| V1 런타임 업데이트, 필드 생략 | V1 유지 | 3.2초 | |
| V1 런타임 업데이트, `V2` 지정 | V2 | 185.0초 | cold start 1.55초에서 1.81초, `uptime_mono_s` 68초 고정 |
| 생략해 만든 런타임 업데이트, `V1` 지정 | V1 | 3.2초 | cold start 5.3초에서 5.4초 |

*표 1. 서울 리전에서 확인한 `platformVersion` 동작 (2026년 11월 13일 00:18에서 02:13 UTC, 계정 1개, boto3 1.44.2, AWS CLI 2.38.5). AWS CLI로 만든 런타임의 READY 시간은 `createdAt`에서 `lastUpdatedAt`까지입니다. 동작 근거의 진단 필드는 측정 방법에서 설명합니다.*

이 계정에서는 측정 시각 기준으로 기본값 전환이 API에 반영되지 않았습니다. 발표문은 기본값이 콘솔, CLI, SDK 중 어디에 적용되는지 밝히지 않으며 계정별로 순차 적용될 가능성도 있습니다. 어느 경우든 V2가 필요하면 `platformVersion`을 명시하고 적용 결과를 확인하는 것을 권고합니다. 기본값을 믿고 필드를 생략했다면 이 글의 V2 런타임 4개는 조용히 V1으로 만들어졌을 것입니다.

```bash
aws bedrock-agentcore-control create-agent-runtime \
  --region ap-northeast-2 \
  --agent-runtime-name "my_agent" \
  --role-arn "arn:aws:iam::111122223333:role/AgentExecutionRole" \
  --agent-runtime-artifact '{"containerConfiguration": {"containerUri": "111122223333.dkr.ecr.ap-northeast-2.amazonaws.com/my-agent:latest"}}' \
  --network-configuration '{"networkMode": "PUBLIC"}' \
  --platform-version V2

aws bedrock-agentcore-control get-agent-runtime \
  --region ap-northeast-2 \
  --agent-runtime-id my_agent-ABCDE12345 --query platformVersion
```

생성과 업데이트 응답에는 `platformVersion`이 없고 `list-agent-runtimes` 항목에도 없습니다. 두 번째 명령처럼 `get-agent-runtime`으로만 확인할 수 있습니다.

### 1.4 서울 리전 단가

단가는 V2가 더 높습니다. 서울 리전 가격표에는 소비 기반(consumption) 단가와 약정 기준선(committed baseline) 단가가 함께 실려 있습니다. 약정 기준선은 런타임에 `resourceConfigurations`로 세션당 기준 용량을 정하는 방식입니다. 이 글의 계산은 기본값인 소비 기반 단가만 사용합니다.

| 항목 | V1 | V2 (소비 기반) | V2 (약정 기준선) | V2 소비 기반 증가율 |
|---|---|---|---|---|
| vCPU-hour | 0.0895 USD | 0.1276 USD | 0.0997 USD | +42.6% |
| GB-hour | 0.00945 USD | 0.0169 USD | 0.0132 USD | +78.8% |

*표 2. 서울 리전 AgentCore Runtime microVM 단가 (USD, 세전, AWS 가격표 API의 2026년 11월 12일 게시본). 초 단위로 계량되며 최소 1초, 메모리 최소 과금은 128 MB입니다.*

단가가 올랐는데 총비용이 내려갈 수 있는지가 이 글의 두 번째 질문입니다. 답은 계량되는 단위 수에 달려 있습니다.

## 2. 측정 방법

### 2.1 측정 대상과 이미지 3종

측정 대상은 모델을 호출하지 않는 FastAPI echo 에이전트입니다. 무거운 의존성이 없으므로 측정값은 애플리케이션 작업이 아니라 플랫폼의 시작 경로를 반영합니다. 핸들러 자체의 처리 시간은 모든 레그에서 p75 0.1 ms였습니다.

같은 에이전트에 `/dev/urandom` 패딩을 더해 이미지 3종을 만들었습니다. Amazon ECR은 레이어를 gzip으로 압축해 저장하므로, `/dev/zero`로 채운 패딩은 압축되어 사라지고 크기별 pull 비용을 측정하는 의미가 없어집니다. 이미지 라벨은 AWS 샘플(agentcore-samples의 05-measure-your-runtime)의 크기 라벨을 따랐고 200mb는 샘플과 같이 패딩 없는 기준 이미지입니다.

| 라벨 | 패딩(MB) | ECR 압축 크기 | 비압축 추정 |
|---|---|---|---|
| 200mb | 0 | 45.4 MiB | 약 230 MB |
| 1gb | 797 | 842.6 MiB | 약 1,027 MB |
| 2gb | 1,821 | 1,866.9 MiB | 약 2,051 MB |

*표 3. 측정에 사용한 컨테이너 이미지 (linux/arm64, python:3.13-slim 기반). 압축 크기는 ECR DescribeImages 값이며 MiB = 2^20 바이트입니다.*

### 2.2 측정 구성

![서울 리전 VPC의 EC2 벤치마크 클라이언트가 같은 리전의 AgentCore Runtime 8개(이미지 3종과 탄력 메모리용 1종, 각각 V1과 V2)를 InvokeAgentRuntime으로 호출하고 런타임은 ECR 이미지를 사용하며 사용량과 OverheadLatency는 CloudWatch의 AWS/Bedrock-AgentCore 지표로 수집합니다. 같은 리전 왕복은 TCP와 TLS 합산 4.3 ms에서 5.2 ms입니다.](images/agentcore-runtime-v2-seoul-fig02-bench-setup.png)

*그림 2. 측정 구성. 클라이언트와 런타임이 같은 서울 리전에 있으므로 경로 비용이 수 ms 수준입니다.*

클라이언트는 서울 리전의 EC2 r8g.4xlarge(aarch64, Python 3.12, boto3 1.44.2)입니다. 런타임은 네트워크 모드 PUBLIC, 프로토콜 HTTP로 만들었습니다. V2 런타임 4개는 `platformVersion="V2"`를 명시했고 생성 직후 `get_agent_runtime`으로 적용된 버전을 확인했습니다. 시나리오마다 측정한 네트워크 기준선의 중위값은 TCP 핸드셰이크 2.2 ms에서 2.7 ms, TCP와 TLS 합산 4.3 ms에서 5.2 ms였습니다.

### 2.3 스냅샷 복원을 증명하는 진단 필드

V2가 정말 스냅샷에서 복원되는지 확인하기 위해, 에이전트는 import 시점 즉 스냅샷 촬영 전에 값을 만들어 응답에 실어 보냅니다. `boot_id`는 import 시 `os.urandom()`으로 만든 난수입니다. V1은 세션마다 새 프로세스이므로 매번 다르고 V2는 모든 인스턴스가 같은 스냅샷을 복원하므로 같아야 합니다. `uptime_mono_s`는 `time.monotonic()` 기준 경과 시간입니다. 이 시계는 복원 뒤에 이어서 흐르지 않으므로 V2에서는 스냅샷 촬영 시점 값에 고정됩니다. `uptime_wall_s`는 `time.time()` 기준이라 계속 흐르므로, V2에서는 인스턴스의 나이 대신 스냅샷의 나이를 나타냅니다.

요청마다 달라야 하는 `req_id`와 `served_at`은 핸들러 안에서 생성했습니다. 시작 시점에 만든 값은 스냅샷에 고정되어 모든 인스턴스에서 반복되기 때문이며 V2 최적화 가이드가 요구하는 방식입니다.

### 2.4 세션 처리와 반복 측정

모든 cold start 측정은 새 `runtimeSessionId`로 1회 호출한 뒤 즉시 `StopRuntimeSession`을 호출합니다. AgentCore Runtime은 세션 수명 전체를 과금하고 벤치마크 세션은 대부분 유휴 상태이므로, 방치하면 측정과 무관한 비용이 대부분을 차지합니다. `idleRuntimeSessionTimeout`과 `maxLifetime`은 최소값인 60초로 설정했습니다. 재시도는 껐습니다. cold start는 측정 대상이므로 재시도 뒤에 숨으면 안 되기 때문입니다.

본 측정은 cold, burst, warm 세 시나리오를 간격 없이 이어서 실행했습니다. 같은 날 같은 런타임으로 레그 사이에 90초 간격을 둔 반복 측정을 한 번 더 했습니다. 반복 측정은 수치가 재현되는지 확인하고 분 단위로 발행되는 CloudWatch 지표를 레그별로 분리하는 데 사용했습니다. 표의 수치는 따로 밝히지 않으면 본 측정값입니다.

## 3. Cold start는 이미지 크기와 동시성에 무관한가

### 3.1 새 세션 30개, 동시성 5

런타임마다 새 세션 30개를 동시성 5로 호출했습니다. 모든 호출이 cold start입니다.

| 이미지 | V1 p75 | V2 p75 | V1 ÷ V2 |
|---|---|---|---|
| 200mb | 5.37초 | 1.77초 | 3.0배 |
| 1gb | 13.41초 | 1.74초 | 7.7배 |
| 2gb | 27.51초 | 1.81초 | 15.2배 |

*표 4. 서울 리전 cold start p75 (런타임당 새 세션 30개, 동시성 5, 클라이언트 측정).*

![이미지 크기 200 MB, 1 GB, 2 GB에 대한 서울 리전 cold start p75 막대 비교. V1은 5.37초, 13.41초, 27.51초로 이미지 크기에 비례해 증가하고 V2는 1.77초, 1.74초, 1.81초로 2초 기준선 아래에 머뭅니다.](images/agentcore-runtime-v2-seoul-fig03-cold-start-p75.png)

*그림 3. 이미지 크기별 cold start p75. V1은 크기에 비례해 늘고 V2는 1.74초에서 1.81초 사이에 머뭅니다.*

개별 수치보다 모양이 중요합니다. V1의 cold start는 이미지 크기에 비례해 커집니다. V2는 200 MB부터 2 GB까지 1.74초에서 1.81초 사이에 머뭅니다. 반복 측정에서도 V2 p75는 1.69초에서 1.94초였습니다. 일관성을 변동계수(CV)로 보면 V2는 0.080에서 0.086으로 이미지 크기와 무관하게 일정하고 V1은 0.849에서 1.347입니다. 같은 이미지끼리 비교하면 V2가 11배에서 16배 안정적입니다.

| 이미지 | 버전 | p50 (ms) | p75 (ms) | p99 (ms) | CV | 성공 | `boot_id` 개수 | `uptime_mono_s` | `uptime_wall_s` |
|---|---|---|---|---|---|---|---|---|---|
| 200mb | V1 | 932 | 5,369 | 5,460 | 0.849 | 30/30 | 30 | 2.5 | 7.7 |
| 200mb | V2 | 1,700 | 1,772 | 1,957 | 0.080 | 30/30 | 2 | 68.8 | 565 |
| 1gb | V1 | 451 | 13,411 | 13,513 | 1.208 | 30/30 | 30 | 3.7 | 15.0 |
| 1gb | V2 | 1,665 | 1,742 | 2,212 | 0.086 | 30/30 | 2 | 68.5 | 419 |
| 2gb | V1 | 476 | 27,508 | 29,666 | 1.347 | 30/30 | 30 | 3.9 | 29.9 |
| 2gb | V2 | 1,708 | 1,810 | 2,141 | 0.086 | 30/30 | 2 | 71.3 | 267 |

*표 5. cold start 분포와 스냅샷 증거 (같은 30세션). CV는 변동계수(표준편차 ÷ 평균)이고 `uptime_mono_s`와 `uptime_wall_s`는 세션별 값의 중위값(초)입니다. throttle은 전 구간 0건입니다.*

표에서 눈여겨볼 점은 V1 분포의 모양, `boot_id` 개수, 두 시계의 값입니다.

첫째, V1의 p50과 p75가 크게 벌어집니다. 2 GB에서 p50은 476 ms인데 p75는 27,508 ms입니다. 분포가 이봉형(bimodal)이라는 뜻이고 원인은 사전 초기화된 환경입니다. 빠른 군집은 15개에서 20개 세션이었고 중위값이 399 ms, 413 ms, 457 ms로 이미지 크기와 무관했습니다. 발표 블로그도 이미 초기화된 환경에 착륙한 세션은 100 ms 안에 시작한다고 밝힙니다. 느린 군집의 중위값은 5,369 ms, 13,428 ms, 27,576 ms입니다. V1에서 이미지 크기가 만드는 페널티는 이미지 전송과 전개 비용이며 프로세스 시작 비용이 아닙니다. V1의 빠른 군집은 V2보다 빠르지만 V2에는 이봉성이 없어 최악값을 예측할 수 있습니다.

둘째, `boot_id`가 스냅샷 복원을 증명합니다. V1은 30세션에서 서로 다른 `boot_id` 30개가 나왔습니다. 프로세스가 30번 새로 시작했다는 뜻입니다. V2는 30세션에서 2개만 나왔습니다. 거의 모든 인스턴스가 같은 준비된 환경을 복원했습니다.

셋째, V2의 두 시계가 갈라집니다. `uptime_mono_s`는 68초에서 71초에 고정되고 `uptime_wall_s`는 267초에서 565초입니다. 스냅샷은 프로세스 시작 후 약 69초 지점에서 촬영됐고 측정 시점에 4분에서 9분 된 상태였습니다. monotonic 시계가 복원 뒤에 이어서 흐르지 않는다는 문서 설명이 그대로 관측됩니다. 반대편 확인도 통과했습니다. cold와 burst를 합쳐 V2가 처리한 240개 요청의 `req_id`는 모두 달랐습니다. 핸들러에서 `os.urandom()`으로 만든 값은 복원 후에도 새 엔트로피를 받습니다.

### 3.2 동시 세션 50개

동시성과 무관하다는 주장을 직접 시험하기 위해 런타임마다 새 세션 50개를 한꺼번에 호출했습니다.

| 이미지 | V1 p75 | V2 p75 | V1 ÷ V2 |
|---|---|---|---|
| 200mb | 5.37초 | 1.70초 | 3.2배 |
| 1gb | 13.49초 | 1.80초 | 7.5배 |
| 2gb | 27.59초 | 1.81초 | 15.2배 |

*표 6. 동시 cold start p75 (런타임당 새 세션 50개 동시 호출). 150건 시도 중 throttle 0건, 실패 0건입니다.*

V2는 동시성 5일 때와 사실상 같습니다. p50과 p75 모두 동시성 5의 값과 6% 안에서 일치합니다. 서울 리전의 기본 쿼터(새 세션 생성 25 TPS, 활성 세션 2,500개) 안에서 50건이 동시에 도착해도 V2의 시작 시간은 변하지 않았습니다.

V1은 p50이 무너집니다. 동시성 5일 때 451 ms와 932 ms 사이였던 p50이 5,332 ms, 13,450 ms, 27,501 ms가 됩니다. 50건이 한꺼번에 도착하면 사전 초기화 환경이 바로 고갈되어 이봉 분포의 빠른 쪽이 사라지기 때문입니다. 빠른 군집은 200 MB와 1 GB에서 정확히 10건이었고 2 GB에서는 0건이었습니다. 2 GB burst는 cold 측정이 사전 초기화 환경을 소진하고 약 38초 뒤에 시작했습니다. 레그 사이에 10분 넘게 간격을 둔 반복 측정에서는 2 GB에서도 빠른 군집 10건이 돌아왔습니다. 런타임당 사전 초기화 환경이 약 10개이고 직전 트래픽 이력에 따라 다시 채워진다는 해석이 자연스럽습니다. 다만 관측에서 추론한 값이고 문서화된 값이 아니므로 설계 근거로 삼지 않는 것을 권고합니다.

### 3.3 V1의 진짜 cold start는 이미지 크기에 선형

느린 군집만 따로 보면 V1의 cold start는 압축 이미지 크기에 거의 선형입니다. 표본이 많은 동시 50세션 측정의 느린 군집 중위값(5,354 ms, 13,460 ms, 27,501 ms)을 ECR 압축 크기에 최소제곱 회귀하면 다음 식이 나옵니다.

```
V1 cold start(ms) ≈ 4,207 + 12.23 × 압축 이미지 크기(MiB)      R² = 0.993
```

절편 4.2초는 이미지와 무관한 microVM 부팅과 초기화 비용으로, 기울기 12.23 ms/MiB는 이미지 전송과 전개 비용으로 읽힙니다. V1에서 이미지를 100 MiB 줄이면 cold start가 약 1.2초 줄어드는 셈입니다. V2에서는 스냅샷 복원 시간이 이미지 크기에 거의 반응하지 않으므로 이 최적화의 효과가 사라집니다. 세 점으로 구한 회귀이므로 방향성 참고로 볼 것을 권고합니다.

### 3.4 발표 수치와의 비교

| 항목 | 발표 수치 | 서울 측정 (본 측정, 반복 측정) |
|---|---|---|
| V2 p75, 2 GB 이미지 | 2초 미만 | 1.81초, 1.94초 |
| V2 p75, 200 MB에서 2 GB | 1.9초에서 2.0초 | 1.74초에서 1.81초, 1.69초에서 1.94초 |
| V1 p75, 2 GB 이미지 | 29.7초 | 27.51초, 29.49초 |
| V1 p75, 200 MB 이미지 | 약 5.4초 | 5.37초, 5.34초 |

*표 7. 발표 수치와 서울 측정 비교. 발표 수치는 2026년 9월 18일과 11월 12일 What's New 발표문과 발표 블로그의 값이며 측정 리전과 표본 수는 발표문에 밝혀져 있지 않습니다.*

서울 리전의 V2는 발표 수치보다 조금 빠르고 V1은 발표 수치와 거의 같습니다. 2 GB 이미지 기준 p75 2초 미만이라는 발표 문구가 서울 리전에서 두 번의 측정 모두 재현됐습니다.

### 3.5 플랫폼이 차지하는 시간

AgentCore Runtime은 2026년 11월부터 V2 런타임에 `OverheadLatency` 지표를 발행합니다. 서비스가 요청을 받은 시점부터 에이전트가 첫 응답 바이트를 돌려줄 때까지의 시간에서 에이전트 자체 처리 시간을 뺀 값입니다. 차원은 `Resource`(런타임 ARN), `Operation`(`InvokeAgentRuntime`), `Name`(`런타임이름::DEFAULT`)이고 V1 런타임에는 발행되지 않습니다. 분 단위 지표가 레그끼리 섞이지 않도록 반복 측정의 값을 사용했고 표본 수는 클라이언트 기록과 정확히 일치했습니다.

| 구간 | 이미지 | 클라이언트 p50 | 서비스 `Latency` p50 | `OverheadLatency` p50 |
|---|---|---|---|---|
| cold | 200mb | 1,575 ms | 1,580 ms | 1,474 ms |
| cold | 1gb | 1,758 ms | 1,711 ms | 1,599 ms |
| cold | 2gb | 1,677 ms | 1,693 ms | 1,582 ms |
| warm | 200mb | 106.1 ms | 81.8 ms | 62.4 ms |
| warm | 1gb | 100.5 ms | 75.4 ms | 57.0 ms |
| warm | 2gb | 101.0 ms | 77.8 ms | 58.5 ms |

*표 8. V2 런타임의 클라이언트 지연과 CloudWatch 지표 (반복 측정, cold는 런타임당 30세션, warm은 세션 1개에서 31회 호출). CloudWatch 백분위는 근사값이므로 10 ms 아래의 차이는 해석하지 않습니다.*

V2 cold start 약 1.6초에서 1.8초 가운데 1.47초에서 1.60초가 플랫폼 몫입니다. echo 에이전트라 에이전트 몫이 거의 없으므로, 이 값이 이 측정 조건에서 V2 cold start의 하한에 가깝습니다. 클라이언트와 서비스 `Latency`의 차이는 50 ms 아래로 같은 리전 경로 비용이 작다는 점도 확인됩니다. 실제 에이전트에서 cold start가 어디서 늘어나는지 볼 때 이 지표로 플랫폼 몫과 에이전트 몫을 나눌 수 있습니다.

## 4. Warm 지연과 세션 재사용

한 세션을 유지하며 30회 순차 호출했습니다. 첫 호출은 cold start이므로 따로 기록했습니다.

| 이미지 | 버전 | 첫 호출(cold) | warm p50 | warm p75 | warm p99 |
|---|---|---|---|---|---|
| 200mb | V1 | 325 ms | 66.8 ms | 74.8 ms | 93.0 ms |
| 200mb | V2 | 1,695 ms | 90.3 ms | 94.5 ms | 116.8 ms |
| 1gb | V1 | 435 ms | 66.2 ms | 69.6 ms | 102.7 ms |
| 1gb | V2 | 1,769 ms | 87.1 ms | 94.7 ms | 110.5 ms |
| 2gb | V1 | 455 ms | 66.9 ms | 76.5 ms | 107.0 ms |
| 2gb | V2 | 1,482 ms | 90.3 ms | 100.1 ms | 109.1 ms |

*표 9. 세션 재사용 시 지연 (세션 1개, cold 1회 + warm 30회).*

V2의 warm 요청은 V1보다 p50 기준 20.9 ms에서 23.5 ms 느렸습니다. 반복 측정에서도 18.2 ms에서 21.2 ms로 세 이미지 모두 같은 방향이었습니다. 앞에서 본 `OverheadLatency`로 보면 V2 warm 요청 하나의 플랫폼 몫은 57 ms에서 62 ms입니다. 모델 호출 한 번이 수백 ms에서 수 초이므로 에이전트 한 턴에서 20 ms 남짓은 작은 차이입니다. 다만 짧은 요청을 많이 보내는 도구 서버처럼 플랫폼 몫이 요청 시간의 대부분인 워크로드에서는 체감될 수 있습니다.

이 표의 첫 열에는 V1 측정의 함정이 보입니다. 런타임당 세션이 하나뿐이라 V1이 사전 초기화 환경에 착륙해 325 ms에서 455 ms가 나옵니다. 같은 런타임의 진짜 cold start는 5.4초에서 27.5초입니다. 적은 표본으로 V1을 측정하면 실제보다 훨씬 빠르게 나오므로, V1 벤치마크는 사전 초기화 환경을 소진시켜야 의미가 있습니다.

warm 90 ms 대 cold 1.7초라는 비율로 보면 세션 재사용이 여전히 가장 큰 지연 해법입니다. cold start는 재사용이 불가능할 때 내는 값입니다. 발표 블로그의 실무 팁도 같은 방향입니다. 사용자가 대화를 시작하는 순간 세션을 먼저 열어 두면, 첫 메시지를 입력하는 동안 환경이 준비되어 시작 시간이 사실상 감춰집니다.

## 5. 단가는 올랐는데 총비용은 내려가는가

과금 사용량은 CloudWatch `AWS/Bedrock-AgentCore` 네임스페이스의 `MemoryUsed-GBHours`와 `CPUUsed-vCPUHours` 지표로 조회했습니다. 차원은 `Resource`(런타임 ARN)와 `Service`(`AgentCore.Runtime`)입니다. 문서에 따르면 이 지표는 최대 60분 늦게 도착할 수 있습니다. 실제로 일부 값은 15분 뒤에도 비어 있다가 1시간 가까이 지나서 들어왔으므로, 마지막 세션 후 70분 뒤에 수집했습니다. 앞의 세 시나리오를 합쳐 런타임당 81세션이며 V1과 V2에 같은 워크로드입니다.

```
세션당 비용(USD) = GB-hours ÷ 세션 수 × GB-hour 단가 + vCPU-hours ÷ 세션 수 × vCPU-hour 단가
추정 footprint(GB) = GB-hours ÷ 관측 세션-시간
```

| 이미지 | 버전 | 세션 | GB-hours | vCPU-hours | 추정 footprint | 비용 |
|---|---|---|---|---|---|---|
| 200mb | V1 | 81 | 0.1422 | 0.1172 | 1.67 GB | 0.0118 USD |
| 200mb | V2 | 81 | 0.0718 | 0.0554 | 1.89 GB | 0.0083 USD |
| 1gb | V1 | 81 | 1.0559 | 0.4349 | 5.37 GB | 0.0489 USD |
| 1gb | V2 | 81 | 0.1008 | 0.0581 | 2.63 GB | 0.0091 USD |
| 2gb | V1 | 81 | 2.7836 | 0.7566 | 5.98 GB | 0.0940 USD |
| 2gb | V2 | 81 | 0.1088 | 0.0609 | 2.77 GB | 0.0096 USD |

*표 10. 같은 워크로드(cold 30 + burst 50 + warm 1세션)의 과금 사용량과 비용 추정치 (USD, 세전, 소수 넷째 자리, 표 2의 소비 기반 단가 적용). footprint는 GB-hours를 클라이언트가 관측한 세션-시간으로 나눈 참고값입니다.*

2 GB 이미지에서 V2는 GB-hour 단가가 78.8% 높은데도 GB-hours가 25.6배 적어 총비용이 9.8배 낮습니다. V1의 GB-hours는 200 MB에서 2 GB로 가며 19.6배 늘어나고 V2는 0.072에서 0.109로 1.5배 늘어나는 데 그칩니다. 컨테이너 전체를 세션 내내 메모리에 상주시키는 대신 필요한 부분만 로드한다는 설명과 맞습니다. vCPU-hours도 같은 방향입니다. V2는 0.055에서 0.061로 거의 평탄하고 V1은 6.5배 늘어납니다. 느린 cold start는 지연 문제이면서 CPU 과금 문제이기도 합니다. microVM 부팅과 이미지 전개 중에 사용한 CPU도 요청 처리와 같은 단가로 과금됩니다.

footprint 열은 세션 수명 차이를 감안해서 읽어야 합니다. V1 2 GB 세션은 cold start 자체가 27초라 그만큼 오래 살았습니다. 이 워크로드에서 V1은 메모리를 더 많이 잡고 그 상태를 더 오래 유지하는 두 효과가 함께 작용합니다. 순수 footprint 비교는 세션 수명을 맞춘 탄력 메모리 측정에서 따로 다룹니다. 200 MB에서는 footprint만 보면 V2(1.89 GB)가 V1(1.67 GB)보다 오히려 큽니다. 로드할 이미지가 작으면 필요한 부분만 로드해서 아낄 것이 적고 단가 인상만 남기 때문입니다.

| 이미지 | V1 1,000세션 | V2 1,000세션 | V2 절감률 |
|---|---|---|---|
| 200mb | 0.146 USD | 0.102 USD | 30% |
| 1gb | 0.604 USD | 0.113 USD | 81% |
| 2gb | 1.161 USD | 0.119 USD | 90% |

*표 11. 측정한 세션당 사용량으로 정규화한 1,000세션당 비용 추정치 (USD, 세전, 소수 셋째 자리, 표 2의 소비 기반 단가 적용). 측정과 같은 세션 수명 가정(세션당 호출 1회 후 즉시 종료)을 유지한 두 버전 간 비교이며 실제 청구서 예측이 아닙니다.*

이미지가 클수록 V2의 절감률이 커지고 2 GB에서는 90%입니다. 반복 측정에서도 1 GB와 2 GB의 절감률은 비슷한 범위였습니다. 200 MB처럼 작은 이미지에서는 절감 폭이 좁고 측정마다 흔들립니다. 에이전트가 실제로 사용하지 않는 이미지 부분이 많을수록 V2가 유리합니다.

측정 중에 V1에서 문서에 없는 동작도 관측했습니다. V1 런타임은 호출이 한 번도 없는데 생성한 그 분 안에 사용량이 기록됐습니다. 200 MB는 0.0228 GB-hours, 1 GB는 0.1497 GB-hours, 2 GB는 0.3752 GB-hours로 이미지 크기에 비례했고 V2 런타임에서는 기록되지 않았습니다. 금액으로 환산하면 이미지 크기와 무관하게 V1 cold 세션 약 10개분입니다. V1이 생성 시 사전 초기화 환경을 준비하는 비용으로 보이지만 청구서와 대조하지 않았으므로 추정입니다. 사용량을 직접 집계할 때는 창을 측정 시작 직전부터 열어야 이 값이 섞이지 않습니다.

이 측정의 비용은 cold, burst, warm 486세션에 0.18 USD였고 탄력 메모리 측정의 메모리 과금은 0.01 USD 미만이었습니다.

## 6. 해제한 메모리를 정말 회수하는가

앞의 시나리오는 이 질문에 답하지 못합니다. echo 에이전트는 메모리를 할당하지 않기 때문입니다. 그래서 별도 런타임 한 쌍을 만들고 세션 모양을 맞췄습니다. 호출 1회에서 1,536 MB를 할당하고 모든 페이지에 실제로 값을 써서 상주시킨 뒤 해제하고 응답합니다. 이어서 클라이언트가 90초간 세션을 유휴로 유지하고 정지시킵니다. 대조군은 할당 없이 같은 세션 모양과 같은 유휴 시간을 반복하므로, 스파이크 자체의 기여분이 기준선 세션 비용과 분리됩니다. 레그마다 150초 정적 구간을 두어 CloudWatch 분 버킷이 섞이지 않게 했습니다.

에이전트가 보고한 프로세스 RSS는 50.4 MB에서 1,593.4 MB로 올랐다가 52.5 MB로 돌아왔습니다. 할당도 해제도 실제였습니다. 플랫폼이 과금한 값은 레그별로 세션-시간을 맞춰 비교했습니다.

| 레그 | 버전 | 세션 | 세션-시간 | GB-hours | 추정 footprint |
|---|---|---|---|---|---|
| 1,536 MB 할당 후 해제 | V1 | 4 | 0.1036 | 0.2976 | 2.87 GB |
| 대조군 (할당 없음) | V1 | 4 | 0.1006 | 0.1275 | 1.27 GB |
| 1,536 MB 할당 후 해제 | V2 | 4 | 0.1055 | 0.1352 | 1.28 GB |
| 대조군 (할당 없음) | V2 | 4 | 0.1020 | 0.1229 | 1.20 GB |

*표 12. 탄력 메모리 측정의 레그별 과금 사용량 (레그당 4세션, 각 세션은 호출 1회 + 유휴 90초). 세션-시간 단위는 시간(h)입니다.*

| 버전 | 대조군 footprint | 스파이크 후 footprint | 스파이크 기여분 | GB-hours 비율 |
|---|---|---|---|---|
| V1 | 1.27 GB | 2.87 GB | +1.60 GB | 2.33배 |
| V2 | 1.20 GB | 1.28 GB | +0.08 GB | 1.10배 |

*표 13. 해제된 1.5 GB 스파이크가 세션 과금 footprint에 남기는 양. 세션-시간을 0.10 h 수준으로 맞췄으므로 수명이 아니라 footprint 차이입니다.*

![V1과 V2의 대조군 대비 스파이크 후 과금 footprint 막대. V1은 1.27 GB에서 2.87 GB로 1.60 GB가 남고 V2는 1.20 GB에서 1.28 GB로 0.08 GB만 남습니다.](images/agentcore-runtime-v2-seoul-fig04-elastic-memory.png)

*그림 4. 1.5 GB를 할당 후 해제한 세션의 과금 footprint. 두 버전 모두 대조군과 세션 수명을 맞춘 비교입니다.*

V1은 1.5 GB 스파이크가 해제된 뒤에도 세션이 끝날 때까지 과금 footprint에 1.60 GB로 남습니다. V2는 0.08 GB만 남아 V1 잔존분의 5% 수준입니다. 세션 길이가 약 93초로 요금 페이지의 회수 시간 120초보다 짧았는데도, 해제한 스파이크는 거의 과금되지 않았습니다.

할당 레그만 보면 V2의 GB-hours는 V1보다 55% 적습니다. 발표문의 "세션당 청구 메모리 최대 68% 감소"와 비슷한 크기입니다. 다만 이 비율은 메모리 사용량 기준이고 비용 기준이 아닙니다. V2의 GB-hour 단가가 78.8% 높으므로 같은 레그의 메모리 비용은 0.00281 USD에서 0.00228 USD로 19% 줄었습니다. 메모리 사용량이 68% 줄면 메모리 비용은 약 43% 줄어드는 셈이므로, 비용 효과를 판단할 때는 이 차이를 감안하는 것을 권고합니다.

## 7. 배포 시간과 운영에서 걸리는 지점

| 런타임 | platformVersion | API 호출 | READY 도달 |
|---|---|---|---|
| 200mb | V1 | 0.60초 | 3.18초 |
| 200mb | V2 | 0.60초 | 185.44초 |
| 1gb | V1 | 0.66초 | 3.14초 |
| 1gb | V2 | 0.61초 | 200.42초 |
| 2gb | V1 | 0.56초 | 3.28초 |
| 2gb | V2 | 0.61초 | 215.78초 |

*표 14. 서울 리전 런타임 생성 API 호출 시간과 READY 상태 도달 시간 (get_agent_runtime 3초 간격 폴링). 기존 V1 런타임을 V2로 업데이트하는 데는 185.0초, 다시 V1로 되돌리는 데는 3.2초가 걸렸습니다.*

V2가 분명히 불리한 항목은 배포 시간 하나입니다. 컨테이너를 띄우고 첫 정상 `/ping`을 기다린 뒤 스냅샷을 촬영해야 하므로 V1보다 58배에서 65배 오래 걸리고 이미지 크기에 따라 조금 늘어납니다. 런타임 버전마다 한 번 내는 비용이지만 CI 파이프라인은 배포마다 3분 이상 기다려야 합니다.

운영에서 걸리는 지점도 함께 확인했습니다. `create`와 `update`는 `CREATING`이나 `UPDATING` 상태에서 바로 반환합니다. 종료 상태가 되기 전에 `update`나 `delete`를 호출하면 `ConflictException`이 발생하므로 `get_agent_runtime`을 폴링해야 합니다. 컨테이너는 시작 후 120초 안에 정상 응답해야 하고 넘기면 헬스 체크 오류로 생성이 실패합니다.

출시 이후 바뀐 제약도 있습니다. 환경 변수 총량 한도는 V1과 V2 모두 4 KB가 되었고 서울 리전에서 3,584 B의 환경 변수로 V2 런타임 생성이 성공했습니다. V2는 최대 10 GB의 압축 이미지를 지원하며 2 GB를 넘으면 `resourceConfigurations`의 `minimumMemoryInMiB`를 충분히 크게 정해야 합니다. AWS CloudFormation의 `AWS::BedrockAgentCore::Runtime` 리소스에는 `PlatformVersion` 속성이 추가되었습니다(이 글에서는 배포로 검증하지 않았습니다). AWS CLI는 2.38.5에서 `--platform-version` 옵션을 제공하고 boto3 1.44.2는 `resourceConfigurations`와 `hooksConfiguration`까지 지원합니다. 사용 중인 CLI와 SDK 버전을 먼저 확인하는 것을 권고합니다.

V2 스냅샷은 직접 삭제하지 않습니다. 런타임이나 엔드포인트를 지우면 참조가 끊기고 이미 실행 중인 세션이 끝난 뒤 제거됩니다. 세션 최대 수명인 8시간까지 걸릴 수 있습니다.

## 8. V2로 옮길 때 코드에서 챙길 것

스냅샷 복원은 실행 모델을 바꾸므로 코드 구조에 영향을 줍니다. V2 최적화 가이드의 원칙은 하나입니다. 스냅샷 수명 동안 같은 값이면 시작 시점에 계산하고 요청마다 다르거나 만료될 수 있으면 핸들러에서 계산합니다. 스냅샷 수명은 그 런타임 버전의 수명입니다.

시작 시점에 만든 값은 모든 인스턴스에서 같습니다. 30세션에서 `boot_id`가 2개만 관측된 것이 그 증거입니다. 난수, 식별자, 토큰은 핸들러에서 `os.urandom()`, `secrets`, `uuid.uuid4()`로 생성해야 합니다. `random` 모듈도 시작 시점에 시드되므로 복원된 인스턴스들이 같은 수열을 반복합니다.

암호 라이브러리에는 현재 제약이 있습니다. 최적화 가이드에 따르면 AgentCore Runtime에서는 스냅샷 안전(snapshot-safe) 빌드도 복원 후 다시 시드되지 않으며 직접 코드 배포와 컨테이너 배포 모두 해당합니다. 비밀 값, 키, 세션 식별자는 요청 처리 중에 만들고 난수는 OpenSSL 같은 라이브러리 대신 OS에서 직접 받는 것을 권고합니다. Node.js의 `crypto` 모듈은 OpenSSL을 사용하므로 핸들러 안에서 호출해도 인스턴스 사이에 값이 반복될 수 있습니다. Node.js에서는 `/dev/urandom`을 직접 읽어야 합니다.

`time.monotonic()`은 복원을 넘어 전진하지 않습니다. `uptime_mono_s`가 68초에서 71초에 고정된 것이 그 증거입니다. 시작 시점 기준으로 경과 시간을 재면 틀린 값이 나오고 틀려 보이지도 않으므로, 기준 시각은 핸들러 안에서 잡아야 합니다. hostname과 PID도 인스턴스 식별자로 사용할 수 없습니다. 관측값은 모든 인스턴스에서 `localhost`와 PID 1이었고 이 값으로 메트릭이나 로그 스트림, 락 소유자를 구분하면 전체 플릿이 하나로 뭉개집니다.

시작 시점에 캐시하면 안 되는 값도 있습니다. AgentCore Gateway에서 가져온 도구 카탈로그는 느리고 비싸서 시작 시점 캐싱 후보로 보이지만 캐시하면 도구 목록이 스냅샷 시점에 고정됩니다. 단기 자격 증명도 인스턴스가 시작되기 전에 만료될 수 있습니다. 반대로 boto3 클라이언트처럼 재사용하는 객체는 시작 시점에 만들고 한 번 호출까지 해 두는 것이 좋습니다. 소켓은 복원을 넘지 못하지만 엔드포인트 해석과 커넥션 풀 설정은 스냅샷에 담기고 복원 후 첫 호출이 투명하게 다시 연결합니다. 같은 이유로 고정 소스 포트에 바인딩하지 않아야 합니다.

```python
import os, time
from bedrock_agentcore.runtime import BedrockAgentCoreApp

client = build_client()   # 시작 시점: 재사용 객체는 여기서 만들고 워밍업
warm_up(client)

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload):
    creds = get_credentials()          # 만료 시 갱신, 시작 시점 값 사용 금지
    request_id = os.urandom(16).hex()  # 요청마다 OS에서 새 난수
    t0 = time.monotonic()              # 경과 시간 기준은 핸들러 안에서
    ...

app.run()  # 8080 포트 리슨 후 첫 정상 /ping 시점에 스냅샷 촬영
```

AgentCore SDK는 `app.run()` 전까지 8080 포트를 열지 않으므로 초기화가 끝나기 전에 스냅샷이 촬영되지 않습니다. 직접 HTTP 서버를 운영한다면 초기화가 끝난 뒤에만 `/ping`이 정상을 보고하게 하거나, `hooksConfiguration`의 빌드 워밍업 훅에서 초기화를 실행하는 것을 권고합니다.

## 9. 한계

이 측정은 서울 리전, 계정 1개, 2026년 11월 13일 하루의 결과입니다. 기본값에 대한 관측도 이 계정과 측정 시각에만 해당하며 콘솔의 기본 선택값은 확인하지 않았습니다. 측정 범위는 컨테이너 배포 경로와 PUBLIC 네트워크 모드입니다. 직접 코드(zip) 배포와 VPC 모드는 다루지 않았습니다. 세션 수명이 60초로 짧아서 수십 분 이상 이어지는 세션의 메모리 회수는 확인하지 못했고 약정 기준선, 빌드 워밍업 훅, 2 GB를 넘는 이미지도 측정 범위 밖입니다.

모델을 호출하지 않는 echo 에이전트이므로 플랫폼을 측정한 것이고 에이전트를 측정한 것이 아닙니다. 실제 에이전트에서 사용자가 체감하는 시간은 대부분 에이전트 루프와 모델 호출입니다. 여기서 측정한 cold start는 그 앞에 더해지는 플랫폼 몫입니다. 표본은 cold와 burst가 런타임당 30세션과 50세션이고 탄력 메모리는 레그당 4세션이므로, 방향성은 분명하나 정밀도는 낮습니다. 사용량은 CloudWatch 지표이며 문서도 실제 청구와 다를 수 있다고 밝힙니다. 재현되어야 하는 것은 절대값보다 V1 대 V2의 비율입니다.

## 10. 마치며

글머리의 두 질문에 답하겠습니다. 서울 리전에서 1 GB를 넘는 이미지의 cold start는 V2에서 2초 아래로 내려왔고 2 GB 이미지에서는 27.51초가 1.81초가 되었습니다. 세션 50개가 동시에 도착해도 그 값은 변하지 않았고 30세션의 `boot_id`가 2개로 관측되어 스냅샷 복원이 실제로 일어남을 확인했습니다. 유휴 중 최고점 메모리 과금은 해제한 1.5 GB 스파이크가 0.08 GB만 남는 것으로 답이 나왔습니다. 단가가 42.6%와 78.8% 올랐는데도 같은 워크로드의 총비용은 2 GB 이미지에서 9.8배 낮아졌습니다.

대가는 배포 시간 3분과 코드 구조의 변화입니다. 시작 시점 값은 모든 인스턴스가 공유한다는 원칙 하나만 지키면 난수, 시계, 식별자, 자격 증명 문제는 같은 자리에서 해결됩니다. 기본값 전환 발표가 나왔지만 이 글의 측정 시점에 API는 여전히 V1을 기본으로 만들었습니다. 그러므로 V2를 사용하려면 `platformVersion`을 명시하고 `get-agent-runtime`으로 확인하는 것을 권고합니다. 이미지가 크거나 세션 중 메모리 사용이 들쭉날쭉한 에이전트, 트래픽이 몰리는 시간대가 뚜렷한 에이전트가 V2의 이점을 가장 크게 봅니다. 이런 에이전트라면 서울 리전에서 이 글과 같은 방식으로 자신의 워크로드를 한 번 측정해 보는 것을 권고합니다. 이 글의 측정 방법과 표가 여러분의 AgentCore Runtime V2 전환 검토에 실질적인 참고가 되기를 바랍니다.

## 참고 자료

- [The next generation AgentCore runtime is now the default – What's New (2026년 11월 12일)](https://aws.amazon.com/ko/about-aws/whats-new/2026/11/new-agentcore-runtime-default/)
- [Amazon Bedrock AgentCore에서 이제 새로운 AgentCore Runtime을 사용 가능 – What's New (2026년 9월 18일)](https://aws.amazon.com/ko/about-aws/whats-new/2026/09/new-agentcore-runtime-generally-available/)
- [The new AgentCore runtime: Elastic, optimized, and consistently fast starts – AWS Artificial Intelligence Blog (2026년 9월 18일)](https://aws.amazon.com/ko/blogs/machine-learning/the-new-agentcore-runtime-elastic-optimized-and-consistently-fast-starts/)
- [microVMs (Platform versions) – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html)
- [Optimize your agent for Amazon Bedrock AgentCore Runtime V2 – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-v2-optimize.html)
- [Configure Amazon Bedrock AgentCore lifecycle settings – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [AgentCore generated runtime observability data – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html)
- [Quotas for Amazon Bedrock AgentCore – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- [Release notes for Amazon Bedrock AgentCore – Amazon Bedrock AgentCore Developer Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html)
- [AWS::BedrockAgentCore::Runtime – AWS CloudFormation Template Reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-runtime.html)
- [Amazon Bedrock AgentCore Pricing – 요금 페이지](https://aws.amazon.com/ko/bedrock/agentcore/pricing/)
- [05-measure-your-runtime – awslabs/agentcore-samples (GitHub)](https://github.com/awslabs/agentcore-samples/tree/main/01-features/02-host-your-agent/01-runtime/05-measure-your-runtime)

*본문의 금액은 2026년 11월 12일 게시된 서울 리전 소비 기반 단가와 2026년 11월 13일 서울 리전에서 측정한 사용량으로 계산한 세전 USD 추정치입니다. 지연과 사용량 수치는 계정 1개, 하루의 측정이며 이미지 내용과 계정 이력에 따라 달라질 수 있습니다.*

## 저자 소개

**최우형 (Woohyung Choi)** 님은 AWS Korea의 Principal Solutions Architect로, 국내 주요 엔터프라이즈 및 디지털 기업의 클라우드 전환과 아키텍처 현대화를 지원하고 있습니다. 특히 클라우드 네이티브 아키텍처와 Agentic AI 분야에 전문성을 가지고 있으며, 고객이 Amazon Bedrock을 비롯한 AWS의 생성형 AI 및 Agentic AI 기술을 안정적이고 비용 효율적으로 도입하고 확장할 수 있도록 아키텍처 설계와 기술 자문을 제공하고 있습니다.

컨테이너, 네트워킹, 비용 최적화를 비롯한 클라우드 핵심 기술부터 Agentic AI를 활용한 업무 혁신과 지능형 시스템 구축까지 폭넓은 영역에서 AWS 아키텍처 모범 사례를 제시하고 있습니다. 이를 통해 고객의 복잡한 기술적 과제를 해결하고, AI와 클라우드를 기반으로 지속 가능한 기술 전략을 수립하고 실행할 수 있도록 기술 리더십을 발휘하고 있습니다.

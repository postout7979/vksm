# VCF Agent Portal (프로토타입)

VCF 9.1 Supervisor에 배포되는 에이전트 포드와의 세션 관리, 그리고 VKS 클러스터의
Unmanaged → Managed 전환 및 라이프사이클 관리(리사이즈/롤링 업그레이드/삭제)를
테스트해볼 수 있는 프로토타입입니다. VMware Tanzu Mission Control(TMC-SM)의
"Attach Cluster → 에이전트 배포 → 구성 정보 수집" 흐름을 참고해 구성했습니다.

포탈에는 두 가지 API 표면이 있습니다.

- **데모용 시뮬레이션 API** (`/deploy-agent`, `/register-secret`,
  `/heartbeat`, `/manage`, `/sync`): 실제 클러스터 없이 대시보드를
  눌러보며 테스트할 때 씁니다. 응답 데이터는 `app/agent_sim.py`가
  생성합니다.
- **실제 에이전트 연동 API** (`/agent/bootstrap`, `/agent/register`,
  `/agent/heartbeat`, `/agent/status`, `/agent/report`): `agents/`
  디렉터리의 실제 에이전트 코드와 `k8s/`의 배포 매니페스트가 사용하는
  엔드포인트입니다. 부트스트랩 토큰 → 세션 토큰 교환 방식으로 인증됩니다.

## 에이전트 배포 (실제 클러스터 연동)

`agents/supervisor_agent`와 `agents/vks_agent`는 각각 VCF 9.1 Supervisor,
VKS 클러스터 내부에 배포되는 실제 에이전트 코드입니다. Kubernetes API가
없는 환경(로컬 테스트 등)에서는 자동으로 mock 데이터로 동작하도록
degrade되어 있어, 실제 클러스터 없이도 포탈과의 등록/리포트 흐름을
먼저 검증할 수 있습니다.

### 인증 흐름 (TMC의 Attach Cluster 방식 참고)

1. 관리자가 포탈에서 `POST /api/supervisors/{id}/agent/bootstrap`
   (또는 VKS는 `.../vks-clusters/{id}/agent/bootstrap`)을 호출해
   1회용 **부트스트랩 토큰**을 발급받습니다.
2. 이 토큰을 배포 매니페스트의 Secret에 넣고 `kubectl apply`합니다.
3. 에이전트 파드가 기동하며 부트스트랩 토큰으로 `/agent/register`를
   호출 → 자체적으로 새 **세션 토큰**을 생성해 자신의 네임스페이스에
   Secret으로 저장하고, 그 토큰을 포탈에 등록합니다. 이 시점부터
   부트스트랩 토큰은 서버에서 무효화됩니다.
4. 이후 에이전트는 세션 토큰으로 주기적으로 `/agent/heartbeat`,
   `/agent/status`(Supervisor) 또는 `/agent/report`(VKS)를 호출합니다.

### Supervisor 에이전트 배포

```bash
# 1) 포탈에 Supervisor 등록 후 id 확인
curl -X POST $PORTAL_URL/api/supervisors \
  -H "Content-Type: application/json" \
  -d '{"name":"vcf-seoul-dc01","vcf_instance":"sc-seoul-01"}'

# 2) 부트스트랩 토큰 발급
curl -X POST $PORTAL_URL/api/supervisors/<id>/agent/bootstrap

# 3) 이미지 빌드
cd agents/supervisor_agent
docker build -t <registry>/supervisor-agent:latest .
docker push <registry>/supervisor-agent:latest

# 4) k8s/supervisor-agent.yaml의 REPLACE_* 값을 채운 뒤 적용
kubectl apply -f ../../k8s/supervisor-agent.yaml --context <supervisor-context>
```

### VKS 에이전트 배포

```bash
# 1) 포탈에서 해당 VKS 클러스터를 관리 대상으로 전환 (부트스트랩 토큰 발급 겸용)
curl -X POST $PORTAL_URL/api/vks-clusters/<id>/agent/bootstrap

# 2) 이미지 빌드
cd agents/vks_agent
docker build -t <registry>/vks-agent:latest .
docker push <registry>/vks-agent:latest

# 3) k8s/vks-agent.yaml의 REPLACE_* 값을 채운 뒤 적용
kubectl apply -f ../../k8s/vks-agent.yaml --context <vks-cluster-context>
```

에이전트 코드를 클러스터 없이 로컬에서 바로 테스트하고 싶다면 (포탈만
떠 있으면 됨):

```bash
pip install requests
PORTAL_URL=http://localhost:8000 \
SUPERVISOR_ID=1 \
BOOTSTRAP_TOKEN=<위에서 발급받은 토큰> \
python agents/supervisor_agent/main.py
```

`kubernetes` 패키지가 없거나 클러스터 밖에서 실행되면 Node/Namespace
수집 대신 mock 데이터로 동작하며, 포탈과의 등록/heartbeat/상태 보고
흐름 자체는 그대로 검증됩니다.

## 구성

- **백엔드**: FastAPI
- **DB**: SQLite (SQLAlchemy를 통해 Python에서 직접 다루는 파일 기반 DB, 별도
  DB 서버 불필요) — 컨테이너 안 `/data/portal.db`에 저장되며 Docker 볼륨으로
  영속화됩니다.
- **프론트엔드**: 정적 HTML/JS 대시보드 (`/static`) — API를 그대로 호출해서
  카드 UI로 보여주는 테스트용 화면입니다. `/docs`에서 Swagger UI로도 모든
  API를 직접 테스트할 수 있습니다.

## 도커로 실행하기

```bash
docker compose up --build
```

실행 후 접속:

- 테스트 대시보드: http://localhost:8000/
- API 문서(Swagger): http://localhost:8000/docs

`docker compose`가 없다면 아래처럼 직접 빌드/실행해도 됩니다.

```bash
docker build -t vcf-agent-portal .
docker run -p 8000:8000 -v vcf-agent-portal-data:/data vcf-agent-portal
```

컨테이너를 처음 띄우면 데모용 Supervisor 2개와 VKS 클러스터 3개가 자동으로
시드(seed)됩니다 (`app/seed.py`).

## 주요 API

### Supervisor (에이전트 포드 / Secret / 세션)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/supervisors` | Supervisor 목록 |
| POST | `/api/supervisors` | Supervisor 등록 |
| POST | `/api/supervisors/{id}/deploy-agent` | 에이전트 포드 배포(시뮬레이션) |
| POST | `/api/supervisors/{id}/register-secret` | 에이전트가 생성한 Secret 등록 → 세션 연결 |
| POST | `/api/supervisors/{id}/heartbeat` | 세션 유지용 heartbeat |
| DELETE | `/api/supervisors/{id}` | Supervisor 삭제 |

### VKS 클러스터 (Unmanaged → Managed 및 라이프사이클)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/vks-clusters` | 클러스터 목록 (`?supervisor_id=`로 필터) |
| POST | `/api/vks-clusters` | 클러스터 등록 (초기 상태: unmanaged) |
| GET | `/api/vks-clusters/{id}` | 클러스터 상세 (수집된 inventory 포함) |
| POST | `/api/vks-clusters/{id}/manage` | VKS용 에이전트 포드 배포 + 구성/배포 정보 수집 |
| POST | `/api/vks-clusters/{id}/unmanage` | 에이전트 포드 제거, 수집 중단 |
| POST | `/api/vks-clusters/{id}/sync` | 인벤토리 재수집 |
| POST | `/api/vks-clusters/{id}/resize` | 컨트롤플레인/워커 노드 수 변경 |
| POST | `/api/vks-clusters/{id}/upgrade` | 롤링 업그레이드(버전 변경) |
| DELETE | `/api/vks-clusters/{id}` | 클러스터 삭제 |

### 실제 에이전트 연동 API

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/supervisors/{id}/agent/bootstrap` | 부트스트랩 토큰 발급 |
| POST | `/api/supervisors/{id}/agent/register` | 에이전트 최초 등록 (Bearer: 부트스트랩 토큰) |
| POST | `/api/supervisors/{id}/agent/heartbeat` | 세션 유지 (Bearer: 세션 토큰) |
| POST | `/api/supervisors/{id}/agent/status` | 운영 상태 보고 (Bearer: 세션 토큰) |
| GET | `/api/supervisors/{id}/status` | 최근 보고된 운영 상태 조회 |
| POST | `/api/vks-clusters/{id}/agent/bootstrap` | 부트스트랩 토큰 발급 (cluster → pending) |
| POST | `/api/vks-clusters/{id}/agent/register` | 에이전트 최초 등록 (Bearer: 부트스트랩 토큰) |
| POST | `/api/vks-clusters/{id}/agent/report` | 구성/배포 인벤토리 보고 (Bearer: 세션 토큰, cluster → managed) |

## 다음 단계로 고려할 것

- 업그레이드를 실제로는 비동기 롤아웃으로 처리하고, 에이전트가 진행률을
  콜백/폴링으로 보고하도록 확장 (현재는 즉시 완료로 단순화됨)
- 세션 토큰 회전(rotation), TLS 종단 간 암호화, 멀티 테넌시(조직/클러스터
  그룹) 추가
- `inventory_json` 단일 컬럼을 네임스페이스/워크로드/애드온 전용 테이블로 정규화
- `agents/supervisor_agent`에서 VCF/Supervisor 전용 CRD(WCP 네임스페이스,
  ResourcePool, StoragePolicy 등) 수집기 추가
- 스키마 변경 시 이 프로토타입은 Alembic 같은 마이그레이션 도구가 없으므로,
  기존 볼륨을 쓰던 중이라면 `docker compose down -v`로 볼륨을 초기화하고
  다시 띄워야 합니다.

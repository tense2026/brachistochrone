# GitHub 업로드 → Docker 연결 전체 계획

현재 상태: 코드가 `tense2026/brachistochrone` 저장소의 `ccr-64330027-why8pr` 브랜치에
푸시되어 있습니다. Dockerfile, docker-compose.yml, CI 워크플로가 모두 포함돼 있습니다.

---

## 0단계. 지금 어디까지 돼 있나

| 항목 | 상태 |
|---|---|
| 코드 + 결과 + 수정 사항 | 푸시 완료 (`ccr-64330027-why8pr`) |
| `Dockerfile` | 작성 완료, 빌드 단계에서 테스트 21개 실행 |
| `docker-compose.yml` | 작성 완료 (`study`, `tests` 서비스) |
| `.github/workflows/ci.yml` | 작성 완료 (테스트 + 이미지 빌드 + 스모크 런) |
| `requirements.txt` 버전 고정 | 완료 |
| Docker 계정 | **없음 — 아래 2단계에서 결정** |
| 로컬 `docker build` 실제 실행 | **아직 안 됨** — 이 작업 환경에 Docker 데몬이 없어
  동일한 단계를 Python 3.13 + 고정 버전으로 따라 검증만 했습니다. 본인 PC에서 1회 빌드 필요 |

---

## 1단계. main 브랜치로 합치기

지금은 작업 브랜치에만 있습니다. 둘 중 하나를 고르세요.

**방법 A — Pull Request (추천, 기록이 남음)**

1. https://github.com/tense2026/brachistochrone 접속
2. 상단에 뜨는 `ccr-64330027-why8pr ... Compare & pull request` 버튼 클릭
3. 제목/설명 확인 후 `Create pull request`
4. CI(Actions)가 초록색으로 통과하는지 확인 → `Merge pull request`

**방법 B — 바로 합치기 (혼자 쓰는 저장소면 충분)**

```bash
git clone https://github.com/tense2026/brachistochrone.git
cd brachistochrone
git checkout main
git merge ccr-64330027-why8pr
git push origin main
```

> PR을 만들어 달라고 하시면 제가 만들어 드릴 수 있습니다. 명시적으로 요청하지 않으셨기
> 때문에 지금은 만들지 않았습니다.

---

## 2단계. Docker 계정 — 꼭 필요한가?

**결론: 세 가지 선택지가 있고, 1번이 가장 간단합니다.**

### 선택지 1 — 계정 없이 로컬에서만 쓰기 (가장 간단)

이미지를 인터넷에 올릴 필요가 없다면 **Docker 계정이 아예 필요 없습니다.**
Docker Desktop(또는 Linux의 docker engine)만 설치하면 `docker build` / `docker run`이
전부 동작합니다. 연구 재현 목적이라면 이것으로 충분합니다.

- 필요한 것: Docker Desktop 설치뿐
- 못 하는 것: 다른 사람에게 이미지 링크로 공유

### 선택지 2 — GitHub Container Registry (GHCR) 사용 (공유까지 원할 때 추천)

**이미 GitHub 계정이 있으니 Docker Hub 계정을 새로 만들 필요가 없습니다.**
GHCR은 GitHub에 내장된 컨테이너 저장소이고, GitHub Actions가 자동 인증되므로
비밀번호/토큰을 따로 등록하지 않아도 됩니다.

- 이미지 주소: `ghcr.io/tense2026/brachistochrone:latest`
- 비용: 공개 이미지는 무료
- 설정: 아래 4단계의 워크플로 하나만 추가

### 선택지 3 — Docker Hub 계정 만들기

꼭 Docker Hub를 쓰고 싶다면:

1. https://hub.docker.com/signup 에서 가입 (이메일 인증 필요)
2. Docker ID를 정합니다 — 이게 이미지 이름 앞에 붙습니다 (`<DockerID>/brachistochrone`)
3. 로그인 후 `Account settings → Personal access tokens → Generate new token`
   - 권한: `Read & Write`
   - 생성된 토큰은 **한 번만 보이므로 바로 복사**
4. GitHub 저장소 → `Settings → Secrets and variables → Actions → New repository secret`
   - `DOCKERHUB_USERNAME` = Docker ID
   - `DOCKERHUB_TOKEN` = 복사한 토큰
5. 무료 플랜 주의: 공개 저장소 1개는 무료지만, 비공개 저장소 수와 이미지 보존 정책에
   제한이 있습니다. GHCR이 이 프로젝트에는 더 유리합니다.

> **추천: 선택지 1로 시작해서, 공유가 필요해지면 선택지 2(GHCR)로 넘어가세요.**
> Docker Hub 계정은 만들지 않아도 됩니다.

---

## 3단계. 로컬에서 Docker 돌려보기 (계정 불필요)

### 3-1. Docker 설치

- Windows / macOS: https://www.docker.com/products/docker-desktop 에서 Docker Desktop 설치
  (설치 시 계정 가입을 권유하지만 **건너뛸 수 있습니다**)
- Linux: `curl -fsSL https://get.docker.com | sh` 후 `sudo usermod -aG docker $USER` 하고
  로그아웃/로그인
- 설치 확인: `docker run --rm hello-world`

### 3-2. 빌드

```bash
cd brachistochrone
docker build -t brachistochrone-study:latest .
```

빌드 중 `python -m unittest -q test_project test_magnus`가 실행됩니다.
**테스트가 실패하면 빌드가 거기서 멈춥니다** — 물리 모델이 깨진 이미지가
만들어지지 않도록 일부러 그렇게 뒀습니다.

### 3-3. 실행

```bash
# 저장된 결과와 같은 설정으로 전체 재현 (약간 시간이 걸립니다)
mkdir -p out
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/out:/app/out" \
  brachistochrone-study:latest

# 결과 확인
cat out/summary.csv
```

`out/`에 PNG 8장과 CSV, JSON이 생성됩니다.

```bash
# 테스트만 실행
docker run --rm brachistochrone-study:latest -m unittest -v test_project test_magnus

# 설정을 바꿔 실행 (ENTRYPOINT가 python이므로 스크립트 이름부터 적습니다)
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/out:/app/out" \
  brachistochrone-study:latest \
  variable_study.py --episodes 50 --pop-size 10 --no-show --output-dir /app/out
```

### 3-4. docker compose로 더 짧게

```bash
docker compose run --rm study   # 전체 실험
docker compose run --rm tests   # 테스트만
```

### 3-5. 재현성 확인 (중요)

컨테이너에서 나온 결과가 저장소의 결과와 같은지 직접 대조해 보세요.

```bash
diff out/summary.csv variable_results/summary.csv && echo "완전히 동일"
```

seed가 고정돼 있어 같아야 합니다. 저는 이 환경에서 바이트 단위로 동일함을 확인했습니다.

---

## 4단계. GHCR에 올려 공유하기 (선택지 2를 고를 때만)

`.github/workflows/publish.yml` 파일을 새로 만드세요.

```yaml
name: Publish image

on:
  push:
    branches: ["main"]
    tags: ["v*"]
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write          # GHCR에 쓰기 권한. 별도 토큰이 필요 없는 이유입니다.
    steps:
      - uses: actions/checkout@v4

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}   # 자동 제공되는 토큰

      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=sha
            type=raw,value=latest,enable={{is_default_branch}}

      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

커밋하고 `main`에 푸시하면 Actions가 자동으로 이미지를 빌드해서 올립니다.

처음 올린 뒤 **공개로 바꾸는 작업이 한 번 필요합니다**(기본값은 비공개):

1. https://github.com/tense2026?tab=packages 접속
2. `brachistochrone` 패키지 클릭
3. `Package settings → Danger Zone → Change visibility → Public`

그 뒤로는 누구나 이렇게 쓸 수 있습니다.

```bash
docker pull ghcr.io/tense2026/brachistochrone:latest
docker run --rm -v "$PWD/out:/app/out" ghcr.io/tense2026/brachistochrone:latest
```

README에 이 두 줄을 넣어두면 재현 방법이 명확해집니다.

---

## 5단계. GUI 재생 창은 어떻게?

컨테이너는 **화면이 없어서** `--replay-only` 재생 창이 뜨지 않습니다. 이건 의도된
설계입니다(배치 재현 전용). 재생 창을 보려면 두 가지 방법이 있습니다.

**방법 A — 호스트에서 직접 실행 (추천)**

```bash
pip install -r requirements.txt
python brachistochrone.py --replay-only --output-dir variable_results/06_all
```

**방법 B — X11 전달 (Linux 전용, 번거로움)**

```bash
xhost +local:docker
docker run --rm -e DISPLAY=$DISPLAY -e MPLBACKEND=TkAgg \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v "$PWD/variable_results:/app/variable_results" \
  brachistochrone-study:latest \
  brachistochrone.py --replay-only --output-dir variable_results/06_all
xhost -local:docker
```

이 경우 Dockerfile에 `python3-tk`를 추가로 설치해야 합니다
(`RUN apt-get update && apt-get install -y --no-install-recommends python3-tk`).
굳이 필요하지 않다면 방법 A를 쓰세요.

---

## 전체 순서 요약

```
1. PR 만들거나 main에 머지                    ← GitHub 웹 또는 git merge
2. Docker Desktop 설치                        ← 계정 가입 건너뛰기 가능
3. docker build -t brachistochrone-study .    ← 빌드 중 테스트 21개 통과 확인
4. docker run ... -v "$PWD/out:/app/out"      ← out/summary.csv 생성
5. diff out/summary.csv variable_results/...  ← 재현성 확인
6. (공유 원하면) publish.yml 추가 → GHCR      ← Docker Hub 계정 불필요
7. (GUI 보려면) 호스트에서 --replay-only      ← 컨테이너 밖에서
```

---

## 막힐 수 있는 지점

| 증상 | 원인과 해결 |
|---|---|
| `permission denied` (out/ 에 쓰기 실패) | 컨테이너가 uid 1000으로 돌아갑니다. `--user "$(id -u):$(id -g)"` 추가 |
| `cannot connect to the Docker daemon` | Docker Desktop이 실행 중인지 확인. Linux는 `sudo systemctl start docker` |
| 빌드가 테스트에서 멈춤 | 물리 모델이 깨졌다는 뜻입니다. 로그의 실패한 테스트 이름을 확인하세요 |
| `no display name` / `TclError` | `MPLBACKEND=Agg`와 `--no-show`를 쓰세요. 이미지에는 이미 설정돼 있습니다 |
| GHCR push가 403 | 워크플로에 `permissions: packages: write`가 있는지 확인 |
| `docker pull`이 `unauthorized` | 패키지가 아직 비공개입니다. 4단계의 visibility 변경을 하세요 |
| 결과가 저장된 CSV와 다름 | `--episodes 180 --pop-size 20 --height 5 --length 10`과 seed=42를 모두 맞췄는지 확인 |

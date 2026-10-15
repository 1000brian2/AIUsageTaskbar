# AI & PC Monitor (AIUsageTaskbar)

Windows 11 작업 표시줄에 완벽하게 밀착되는 **AI 실시간 사용량(Codex / Gemini) & PC 성능 통합 모니터**입니다.

외부 무거운 라이브러리 없이 순수 Python 표준 라이브러리와 Windows Native Win32 API(`ctypes`)만으로 제작되어 **CPU 0.0% / RAM 초경량**으로 동작합니다.

---

## ✨ 핵심 기능

### 1. 🔋 작업 표시줄 슬림 독 (Taskbar Dock)
- **우로 밀착 (Snap-to-Right)**: 트레이 영역의 시스템 아이콘(`^`) 바로 왼쪽에 겹침 없이 밀착 배치됩니다.
- **듀얼 모니터 지원**: 주 모니터뿐만 아니라 보조 모니터의 작업 표시줄 시계 영역 옆에도 자동으로 동일한 위젯이 동기화 배치됩니다.
- **배터리 잔여 게이지 & 브랜드 컬러**:
  - **GPT** (Emerald `#10B981`): ChatGPT / Codex 잔여량 배터리
  - **GEM** (Royal Blue `#3B82F6`): Gemini 잔여량 배터리
  - **RAM** (Slate `#94A3B8`): PC 실시간 메모리 사용률

### 2. ⚡ 마우스 호버 예측 요약 카드 (Hover Card)
- 작업 표시줄 위젯에 마우스 커서를 올리면 위로 부드럽게 팝업 카드가 나타납니다.
- **5시간(5H) / 주간(WK) 사용량 게이지 바**: 남은 비율(%) 및 사용 비율(%)
- **초기화 타이머**: 다음 한도 리셋까지 남은 시간 실시간 카운트다운
- **소비 속도 분석 (`%/h`) & 소진 예측**:
  - 최근 사용량을 추적하여 시간당 소비율 계산
  - 현재 속도 유지 시 초기화 시각 이전에 소진될 위험이 있는지 능동 진단
- **PC 시스템 성능**: RAM, CPU 점유율, 메인보드/CPU 센서 온도, 실시간 네트워크(↓/↑) 속도

### 3. 📊 상세 카드 창 (Full Detail Window)
- 작업 표시줄 독을 클릭하면 전체 상세 모니터 대시보드가 열립니다.
- 창 닫기(`X`) 클릭 시 **"작업 표시줄에 켜두기(최소화)"** 또는 **"프로그램 완전 종료"**를 선택할 수 있습니다.

---

## 🛠️ 요구 사양 & 작동 원리

- **OS**: Windows 10 / Windows 11 (Windows 11 테스크바 최적화)
- **Python**: Python 3.10 이상
- **외부 의존성(pip)**: **0개 (Zero Pip Dependencies)**
  - 표준 라이브러리(`tkinter`, `ctypes`, `urllib`, `json` 등)만으로 구동
- **AI 연동 방식**:
  - **Codex / ChatGPT**: 로컬에 설치된 Codex CLI의 로컬 app-server IPC(`stdio JSON-RPC`)를 통해 안전하게 잔여량 조회
  - **Gemini**: 로컬 개발 환경(Antigravity Language Server)의 로컬 포트와 통신하여 실시간 쿼터 조회
  - *외부 서버로 API 키나 개인정보를 전송하지 않으며, 로컬 프로세스 간 통신만 사용합니다.*

---

## 🚀 빠른 시작 (Quick Start)

### 1. 저장소 복제 (Clone)
```bash
git clone https://github.com/<your-username>/AIUsageTaskbar.git
cd AIUsageTaskbar
```

### 2. 바탕화면 및 시작 메뉴 바로가기 생성
```bash
python install.py
```

### 3. 실행
```bash
# 콘솔 창 없이 백그라운드로 실행
python launch_app.py

# 또는 배치 파일 실행
launch_widget.bat
```

---

## ⚙️ 설정 & 메뉴

- 작업 표시줄 독을 **우클릭**하면 컨텍스트 메뉴가 열립니다:
  - 🔄 **AI 사용량 새로고침**: 즉시 최신 잔여량 재조회
  - 📊 **AI & PC 모니터 창 열기**: 전체 상세 카드 창 표시
  - ⚙️ **설정**: 자동 갱신 주기(1분, 5분, 10분, 15분, 30분) 및 닫기 동작 설정
  - ❌ **프로그램 종료**: 백그라운드 프로세스 완전 종료

---

## 📄 라이선스 (License)

이 프로젝트는 [MIT License](LICENSE)를 따릅니다.

> **Disclaimer**: 본 프로그램은 비공식 커뮤니티 오픈소스 프로젝트입니다. OpenAI, Codex, ChatGPT, Google, Gemini 상표는 각 사의 자산입니다.

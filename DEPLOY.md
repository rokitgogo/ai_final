# 외부 접속 설정 (학생들이 밖에서 접속)

같은 Wi-Fi가 아닌 **밖(집, 학원 등)**에서 접속하려면 앱을 **인터넷에 공개**해야 합니다.

---

## 방법 1: Streamlit Community Cloud (추천, 무료)

앱을 24시간 인터넷에 올려두면 학생들이 **어디서나** 접속 가능합니다.

### 1단계: GitHub에 올리기

1. [GitHub](https://github.com) 가입 (없으면)
2. 새 저장소(Repository) 생성
3. 프로젝트 폴더 내용을 모두 업로드 (Push)

### 2단계: Streamlit Cloud에 배포

1. [share.streamlit.io](https://share.streamlit.io) 접속
2. GitHub로 로그인
3. **"New app"** 클릭
4. 저장소 선택, 메인 파일: `app.py`, 브랜치: `main`
5. **Advanced settings** → Secrets에 추가 (Gemini API 사용 시):
   ```toml
   GOOGLE_API_KEY = "여기에_API_키"
   ```
6. **Deploy** 클릭

### 3단계: URL 공유

배포 완료 후 예시:
```
https://your-app-name.streamlit.app
```
이 주소를 학생들에게 전달하면 **어디서나 폰·PC**로 접속 가능합니다.

---

## 방법 2: ngrok (PC 켜둔 동안만, 무료)

교사 PC에서 앱을 실행한 상태에서 **임시로** 외부 접속을 열 때 사용합니다.

### 1단계: ngrok 설치

1. [ngrok.com](https://ngrok.com) 가입
2. [다운로드](https://ngrok.com/download) 후 압축 해제
3. (선택) `ngrok config add-authtoken 본인토큰` 실행

### 2단계: 실행 순서

1. **run_app.bat**로 Streamlit 실행
2. 새 터미널에서:
   ```bash
   ngrok http 8501
   ```
3. ngrok이 만들어 준 `https://xxxx.ngrok-free.app` 주소를 학생들에게 공유

### ⚠️ 제한사항

- **PC가 켜져 있고 앱이 실행 중일 때만** 접속 가능
- 무료 버전은 실행할 때마다 URL이 바뀜 (유료는 고정 URL 가능)

---

## 비교

| | Streamlit Cloud | ngrok |
|---|---|---|
| **접속 가능 시간** | 24시간 | PC 켜진 동안만 |
| **URL** | 고정 | 매번 변경 (무료) |
| **설치** | 없음 (브라우저만) | ngrok 설치 필요 |
| **학생 밖에서 접속** | ✅ | ✅ |

→ **학생들이 언제든 접속해야 하면** Streamlit Cloud 사용을 권장합니다.

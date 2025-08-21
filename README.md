# 📝 Mock Coding Test Automation for BOJ

이 프로젝트는 **모의 코딩 테스트 환경**을 자동으로 구성하고,  
참가자가 **로그인 → 테스트 → 제출**까지 쉽게 진행할 수 있도록 돕는 스크립트입니다.

---

## 📦 주요 기능

1. **필요한 Python 패키지 자동 설치**
   - `requests`, `PyYAML`, `html2text`, `boj-cli` 등 자동 체크 후 설치
   - 이는 test.py를 최초 실행할때 설치됩니다.

2. **BOJ 로그인**
   - `boj login` 자동 실행
   - 최초 1회 로그인 후, 이후 `boj submit`을 바로 사용할 수 있음

3. **문제 폴더 자동 생성**
   - `problems/문제번호/` 구조
   - `main.py` (풀이 파일), `PROBLEM.md` (문제 설명), `testcases/` 포함

4. **헬퍼 스크립트 생성**
   - 각 문제 폴더에 자동으로 `test.py`, `test.bat`, `test.sh` 생성
   - `test.py` 실행 시:
     1) BOJ 로그인 확인/진행  
     2) `boj run`으로 샘플 테스트 실행  
     3) 바로 `boj submit` 제출  
---

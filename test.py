#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
test.py — one-shot 부트스트랩 + BOJ 로그인 + 시험 세팅 스크립트

흐름
1) 필요한 패키지 설치 (requests / PyYAML / html2text / boj-cli)
2) BOJ 로그인(최초 1회) — 이후 세션 유지
3) 시험 세팅 (exam-code / 난이도 / 언어)
   - solved.ac에서 버킷별 후보 수집(또는 기존 pool/ 재사용)
   - 결정론적으로 문제 3개 선택
   - problems/<문제번호>/ 생성 + main 파일 + PROBLEM.md + testcases 시도
   - .boj/config.yaml 자동 구성(언어별 run 명령 포함)
4) 안내 출력
   - 각 문제 폴더로 이동해서 `boj run` → 풀이 후 `boj submit` 바로 가능(로그인 완료되어 있음)
"""

# ------------------------------------------------------------
# 0) 부트스트랩: 패키지 설치
# ------------------------------------------------------------
import sys, subprocess, shutil, os, platform, time, re, json, random, hashlib
from datetime import datetime
from html import unescape
from typing import Dict, List, Tuple

def _pip_install(*pkgs):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])
    except Exception as e:
        print(f"[error] pip install 실패: {pkgs}\n{e}")
        raise

# 필수 파이썬 패키지
try:
    import requests  # noqa
except Exception:
    _pip_install("requests>=2.31")
    import requests

try:
    import yaml  # noqa
except Exception:
    _pip_install("PyYAML>=6.0")
    import yaml

try:
    import html2text  # noqa
except Exception:
    _pip_install("html2text>=2020.1.16")
    import html2text

# boj-cli 확인/설치
if shutil.which("boj") is None:
    _pip_install("boj-cli>=1.2")

# boj 실행 커맨드 (PATH에 없으면 python -m boj)
BOJ_CMD = ["boj"] if shutil.which("boj") else [sys.executable, "-m", "boj"]

# ------------------------------------------------------------
# 1) solved.ac / 공통 유틸
# ------------------------------------------------------------
SOLVED_AC_SEARCH = "https://solved.ac/api/v3/search/problem"

TIER_ORDER = [
    "B5","B4","B3","B2","B1",
    "S5","S4","S3","S2","S1",
    "G5","G4","G3","G2","G1",
    "P5","P4","P3","P2","P1",
    "D5","D4","D3","D2","D1",
    "R5","R4","R3","R2","R1",
]
TIER_TO_LEVEL = {name: i+1 for i, name in enumerate(TIER_ORDER)}

DEFAULT_BUCKETS = {
    "veasy":  ("B2~S5", 1),
    "easy":   ("S4~S2", 1),
    "mid":    ("S1~G5", 1),
    "hard":   ("G4~G1", 1),
    "insane": ("P5~P1", 1),
}
DIFFICULTY_PRESETS = {
    "easy": ["veasy", "easy", "mid"],
    "mid":  ["easy",  "mid",  "hard"],
    "hard": ["mid",   "hard", "insane"],
}

def parse_tier_range(expr: str) -> Tuple[int, int]:
    s = expr.replace(" ", "").upper()
    if "~" in s:
        a, b = s.split("~", 1)
        if a not in TIER_TO_LEVEL or b not in TIER_TO_LEVEL:
            raise ValueError(f"잘못된 tier 표기: {expr}")
        lo, hi = TIER_TO_LEVEL[a], TIER_TO_LEVEL[b]
        if lo > hi: lo, hi = hi, lo
        return lo, hi
    else:
        if s not in TIER_TO_LEVEL:
            raise ValueError(f"잘못된 tier 표기: {expr}")
        v = TIER_TO_LEVEL[s]
        return v, v

def tier_name(level: int) -> str:
    idx = max(1, min(30, level)) - 1
    return TIER_ORDER[idx]

def build_query(tier_expr: str, tags: List[str]) -> str:
    lo, hi = parse_tier_range(tier_expr)
    q = [f"tier:{lo}..{hi}"]
    for t in tags:
        t = t.strip()
        if t: q.append(f"tag:{t}")
    return " ".join(q)

def fetch_candidates(query: str, max_pages: int = 3, size: int = 100) -> List[Dict]:
    items_all: List[Dict] = []
    for page in range(1, max_pages+1):
        r = requests.get(SOLVED_AC_SEARCH, params={"query": query, "page": page, "size": size}, timeout=12)
        if r.status_code != 200:
            print(f"[warn] solved.ac 응답 {r.status_code}: {r.text[:200]}")
            break
        data = r.json()
        items = data.get("items", [])
        items_all.extend(items)
        if len(items) < size: break
    items_all.sort(key=lambda x: x.get("problemId", 0))
    uniq = {}
    for it in items_all:
        pid = it.get("problemId")
        if pid and pid not in uniq:
            uniq[pid] = it
    return list(uniq.values())

def save_json(path: str, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_json(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ------------------------------------------------------------
# 2) BOJ 설정 파일(.boj/config.yaml) 유틸
# ------------------------------------------------------------
def find_boj_config_path() -> str:
    cwd_conf = os.path.join(os.getcwd(), ".boj", "config.yaml")
    if os.path.exists(cwd_conf):
        return cwd_conf
    return os.path.expanduser("~/.boj/config.yaml")

def load_boj_config():
    path = find_boj_config_path()
    conf = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                conf = yaml.safe_load(f) or {}
        except Exception:
            conf = {}
    return conf, path

def get_ongoing_dir() -> str:
    conf, _ = load_boj_config()
    ws = (conf or {}).get("workspace", {})
    return ws.get("ongoing_dir", "problems") or ""

def resolve_problem_dir(problem_id: int) -> str:
    ongoing_dir = get_ongoing_dir()
    if os.path.isabs(ongoing_dir):
        base_dir = ongoing_dir
    elif ongoing_dir in ("", "."):
        base_dir = os.getcwd()
    else:
        base_dir = os.path.join(os.getcwd(), ongoing_dir)
    return os.path.join(base_dir, str(problem_id))

def switch_boj_default_filetype(lang_key: str):
    conf_path = find_boj_config_path()
    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    try:
        with open(conf_path, "r", encoding="utf-8") as f:
            conf = yaml.safe_load(f) or {}
    except Exception:
        conf = {}

    conf.setdefault("general", {})
    conf.setdefault("workspace", {})
    conf.setdefault("filetype", {})

    conf["workspace"].setdefault("ongoing_dir", "problems")
    conf["workspace"].setdefault("archive_dir", "solved")

    is_windows = platform.system().lower().startswith("win")
    py_run = "python main.py" if is_windows else "python3 main.py"
    cpp_run = "main.exe" if is_windows else "./main"

    ft = conf["filetype"]
    ft.setdefault("py", {
        "language": "python3",
        "main": "main.py",
        "compile": "",
        "run": py_run,
    })
    ft.setdefault("cpp", {
        "language": "c++17",
        "main": "main.cc",
        "compile": "g++ -std=c++17 -O2 -o main main.cc",
        "run": cpp_run,
    })
    ft.setdefault("java", {
        "language": "java11",
        "main": "Main.java",
        "compile": "javac Main.java",
        "run": "java Main",
    })

    if lang_key in ("py","cpp","java"):
        conf["general"]["default_filetype"] = lang_key

    with open(conf_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(conf, f, allow_unicode=True, sort_keys=False)

    print(f"[ok] {conf_path} 기본 언어를 '{lang_key}'로 설정했습니다.")

# ------------------------------------------------------------
# 3) BOJ 로그인 / 실행 유틸
# ------------------------------------------------------------
def _run(cmd, cwd=None):
    return subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=cwd)

def is_boj_logged_in() -> bool | None:
    """
    boj-cli가 'whoami'를 지원하면 True/False를 반환.
    지원하지 않으면 None을 반환(확인 불가).
    """
    help_out = _run(BOJ_CMD + ["help"])
    if help_out.returncode == 0 and "whoami" in (help_out.stdout or ""):
        r = _run(BOJ_CMD + ["whoami"])
        # whoami가 존재할 때만 판정. 출력이 있으면 로그인된 것으로 간주.
        return r.returncode == 0 and bool((r.stdout or "").strip())
    # whoami 미지원 버전: 확인 불가
    return None

def ensure_boj_login():
    """
    1) whoami가 있으면 먼저 체크해서 이미 로그인되어 있으면 패스
    2) 아니면(미지원/불확실) 'boj login' 실행
    3) 'boj login'이 0으로 끝나면 로그인 성공으로 간주(재확인 생략)
    """
    status = is_boj_logged_in()
    if status is True:
        print("[i] 이미 백준에 로그인되어 있습니다.")
        return

    if status is None:
        print("[i] 백준 로그인 상태를 확인할 수 없습니다. 로그인 절차를 진행합니다.")
    else:
        print("[i] 백준 로그인이 필요합니다. 계정 정보를 입력해 주세요.")

    r = _run(BOJ_CMD + ["login"])
    if r.returncode != 0:
        # boj-cli가 브라우저 로그인 실패시 여기로 옴
        msg = (r.stderr or r.stdout or "").strip()
        if msg:
            print(msg)
        raise SystemExit("[err] 로그인 실패. 다시 시도해 주세요.")

    # 여기서는 boj login이 성공 종료됨 → 바로 성공으로 간주
    print("[ok] 로그인 성공! 이제 'boj submit'이 즉시 가능합니다.")

# ------------------------------------------------------------
# 4) BOJ 문제 페이지 → Markdown
# ------------------------------------------------------------
def _http_get_with_headers(url: str, tries: int = 3, timeout: int = 12) -> str:
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/122.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.acmicpc.net/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    last_err = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.text
            last_err = f"{r.status_code} {r.reason}"
        except Exception as e:
            last_err = str(e)
        time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"GET 실패: {last_err}")

def _extract_div(html: str, div_id: str) -> str:
    m = re.search(rf'<div id="{re.escape(div_id)}"[^>]*>(.*?)</div>', html, re.S | re.I)
    return m.group(1).strip() if m else ""

def fetch_problem_sections(problem_id: int) -> Dict[str, str]:
    url = f"https://www.acmicpc.net/problem/{problem_id}"
    try:
        html = _http_get_with_headers(url)
        desc_html   = _extract_div(html, "problem_description")
        input_html  = _extract_div(html, "problem_input")
        output_html = _extract_div(html, "problem_output")
        sample_inputs  = re.findall(r'<pre[^>]*id="sample-input-\d+"[^>]*>(.*?)</pre>', html, re.S | re.I)
        sample_outputs = re.findall(r'<pre[^>]*id="sample-output-\d+"[^>]*>(.*?)</pre>', html, re.S | re.I)

        h2t = html2text.HTML2Text()
        h2t.ignore_links = False
        h2t.body_width = 0

        def to_md(h: str) -> str:
            if not h: return ""
            return h2t.handle(unescape(h)).strip()

        return {
            "url": url,
            "description": to_md(desc_html) or "(설명을 가져오지 못했습니다.)",
            "input": to_md(input_html),
            "output": to_md(output_html),
            "samples_in": [to_md(s) for s in sample_inputs],
            "samples_out": [to_md(s) for s in sample_outputs],
        }
    except Exception as e:
        return {
            "url": url,
            "description": f"(문제 페이지 요청 오류: {e})",
            "input": "",
            "output": "",
            "samples_in": [],
            "samples_out": [],
        }

def write_problem_md(problem_dir: str, problem_id: int, title: str):
    sec = fetch_problem_sections(problem_id)
    lines: List[str] = []
    lines.append(f"# [{problem_id}] {title}")
    lines.append("")
    lines.append(f"- URL: {sec['url']}")
    lines.append("")
    lines.append("## 문제 설명")
    lines.append("")
    lines.append(sec["description"] or "(내용 없음)")
    if sec["input"]:
        lines.append("\n## 입력\n")
        lines.append(sec["input"])
    if sec["output"]:
        lines.append("\n## 출력\n")
        lines.append(sec["output"])
    if sec["samples_in"] or sec["samples_out"]:
        lines.append("\n## 예제")
        nmax = max(len(sec["samples_in"]), len(sec["samples_out"]))
        for i in range(nmax):
            sin = sec["samples_in"][i] if i < len(sec["samples_in"]) else ""
            sout= sec["samples_out"][i] if i < len(sec["samples_out"]) else ""
            n = i + 1
            if sin:
                lines.append(f"\n### 예제 입력 {n}\n")
                lines.append("```\n" + sin.strip() + "\n```")
            if sout:
                lines.append(f"\n### 예제 출력 {n}\n")
                lines.append("```\n" + sout.strip() + "\n```")
    path = os.path.join(problem_dir, "PROBLEM.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

# ------------------------------------------------------------
# 5) 문제 폴더 준비(boj add + 보강)
# ------------------------------------------------------------
def ensure_boj_add(problem_id: int,
                   lang_flag: str = None,
                   title: str = "",
                   save_pdf: bool = False):
    def _run_local(cmd, cwd=None):
        return subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=cwd)

    problem_dir = resolve_problem_dir(problem_id)
    os.makedirs(problem_dir, exist_ok=True)

    # boj add 시도
    add_cmd = BOJ_CMD + ["add", str(problem_id)]
    if lang_flag:
        add_cmd = BOJ_CMD + ["add", "--type", lang_flag, str(problem_id)]
    res = _run_local(add_cmd)
    if res.returncode != 0:
        # --type 없이 재시도
        res2 = _run_local(BOJ_CMD + ["add", str(problem_id)])
        if res2.returncode != 0:
            print(f"[warn] boj add 실패. 직접 폴더/파일 생성으로 진행합니다.\n{(res2.stderr or res.stderr).strip()}")
            # 최소 파일 보장
            lang_map = {"py": "main.py", "cpp": "main.cc", "java": "Main.java"}
            filename = lang_map.get(lang_flag or "py", "main.py")
            main_path = os.path.join(problem_dir, filename)
            if not os.path.exists(main_path):
                open(main_path, "w", encoding="utf-8").close()
            os.makedirs(os.path.join(problem_dir, "testcases"), exist_ok=True)
        # ongoing_dir 반영
        problem_dir = resolve_problem_dir(problem_id)

    # 언어별 main 파일 보호 생성
    lang_map = {"py": "main.py", "cpp": "main.cc", "java": "Main.java"}
    if (lang_flag in lang_map) and not os.path.exists(os.path.join(problem_dir, lang_map[lang_flag])):
        open(os.path.join(problem_dir, lang_map[lang_flag]), "w", encoding="utf-8").close()

    # PROBLEM.md 작성
    write_problem_md(problem_dir, problem_id, title or "")

    # 샘플 케이스(가능 시)
    tc_dir = os.path.join(problem_dir, "testcases")
    if not os.path.isdir(tc_dir) or not os.listdir(tc_dir):
        res3 = _run_local(BOJ_CMD + ["case"], cwd=problem_dir)
        if res3.returncode != 0:
            os.makedirs(tc_dir, exist_ok=True)

    # (옵션) PDF 저장
    if save_pdf and shutil.which("wkhtmltopdf"):
        try:
            subprocess.run(["wkhtmltopdf",
                            f"https://www.acmicpc.net/problem/{problem_id}",
                            os.path.join(problem_dir, "statement.pdf")],
                           check=True)
        except Exception as e:
            print(f"[warn] PDF 생성 실패: {e}")

# ------------------------------------------------------------
# 6) 시험 공지 마크다운
# ------------------------------------------------------------
def md_announce(picked: List[Dict], duration: int, buckets_info: List[Tuple[str,str,int]]) -> str:
    lines = []
    lines.append("# 모의 코딩테스트")
    lines.append("")
    lines.append(f"- **제한시간**: {duration}분")
    lines.append(f"- **문항수**: {len(picked)}")
    lines.append("")
    lines.append("## 버킷 구성")
    for name, rng, cnt in buckets_info:
        lines.append(f"- {name}: {rng} x {cnt}")
    lines.append("")
    lines.append("## 규칙")
    lines.append("- 각 문제 폴더로 이동해서 main 수정하기")
    lines.append("- 문서 위치에서 `boj run`으로 샘플 테스트")
    lines.append("- 풀이 완료 후 `boj submit`으로 제출")
    lines.append("- 인터넷 검색은 표준 라이브러리 문서 정도로 제한")
    lines.append("")
    lines.append("## 문제")
    for i, p in enumerate(picked, 1):
        pid = p["problemId"]; title = p.get("titleKo") or p.get("title") or ""
        level = p.get("level") or 0
        lines.append(f"**Q{i}. [{pid}] {title}** ({tier_name(level)})  \nhttps://www.acmicpc.net/problem/{pid}")
    return "\n".join(lines)

# ------------------------------------------------------------
# 7) 선택/결정론
# ------------------------------------------------------------
def deterministic_pick(pool: List[Dict], exam_code: str, salt: str, count: int) -> List[Dict]:
    picked = []
    if not pool or count <= 0: return picked
    h = hashlib.blake2b(digest_size=16)
    h.update((exam_code + "|" + salt).encode("utf-8"))
    seed = int.from_bytes(h.digest(), "big")
    rng = random.Random(seed)
    idxs = list(range(len(pool)))
    rng.shuffle(idxs)
    for i in idxs[:min(count, len(pool))]:
        picked.append(pool[i])
    return picked

def resolve_buckets_from_preset(preset: str) -> List[Tuple[str,str,int]]:
    preset = preset.lower()
    names = {"easy":["veasy","easy","mid"],
             "mid":["easy","mid","hard"],
             "hard":["mid","hard","insane"]}[preset]
    return [(nm, DEFAULT_BUCKETS[nm][0], DEFAULT_BUCKETS[nm][1]) for nm in names]

# ------------------------------------------------------------
# 8) 메인
# ------------------------------------------------------------
def main():
    print("시험 코드(exam-code)를 입력하세요 : ", end="")
    exam_code = (input() or "").strip()
    while not exam_code:
        print("시험 코드(exam-code)를 입력하세요 : ", end="")
        exam_code = (input() or "").strip()

    print("난이도 프리셋을 선택하세요 (easy/mid/hard) : ", end="")
    diff = (input() or "").strip().lower() or "mid"
    if diff not in ("easy", "mid", "hard"):
        diff = "mid"

    print("언어를 선택하세요 (py/cpp/java/) : ", end="")
    lang = (input() or "").strip().lower()
    if lang not in ("py","cpp","java"):
        lang = None  # boj-cli 기본값 사용

    # 1) 로그인 보장
    ensure_boj_login()

    # 2) pool 준비(없으면 즉석 생성)
    pool_dir = "./pool"
    os.makedirs(pool_dir, exist_ok=True)

    def pool_path(name: str) -> str:
        return os.path.join(pool_dir, f"pool_{name}.json")

    buckets = resolve_buckets_from_preset(diff)
    tags: List[str] = []

    pools = []
    for name, rng, cnt in buckets:
        pj = load_json(pool_path(name), None)
        if not pj:
            # 즉석 생성
            q = build_query(rng, tags)
            cands = fetch_candidates(q, max_pages=3, size=100)
            pj = {"bucket": {"name": name, "range": rng, "count": cnt},
                  "tags": tags, "updated_at": datetime.now().isoformat(), "items": cands}
            save_json(pool_path(name), pj)
            print(f"[ok] '{name}' 버킷을 새로 수집했습니다. ({len(cands)}개 후보)")
        items = pj.get("items", [])
        pools.append((name, rng, cnt, items))

    # 3) 문제 결정
    picked_all: List[Dict] = []
    for name, rng, cnt, items in pools:
        chosen = deterministic_pick(items, exam_code, name, cnt)
        if len(chosen) < cnt:
            print(f"[warn] '{name}' 버킷 후보 부족({len(items)}개) → 가능한 만큼만 선택")
        picked_all.extend(chosen)

    # 4) 공지 작성
    dt = datetime.now().strftime("%Y%m%d_%H%M")
    md_name = f"시험 유의 사항.md"
    with open(md_name, "w", encoding="utf-8") as f:
        f.write(md_announce(picked_all, duration=120, buckets_info=[(n,r,c) for (n,r,c,_) in pools]))
    print(f"[ok] 공지 생성: {md_name}")

    # 5) BOJ 설정 및 문제 폴더 생성
    switch_boj_default_filetype(lang)  # 'py'/'cpp'/'java' or None
    for p in picked_all:
        ensure_boj_add(
            p["problemId"],
            lang_flag=lang,
            title=p.get("titleKo") or p.get("title") or "",
            save_pdf=False
        )

    # 6) 안내
    print("\n=== 준비 완료! ===")
    print("- 아래 폴더로 이동해서 `boj run` 실행 → 샘플 테스트 확인")
    print("- 풀이가 끝났다면 `boj submit`으로 바로 제출 가능 (이미 로그인됨)\n")
    base_dir = get_ongoing_dir()
    for p in picked_all:
        print(os.path.join(base_dir, str(p["problemId"])))
    print("\n행운을 빕니다! 🚀")

if __name__ == "__main__":
    main()

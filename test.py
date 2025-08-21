"""
1. python test.py 실행
  - 백준 로그인
  - 문제 분류 json 폴더 생성(주최자 한정)

2. 모의 코딩 테스트 디렉토리를 참가자에게 공유한다.
   - 사용자 역시 백준 로그인 필요

3. 난이도 별 티어 분포
  - veasy:B5~B3
  - easy:B2~S4
  - mid:S3~G5
  - hard:G4~P5
  - insane:P4~D5

4. 시험 난이도 별 문제 구성
  - 문제는 기본 3문제 구성
  - easy : veasy + easy + mid
  - mid : easy + mid + hard
  - hard : mid + hard + insane

5. 시험 응시 주의 사항
  - 시험 코드는 정해진 규칙이 없습니다. (추천 예시 : SSAFY_python_20250821)
  - 난이도별 
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock CT Bundle (N-buckets) w/ Exam Code & Snapshot Pools for BOJ (solved.ac)

- 5단계 고정 버킷(veasy/easy/mid/hard/insane)을 공통으로 사용
- 실행 시 인자 없으면 exam-code / language / difficulty를 대화형으로 입력받아 진행
- 프리셋:
  * easy  -> veasy, easy, mid
  * mid   -> easy,  mid,  hard
  * hard  -> mid,   hard, insane
- '풀 스냅샷'(JSON)에서 exam-code로 결정론적 선택 → 전원이 동일 결과
- 고급: --bucket "name:TIER_RANGE:COUNT" 사용 가능

주의: 언어를 지정해 사용할 때는 ./.boj/config.yaml 또는 ~/.boj/config.yaml 에 해당 filetype이 정의돼 있어야 합니다.
(없어도 본 스크립트가 1회 우회 재시도 및 폴더 강제 생성까지 시도합니다.)
"""

# ---- Self bootstrap: auto-install deps if missing (run before third-party imports) ----
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

# 1) Python 패키지 확인/설치
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

# 2) boj-cli 존재 확인/설치 (CLI)
if shutil.which("boj") is None:
    _pip_install("boj-cli>=1.2")

# boj 실행 커맨드 결정: PATH에 boj가 없으면 python -m boj 로 실행
BOJ_CMD = ["boj"] if shutil.which("boj") else [sys.executable, "-m", "boj"]

import argparse  # noqa

# ------------------------------ solved.ac ------------------------------

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
    "veasy":  ("B5~B3", 1),
    "easy":   ("B2~S4", 1),
    "mid":    ("S3~G5", 1),
    "hard":   ("G4~P5", 1),
    "insane": ("P4~D5", 1),
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
        if lo > hi:
            lo, hi = hi, lo
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
        if t:
            q.append(f"tag:{t}")
    return " ".join(q)

def fetch_candidates(query: str, max_pages: int = 3, size: int = 100) -> List[Dict]:
    items_all: List[Dict] = []
    for page in range(1, max_pages + 1):
        r = requests.get(SOLVED_AC_SEARCH, params={"query": query, "page": page, "size": size}, timeout=12)
        if r.status_code != 200:
            print(f"[warn] solved.ac 응답 {r.status_code}: {r.text[:200]}", file=sys.stderr)
            break
        data = r.json()
        items = data.get("items", [])
        items_all.extend(items)
        if len(items) < size:
            break
    # problemId 정렬 + 중복 제거 (결정론)
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

# ------------------------------ BOJ config helpers ------------------------------

def find_boj_config_path() -> str:
    """로컬 ./.boj/config.yaml → 홈 ~/.boj/config.yaml 순으로 탐색."""
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
    """로컬/홈 설정을 보강하고 기본 filetype을 lang_key로 설정."""
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

    ft = conf["filetype"]

    # OS별 python 실행 커맨드 자동 설정
    is_windows = platform.system().lower().startswith("win")
    py_run = "python main.py" if is_windows else "python3 main.py"
    cpp_run = "main.exe" if is_windows else "./main"

    ft.setdefault("py", {
        "language": "python3",     # BOJ 제출 언어명(소문자)
        "main": "main.py",
        "compile": "",
        "run": py_run,             # $file 사용하지 않음
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

    if lang_key in ("py", "cpp", "java"):
        conf["general"]["default_filetype"] = lang_key

    with open(conf_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(conf, f, allow_unicode=True, sort_keys=False)

    print(f"[ok] {conf_path} 기본 언어를 '{lang_key}'로 설정했습니다.")

# ------------------------------ BOJ problem page → Markdown ------------------------------

def _http_get_with_headers(url: str, tries: int = 3, timeout: int = 12) -> str:
    """브라우저 헤더로 요청하여 403 회피 + 재시도."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
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
    """<div id="...">...</div> 블록 추출 (BOJ 구조 기준)."""
    pattern = rf'<div id="{re.escape(div_id)}"[^>]*>(.*?)</div>'
    m = re.search(pattern, html, re.S | re.I)
    return m.group(1).strip() if m else ""

def fetch_problem_sections(problem_id: int) -> Dict[str, str]:
    """
    BOJ 문제 페이지를 가져와 Markdown으로 변환:
    - 설명(problem_description), 입력(problem_input), 출력(problem_output)
    - 예제 입력/출력 (sample-input-N / sample-output-N)
    """
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
            if not h:
                return ""
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
    """PROBLEM.md를 설명/입력/출력/예제까지 작성."""
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
            sout = sec["samples_out"][i] if i < len(sec["samples_out"]) else ""
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

# ------------------------------ BOJ workspace prep ------------------------------

def ensure_boj_add(problem_id: int,
                   lang_flag: str = None,
                   title: str = "",
                   make_aliases: bool = False,
                   alias_name: str = None,
                   save_pdf: bool = False):
    """
    - 1차: boj add 시도 (성공 시 그 경로 사용)
    - 실패해도: ongoing_dir 아래에 문제 폴더 강제 생성 + main/PROBLEM.md/testcases 보장
    """
    def _run(cmd, cwd=None):
        return subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=cwd)

    problem_dir = resolve_problem_dir(problem_id)
    os.makedirs(problem_dir, exist_ok=True)

    # 1) boj add 시도
    add_cmd = BOJ_CMD + ["add", str(problem_id)]
    if lang_flag:
        add_cmd = BOJ_CMD + ["add", "--type", lang_flag, str(problem_id)]
    res = _run(add_cmd)

    if res.returncode != 0:
        # --type 없이 재시도
        res2 = _run(BOJ_CMD + ["add", str(problem_id)])
        if res2.returncode != 0:
            print(f"[warn] boj add 실패. 직접 폴더/파일 생성으로 진행합니다.\n{(res2.stderr or res.stderr).strip()}")
            # === Fallback: 최소 파일 보장 ===
            lang_map = {"py": "main.py", "cpp": "main.cc", "java": "Main.java"}
            filename = lang_map.get(lang_flag or "py", "main.py")
            main_path = os.path.join(problem_dir, filename)
            if not os.path.exists(main_path):
                open(main_path, "w", encoding="utf-8").close()
            tc_dir = os.path.join(problem_dir, "testcases")
            os.makedirs(tc_dir, exist_ok=True)
        # 성공했을 수 있으니 문제 디렉토리 재계산(ongoing_dir 반영)
        problem_dir = resolve_problem_dir(problem_id)

    # 2) 보호적 생성
    if not os.path.isdir(problem_dir):
        os.makedirs(problem_dir, exist_ok=True)
    lang_map = {"py": "main.py", "cpp": "main.cc", "java": "Main.java"}
    if (lang_flag in lang_map) and not os.path.exists(os.path.join(problem_dir, lang_map[lang_flag])):
        open(os.path.join(problem_dir, lang_map[lang_flag]), "w", encoding="utf-8").close()

    # 3) PROBLEM.md 작성 (본문+입출력+예제까지)
    write_problem_md(problem_dir, problem_id, title or "")

    # 4) 샘플 케이스 시도 (실패해도 통과)
    tc_dir = os.path.join(problem_dir, "testcases")
    if not os.path.isdir(tc_dir) or not os.listdir(tc_dir):
        res3 = _run(BOJ_CMD + ["case"], cwd=problem_dir)
        if res3.returncode != 0:
            os.makedirs(tc_dir, exist_ok=True)

    # 5) (옵션) PDF 저장
    url = f"https://www.acmicpc.net/problem/{problem_id}"
    if save_pdf and shutil.which("wkhtmltopdf"):
        try:
            subprocess.run(["wkhtmltopdf", url, os.path.join(problem_dir, "statement.pdf")], check=True)
        except Exception as e:
            print(f"[warn] PDF 생성 실패: {e}")

    # 6) (옵션) 별칭 폴더
    if make_aliases and alias_name:
        alias_path = os.path.join(os.getcwd(), alias_name)
        if not os.path.exists(alias_path):
            try:
                if platform.system().lower().startswith("win"):
                    subprocess.run(["cmd", "/c", "mklink", "/J", alias_path, problem_dir], check=True)
                else:
                    os.symlink(problem_dir, alias_path)
            except Exception as e:
                print(f"[warn] alias 생성 실패: {e}")

# ------------------------------ announce ------------------------------

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
    lines.append("- VSCode: 해당 문제 디렉토리로 이동하기")
    lines.append("- VSCode: 이동 후 main 파일을 수정하기")
    lines.append("- VSCode: `boj run`으로 샘플 테스트하기")
    lines.append("- VSCode: 'boj submit`으로 제출")
    lines.append("- 인터넷 검색은 표준 라이브러리 문서 정도로 제한")
    lines.append("- 종료 후 5분 내 풀이 요약 및 토론")
    lines.append("")
    lines.append("## 문제")
    for i, p in enumerate(picked, 1):
        pid = p["problemId"]
        title = p.get("titleKo") or p.get("title") or ""
        level = p.get("level") or 0
        lines.append(f"**Q{i}. [{pid}] {title}** ({tier_name(level)})  \nhttps://www.acmicpc.net/problem/{pid}")
    return "\n".join(lines)

# ------------------------------ selection core ------------------------------

def deterministic_pick(pool: List[Dict], exam_code: str, salt: str, count: int) -> List[Dict]:
    picked = []
    if not pool or count <= 0:
        return picked
    h = hashlib.blake2b(digest_size=16)
    h.update((exam_code + "|" + salt).encode("utf-8"))
    seed = int.from_bytes(h.digest(), "big")
    rng = random.Random(seed)
    idxs = list(range(len(pool)))
    rng.shuffle(idxs)
    for i in idxs[:min(count, len(pool))]:
        picked.append(pool[i])
    return picked

def parse_bucket_arg(s: str) -> Tuple[str, str, int]:
    raw = s.strip()
    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError(f"--bucket 형식 오류: {s} (예: name:B4~S3:1)")
    name, rng, cnt = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if not name:
        raise ValueError(f"--bucket 이름이 비었습니다: {s}")
    try:
        cnt = int(cnt)
    except:
        raise ValueError(f"--bucket COUNT 정수 필요: {s}")
    if cnt <= 0:
        raise ValueError(f"--bucket COUNT는 1 이상이어야 함: {s}")
    parse_tier_range(rng)
    return name, rng, cnt

def resolve_buckets_from_preset(preset: str) -> List[Tuple[str,str,int]]:
    preset = preset.lower()
    names = {"easy":["veasy","easy","mid"],
             "mid":["easy","mid","hard"],
             "hard":["mid","hard","insane"]}[preset]
    return [(nm, DEFAULT_BUCKETS[nm][0], DEFAULT_BUCKETS[nm][1]) for nm in names]

def prompt_choice(prompt: str, choices: List[str], default: str = None) -> str:
    chs = "/".join(choices)
    while True:
        s = input(f"{prompt} ({chs})" + (f" [{default}] " if default else " ") ).strip().lower()
        if not s and default is not None:
            return default
        if s in choices:
            return s
        print(f"입력이 올바르지 않습니다. 가능한 값: {chs}")

# ------------------------------ main ------------------------------

def main():
    ap = argparse.ArgumentParser(description="Mock CT Bundle (N-buckets, exam-code + snapshot pools)")
    ap.add_argument("--refresh-pool", action="store_true", help="기본 5버킷(veasy~insane) 풀 스냅샷 생성/갱신")
    ap.add_argument("--exam-code", type=str, help="시험 코드(전원 동일 입력)")
    ap.add_argument("--difficulty", type=str, choices=["easy","mid","hard"], help="난이도 프리셋 선택")
    ap.add_argument("--pool-dir", type=str, default="./pool", help="풀 스냅샷 저장/읽기 디렉터리")
    prep = ap.add_mutually_exclusive_group()
    prep.add_argument("--prepare", dest="prepare", action="store_true", help="문제 폴더/샘플 생성 (기본값)")
    prep.add_argument("--no-prepare", dest="prepare", action="store_false", help="문제 폴더/샘플 생성하지 않음")
    ap.set_defaults(prepare=True)
    ap.add_argument("--lang", type=str, choices=["py","cpp","java"], help="boj add --type <py|cpp|java>")
    ap.add_argument("--aliases", action="store_true", help="problem1/2/3 별칭 폴더(링크) 생성")
    ap.add_argument("--save-pdf", action="store_true", help="문제 페이지를 statement.pdf로 저장(wkhtmltopdf 필요)")
    ap.add_argument("--tags", type=str, default="", help="공통 태그(쉼표) 예: 'graph,dp'")
    ap.add_argument("--max-pages", type=int, default=3, help="solved.ac 검색 페이지(100/페이지)")
    ap.add_argument("--duration", type=int, default=120, help="시험 시간(분)")
    ap.add_argument("--bucket", action="append",
                    help='커스텀 버킷 "name:TIER_RANGE:COUNT" (여러 번 지정). 예: --bucket "easy:B4~S3:1"')

    args = ap.parse_args()

    # 0) 풀 스냅샷 모드
    if args.refresh_pool:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        def pool_path(name: str) -> str:
            return os.path.join(args.pool_dir, f"pool_{name}.json")
        for name in ["veasy","easy","mid","hard","insane"]:
            rng, cnt = DEFAULT_BUCKETS[name]
            q = build_query(rng, tags)
            cands = fetch_candidates(q, max_pages=args.max_pages, size=100)
            save_json(pool_path(name), {
                "bucket": {"name": name, "range": rng, "count": cnt},
                "tags": tags,
                "updated_at": datetime.now().isoformat(),
                "items": cands
            })
            print(f"[ok] '{name}' 풀 스냅샷 저장: {pool_path(name)}")
        print("[i] pool/ 폴더를 팀원과 공유하세요.")
        return

    # 1) 대화형 입력 (요청하신 프롬프트 문구로 변경)
    exam_code = (args.exam_code or "").strip()
    while not exam_code:
        exam_code = input("시험 코드(exam-code)를 입력하세요 : ").strip()

    buckets: List[Tuple[str,str,int]] = []
    if args.bucket:
        for b in args.bucket:
            name, rng, cnt = parse_bucket_arg(b)
            buckets.append((name, rng, cnt))
    else:
        diff = args.difficulty or input("난이도 프리셋을 선택하세요 (easy/mid/hard) : ").strip().lower() or "mid"
        if diff not in ("easy","mid","hard"):
            diff = "mid"
        buckets = resolve_buckets_from_preset(diff)

    lang = args.lang
    if lang is None:
        c = input("언어를 선택하세요 (py/cpp/java/) : ").strip().lower()
        lang = c if c in ("py","cpp","java") else None

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    def pool_path(name: str) -> str:
        return os.path.join(args.pool_dir, f"pool_{name}.json")

    # 2) 스냅샷 로드
    pools = []
    for name, rng, cnt in buckets:
        pj = load_json(pool_path(name), None)
        if not pj:
            print(f"[error] 풀 스냅샷 없음: {pool_path(name)}  (주최자가 먼저 --refresh-pool 실행해 공유해야 합니다)")
            sys.exit(1)
        items = pj.get("items", [])
        pools.append((name, rng, cnt, items))

    # 3) 결정론 추출
    picked_all: List[Dict] = []
    for name, rng, cnt, items in pools:
        chosen = deterministic_pick(items, exam_code, name, cnt)
        if len(chosen) < cnt:
            print(f"[warn] '{name}' 버킷에서 {cnt}개 요구했지만 후보가 부족({len(items)}개). 가능한 만큼만 선택.")
        picked_all.extend(chosen)

    # 4) 출력/공지
    print(f"\n=== 이번 모의시험 (exam-code: {exam_code}) ===")
    for i, p in enumerate(picked_all, 1):
        pid = p["problemId"]
        title = p.get("titleKo") or p.get("title") or ""
        lvl = p.get("level") or 0
        print(f"Q{i}. [{pid}] {title} ({tier_name(lvl)}) -> https://www.acmicpc.net/problem/{pid}")

    dt = datetime.now().strftime("%Y%m%d_%H%M")
    md_name = f"시험 응시자 설명서.md"
    with open(md_name, "w", encoding="utf-8") as f:
        f.write(md_announce(picked_all, args.duration, [(n, r, c) for (n, r, c, _) in pools]))
    print(f"[ok] 공지 생성: {md_name}")

    # 5) 문제 폴더/샘플 준비
    if args.prepare:
        switch_boj_default_filetype(lang)  # 'py'/'cpp'/'java' 또는 None
        for i, p in enumerate(picked_all, 1):
            ensure_boj_add(
                p["problemId"],
                lang_flag=lang,
                title=p.get("titleKo", ""),
                make_aliases=args.aliases,
                alias_name=f"problem{i}" if args.aliases else None,
                save_pdf=args.save_pdf
            )
        print("[ok] 준비 완료. 각 폴더(예: problem1/ 또는 문제번호 폴더)에서 `boj run` → `boj submit` 실행하세요.")

if __name__ == "__main__":
    main()

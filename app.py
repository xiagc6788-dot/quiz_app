import time
import random
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

# ========= 基本配置 =========
DB_PATH = Path("quiz.db")
CSV_PATH = Path("questions.csv")

EXAM_CONFIG = {
    "单选题": {"count": 30, "score": 1},
    "多选题": {"count": 20, "score": 2},
    "判断题": {"count": 20, "score": 1},
    "填空题": {"count": 10, "score": 2},
}

QTYPE_ORDER = ["单选题", "多选题", "判断题", "填空题"]


# ========= 数据库 =========
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter TEXT NOT NULL,
            q_type TEXT NOT NULL,
            text TEXT NOT NULL,
            options TEXT,
            answer TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wrong_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            wrong_count INTEGER NOT NULL DEFAULT 0,
            last_wrong_ts REAL NOT NULL,
            UNIQUE(user_id, question_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS answer_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            is_correct INTEGER NOT NULL,
            answer_text TEXT NOT NULL,
            ts REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def import_csv_if_empty():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) FROM questions")
    count = cur.fetchone()[0]
    if count > 0:
        conn.close()
        return

    if not CSV_PATH.exists():
        conn.close()
        st.error("题库文件 questions.csv 不存在，请先上传。")
        return

    df = pd.read_csv(CSV_PATH).fillna("")
    for _, row in df.iterrows():
        cur.execute("""
            INSERT INTO questions (chapter, q_type, text, options, answer)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(row["chapter"]).strip(),
            str(row["q_type"]).strip(),
            str(row["text"]).strip(),
            str(row["options"]).strip(),
            str(row["answer"]).strip(),
        ))
    conn.commit()
    conn.close()


# ========= 工具函数 =========
def normalize_tf(x: str) -> str:
    x = str(x).strip()
    if x in ["对", "√", "是", "正确", "T", "True", "true"]:
        return "对"
    if x in ["错", "×", "否", "错误", "F", "False", "false"]:
        return "错"
    return x


def escape_html(s: str) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def check_answer(q_type: str, user_answer, std_answer: str) -> bool:
    std_answer = str(std_answer).strip()
    if q_type == "判断题":
        return normalize_tf(user_answer) == normalize_tf(std_answer)

    if q_type == "多选题":
        if not user_answer:
            return False
        ua = "".join(sorted([str(x).strip().upper() for x in user_answer]))
        sa = "".join(sorted(list(std_answer.strip().upper())))
        return ua == sa

    if q_type == "单选题":
        if user_answer is None:
            return False
        return str(user_answer).strip().upper() == std_answer.strip().upper()

    return str(user_answer).strip() == std_answer.strip()


def format_hms(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def get_all_chapters() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT chapter FROM questions ORDER BY chapter")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows


# ========= 题目获取&统计 =========
def fetch_questions_for_mode(user_id: str, mode: str, chapter: str = "全部", q_type_filter: str = "全部"):
    """获取符合条件的所有题目列表（按题型排序）"""
    conn = get_conn()
    cur = conn.cursor()

    if mode == "章节刷题":
        sql = "SELECT * FROM questions WHERE 1=1"
        params = []
        if chapter != "全部":
            sql += " AND chapter = ?"
            params.append(chapter)
        if q_type_filter != "全部":
            sql += " AND q_type = ?"
            params.append(q_type_filter)
        cur.execute(sql, params)
        rows = cur.fetchall()

    elif mode == "错题重刷":
        sql = """
        SELECT q.* FROM questions q
        JOIN wrong_log w ON q.id = w.question_id
        WHERE w.user_id = ?
        """
        params = [user_id]
        if chapter != "全部":
            sql += " AND q.chapter = ?"
            params.append(chapter)
        if q_type_filter != "全部":
            sql += " AND q.q_type = ?"
            params.append(q_type_filter)
        cur.execute(sql, params)
        rows = cur.fetchall()

    elif mode == "随机刷题":
        sql = "SELECT * FROM questions WHERE 1=1"
        params = []
        if q_type_filter != "全部":
            sql += " AND q_type = ?"
            params.append(q_type_filter)
        cur.execute(sql, params)
        rows = cur.fetchall()

    else:
        rows = []

    conn.close()

    # 转为字典列表并按题型排序
    result = [dict(r) for r in rows]
    result.sort(key=lambda x: QTYPE_ORDER.index(x["q_type"]) if x["q_type"] in QTYPE_ORDER else 99)
    random.shuffle(result)  # 先打乱
    result.sort(key=lambda x: QTYPE_ORDER.index(x["q_type"]) if x["q_type"] in QTYPE_ORDER else 99)  # 再按题型排序
    return result


def record_wrong(user_id: str, question_id: int):
    ts = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wrong_log (user_id, question_id, wrong_count, last_wrong_ts)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, question_id) DO UPDATE SET
            wrong_count = wrong_count + 1,
            last_wrong_ts = excluded.last_wrong_ts
    """, (user_id, question_id, ts))
    conn.commit()
    conn.close()


def remove_from_wrong(user_id: str, question_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM wrong_log WHERE user_id = ? AND question_id = ?", (user_id, question_id))
    conn.commit()
    conn.close()


def log_answer(user_id: str, question_id: int, is_correct: bool, answer_text: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO answer_log (user_id, question_id, is_correct, answer_text, ts)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, question_id, int(is_correct), str(answer_text), time.time()))
    conn.commit()
    conn.close()


def get_question_stats(user_id: str, question_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct_cnt,
            SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS wrong_cnt
        FROM answer_log
        WHERE user_id = ? AND question_id = ?
    """, (user_id, question_id))
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0, 0
    return row[0] or 0, row[1] or 0


def get_chapter_summary(user_id: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT chapter, COUNT(*) AS total FROM questions GROUP BY chapter ORDER BY chapter")
    q_total = {r["chapter"]: r["total"] for r in cur.fetchall()}

    cur.execute("""
        SELECT q.chapter, COUNT(DISTINCT a.question_id) AS done_cnt
        FROM answer_log a JOIN questions q ON a.question_id = q.id
        WHERE a.user_id = ? GROUP BY q.chapter
    """, (user_id,))
    q_done = {r["chapter"]: r["done_cnt"] for r in cur.fetchall()}

    cur.execute("""
        SELECT q.chapter, COUNT(*) AS wrong_cnt
        FROM wrong_log w JOIN questions q ON w.question_id = q.id
        WHERE w.user_id = ? GROUP BY q.chapter
    """, (user_id,))
    q_wrong = {r["chapter"]: r["wrong_cnt"] for r in cur.fetchall()}

    conn.close()

    data = []
    for chap, total in q_total.items():
        done = q_done.get(chap, 0)
        wrong = q_wrong.get(chap, 0)
        data.append({
            "章节": chap,
            "总题数": total,
            "已刷题数": done,
            "错题数": wrong,
            "待刷题数": max(total - done, 0),
        })
    return pd.DataFrame(data)


def get_wrong_count(user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM wrong_log WHERE user_id = ?", (user_id,))
    cnt = cur.fetchone()[0]
    conn.close()
    return cnt


def get_available_count(user_id: str, mode: str, chapter: str, q_type_filter: str):
    conn = get_conn()
    cur = conn.cursor()

    if mode == "章节刷题":
        sql = "SELECT COUNT(*) FROM questions WHERE 1=1"
        params = []
        if chapter != "全部":
            sql += " AND chapter = ?"
            params.append(chapter)
        if q_type_filter != "全部":
            sql += " AND q_type = ?"
            params.append(q_type_filter)
        cur.execute(sql, params)

    elif mode == "错题重刷":
        sql = "SELECT COUNT(*) FROM questions q JOIN wrong_log w ON q.id = w.question_id WHERE w.user_id = ?"
        params = [user_id]
        if chapter != "全部":
            sql += " AND q.chapter = ?"
            params.append(chapter)
        if q_type_filter != "全部":
            sql += " AND q.q_type = ?"
            params.append(q_type_filter)
        cur.execute(sql, params)

    elif mode == "随机刷题":
        sql = "SELECT COUNT(*) FROM questions WHERE 1=1"
        params = []
        if q_type_filter != "全部":
            sql += " AND q_type = ?"
            params.append(q_type_filter)
        cur.execute(sql, params)

    else:
        conn.close()
        return 0

    cnt = cur.fetchone()[0]
    conn.close()
    return cnt


# ========= 模拟考核 =========
def build_exam_paper():
    """按 EXAM_CONFIG 组卷，严格按题型顺序排列"""
    conn = get_conn()
    cur = conn.cursor()
    exam_questions = []

    for qtype in QTYPE_ORDER:
        cfg = EXAM_CONFIG.get(qtype)
        if not cfg:
            continue
        cur.execute("SELECT id, chapter, q_type, text, options, answer FROM questions WHERE q_type = ?", (qtype,))
        rows = list(cur.fetchall())
        random.shuffle(rows)
        need = min(cfg["count"], len(rows))
        exam_questions.extend([dict(r) for r in rows[:need]])

    conn.close()
    return exam_questions  # 已经按题型顺序添加


def grade_exam(user_id: str, exam_questions, exam_answers):
    total_score = 0
    detail = []

    for idx, row in enumerate(exam_questions):
        qid = row["id"]
        qtype = row["q_type"]
        std = row["answer"]
        user_ans = exam_answers.get(idx)

        if qtype == "多选题":
            is_correct = check_answer(qtype, user_ans or [], std)
            ans_str = "".join(user_ans or [])
        else:
            is_correct = check_answer(qtype, user_ans, std)
            ans_str = str(user_ans or "")

        log_answer(user_id, qid, is_correct, ans_str)
        if not is_correct:
            record_wrong(user_id, qid)

        per_score = EXAM_CONFIG.get(qtype, {}).get("score", 0)
        gain = per_score if is_correct else 0
        total_score += gain

        detail.append({
            "题号": idx + 1,
            "题型": qtype,
            "得分": gain,
            "应得分": per_score,
            "是否正确": "√" if is_correct else "×",
        })

    return total_score, pd.DataFrame(detail)


# ========= SessionState =========
def init_session():
    ss = st.session_state
    defaults = {
        "mode": "章节刷题",
        "q_list": [],
        "q_index": 0,
        "show_answer": False,
        "judge_result": None,
        "practice_start_ts": None,
        "confirm_clear": False,
        "exam_questions": [],
        "exam_answers": {},
        "exam_index": 0,
        "exam_start_ts": None,
        "exam_finished": False,
        "exam_result": None,
        "exam_marked": set(),
    }
    for k, v in defaults.items():
        if k not in ss:
            ss[k] = v


# ========= 主界面 =========
def main():
    st.set_page_config(page_title="刷题小玩意儿-川", page_icon="🧠", layout="wide")
    init_session()
    init_db()
    import_csv_if_empty()
    ss = st.session_state

    # 全局样式
    st.markdown("""
        <style>
        .stApp {
            background: radial-gradient(circle at top left, #470000 0, #070707 40%, #000000 100%);
            color: #f5f5f5;
        }
        .main-title {
            text-align: center;
            font-size: 34px;
            font-weight: 800;
            letter-spacing: 0.12em;
            margin-bottom: 0.2rem;
            background: linear-gradient(90deg,#ff5252,#ffb74d);
            -webkit-background-clip: text;
            color: transparent;
        }
        .sub-title {
            text-align: center;
            color: #bbbbbb;
            margin-bottom: 1.6rem;
            font-size: 14px;
        }
        .question-card {
            padding: 1.4rem 1.6rem;
            border-radius: 10px;
            border: 1px solid #ff525233;
            background: linear-gradient(145deg,#121212,#050505);
            box-shadow: 0 8px 20px rgba(0,0,0,0.5);
            margin-bottom: 1rem;
        }
        .tag {
            display: inline-block;
            padding: 0.16rem 0.7rem;
            margin-right: 0.4rem;
            border-radius: 999px;
            font-size: 11px;
            background: #2b2b2b;
            color: #ffb74d;
            border: 1px solid #ff525233;
        }
        .stButton > button {
            border-radius: 999px;
            border: 0;
            background: linear-gradient(90deg,#ff5252,#ff7043);
            color: white;
            padding: 0.35rem 1.1rem;
            font-weight: 600;
        }
        .stButton > button:hover {
            background: linear-gradient(90deg,#ff7043,#ff5252);
        }
        section[data-testid="stSidebar"] h1, 
        section[data-testid="stSidebar"] h2, 
        section[data-testid="stSidebar"] h3 {
            color: #ff8a65;
        }
        .nav-btn {
            display: inline-block;
            width: 32px;
            height: 32px;
            line-height: 32px;
            text-align: center;
            margin: 2px;
            border-radius: 4px;
            background: #333;
            color: #fff;
            cursor: pointer;
            font-size: 12px;
        }
        .nav-btn.current { background: #ff5252; }
        .nav-btn.marked { border: 2px solid #ffb74d; }
        .nav-btn.answered { background: #2e7d32; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="main-title">刷题小玩意儿-川</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">章节刷题 · 错题重刷 · 随机刷题 · 模拟考核</div>', unsafe_allow_html=True)

    # 侧边栏
    with st.sidebar:
        st.header("基本设置")
        user_id = st.text_input("用户名", value="student01").strip() or "student01"

        mode = st.selectbox("刷题模式", ["章节刷题", "错题重刷", "随机刷题", "模拟考核"],
                           index=["章节刷题", "错题重刷", "随机刷题", "模拟考核"].index(ss.mode))
        if mode != ss.mode:
            ss.mode = mode
            ss.q_list = []
            ss.q_index = 0
            ss.show_answer = False
            ss.judge_result = None
            ss.practice_start_ts = None

        chapters = get_all_chapters()
        chapter = "全部"
        if mode in ["章节刷题", "错题重刷"]:
            chapter = st.selectbox("按章节", ["全部"] + chapters, index=0)

        q_type_filter = "全部"
        if mode in ["章节刷题", "错题重刷", "随机刷题"]:
            q_type_filter = st.selectbox("题型筛选", ["全部"] + QTYPE_ORDER, index=0)

        st.markdown("---")
        st.subheader("统计信息")
        total_cnt = get_available_count(user_id, mode, chapter, q_type_filter)
        wrong_cnt = get_wrong_count(user_id)
        st.write(f"当前模式可选题数：**{total_cnt}**")
        st.write(f"当前用户错题数：**{wrong_cnt}**")

        st.markdown("---")
        st.subheader("数据管理")
        if not ss.confirm_clear:
            if st.button("清空本用户错题本和答题记录"):
                ss.confirm_clear = True
                st.rerun()
        else:
            st.warning("确定要清空？此操作不可恢复。")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("确定清空"):
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM wrong_log WHERE user_id = ?", (user_id,))
                    cur.execute("DELETE FROM answer_log WHERE user_id = ?", (user_id,))
                    conn.commit()
                    conn.close()
                    ss.confirm_clear = False
                    st.success("已清空")
                    st.rerun()
            with col2:
                if st.button("取消"):
                    ss.confirm_clear = False
                    st.rerun()

    tab_quiz, tab_wrong, tab_sum = st.tabs(["刷题 / 考核", "错题汇总", "题目汇总"])

    with tab_quiz:
        if mode == "模拟考核":
            render_exam_tab(user_id)
        else:
            render_practice_tab(user_id, mode, chapter, q_type_filter)

    with tab_wrong:
        render_wrong_summary(user_id)

    with tab_sum:
        df = get_chapter_summary(user_id)
        st.dataframe(df, use_container_width=True)


# ========= 练习 =========
def render_practice_tab(user_id: str, mode: str, chapter: str, q_type_filter: str):
    ss = st.session_state

    # 初始化或刷新题目列表
    col_refresh, col_time = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 刷新题目列表"):
            ss.q_list = fetch_questions_for_mode(user_id, mode, chapter, q_type_filter)
            ss.q_index = 0
            ss.show_answer = False
            ss.judge_result = None
            ss.practice_start_ts = time.time()
            st.rerun()

    if not ss.q_list:
        ss.q_list = fetch_questions_for_mode(user_id, mode, chapter, q_type_filter)
        if ss.practice_start_ts is None:
            ss.practice_start_ts = time.time()

    if not ss.q_list:
        st.info("当前条件下没有可用题目，请调整筛选条件后点击刷新。")
        return

    with col_time:
        if ss.practice_start_ts:
            elapsed = int(time.time() - ss.practice_start_ts)
            st.markdown(f"**练习用时：{format_hms(elapsed)}**")

    # 当前题目
    if ss.q_index >= len(ss.q_list):
        ss.q_index = len(ss.q_list) - 1
    if ss.q_index < 0:
        ss.q_index = 0

    current = ss.q_list[ss.q_index]
    qid = current["id"]
    qtype = current["q_type"]
    options = (current["options"] or "").split("||") if current["options"] else []

    st.markdown("---")
    st.markdown(f'<div class="question-card">', unsafe_allow_html=True)
    st.markdown(f'<span class="tag">{escape_html(current["chapter"])}</span><span class="tag">{escape_html(qtype)}</span>', unsafe_allow_html=True)
    st.markdown(f"**第 {ss.q_index + 1} / {len(ss.q_list)} 题：** {escape_html(current['text'])}")

    # 根据题型渲染
    user_ans = None
    if qtype == "单选题":
        user_ans = st.radio("请选择一个答案：", options, index=None, key=f"prac_single_{qid}")
        if user_ans:
            user_ans = user_ans[0] if user_ans and user_ans[0].isalpha() else user_ans

    elif qtype == "多选题":
        st.write("请选择一个或多个答案：")
        selected = []
        for i, opt in enumerate(options):
            if st.checkbox(opt, key=f"prac_multi_{qid}_{i}"):
                letter = opt[0] if opt and opt[0].isalpha() else str(i)
                selected.append(letter)
        user_ans = selected

    elif qtype == "判断题":
        user_ans = st.radio("请选择：", ["对", "错"], index=None, key=f"prac_judge_{qid}")

    else:
        user_ans = st.text_area("请填写答案：", key=f"prac_blank_{qid}")

    # 按钮
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("提交 / 检查答案"):
            std = current["answer"]
            is_correct = check_answer(qtype, user_ans, std)
            ans_str = "".join(user_ans) if isinstance(user_ans, list) else str(user_ans or "")
            log_answer(user_id, qid, is_correct, ans_str)
            if is_correct:
                remove_from_wrong(user_id, qid)
            else:
                record_wrong(user_id, qid)
            ss.show_answer = True
            ss.judge_result = is_correct
            st.rerun()

    with col2:
        if st.button("上一题") and ss.q_index > 0:
            ss.q_index -= 1
            ss.show_answer = False
            ss.judge_result = None
            st.rerun()

    with col3:
        if st.button("下一题") and ss.q_index < len(ss.q_list) - 1:
            ss.q_index += 1
            ss.show_answer = False
            ss.judge_result = None
            st.rerun()

    # 判分结果
    if ss.show_answer and ss.judge_result is not None:
        std = current["answer"]
        if ss.judge_result:
            st.success(f"✅ 回答正确！标准答案：{std}")
        else:
            st.error(f"❌ 回答错误。标准答案：{std}")

    correct_cnt, wrong_cnt = get_question_stats(user_id, qid)
    st.info(f"本题统计：答对 {correct_cnt} 次，答错 {wrong_cnt} 次")
    st.markdown("</div>", unsafe_allow_html=True)


# ========= 模拟考核 =========
def render_exam_tab(user_id: str):
    ss = st.session_state

    # 未开始
    if not ss.exam_questions and not ss.exam_finished:
        st.subheader("模拟考核说明")
        for qt in QTYPE_ORDER:
            cfg = EXAM_CONFIG.get(qt)
            if cfg:
                st.markdown(f"- {qt}：{cfg['count']} 题，每题 {cfg['score']} 分")
        st.markdown("- 总时长：60 分钟，超时自动交卷")
        st.markdown("- 题目按 **单选→多选→判断→填空** 顺序排列")

        if st.button("开始模拟考核"):
            ss.exam_questions = build_exam_paper()
            ss.exam_answers = {}
            ss.exam_index = 0
            ss.exam_start_ts = time.time()
            ss.exam_finished = False
            ss.exam_result = None
            ss.exam_marked = set()
            st.rerun()
        return

    # 已交卷
    if ss.exam_finished and ss.exam_result is not None:
        total, df = ss.exam_result
        st.success(f"本次模拟考核总分：**{total} 分**")
        st.dataframe(df, use_container_width=True)
        if st.button("重新开始新的模拟考核"):
            ss.exam_questions = []
            ss.exam_answers = {}
            ss.exam_index = 0
            ss.exam_start_ts = None
            ss.exam_finished = False
            ss.exam_result = None
            ss.exam_marked = set()
            st.rerun()
        return

    questions = ss.exam_questions
    if not questions:
        st.info("暂无试卷")
        return

    # 计时
    elapsed = int(time.time() - (ss.exam_start_ts or time.time()))
    remain = 60 * 60 - elapsed
    if remain <= 0:
        total, df = grade_exam(user_id, questions, ss.exam_answers)
        ss.exam_finished = True
        ss.exam_result = (total, df)
        st.warning("时间到，已自动交卷")
        st.rerun()
        return

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown(f"**已用时间：{format_hms(elapsed)}**")
    with col_t2:
        st.markdown(f"**剩余时间：{format_hms(remain)}**")

    # 题号导航
    st.markdown("---")
    st.markdown("**题号导航（点击跳转，黄边=已标记，绿色=已作答）：**")

    nav_html = ""
    for i, q in enumerate(questions):
        cls = "nav-btn"
        if i == ss.exam_index:
            cls += " current"
        if i in ss.exam_marked:
            cls += " marked"
        if i in ss.exam_answers and ss.exam_answers[i]:
            cls += " answered"
        nav_html += f'<span class="{cls}">{i + 1}</span>'
    st.markdown(nav_html, unsafe_allow_html=True)

    # 跳转输入
    jump_col1, jump_col2 = st.columns([1, 4])
    with jump_col1:
        jump_to = st.number_input("跳转到第几题", min_value=1, max_value=len(questions), value=ss.exam_index + 1, step=1)
    with jump_col2:
        if st.button("跳转"):
            ss.exam_index = jump_to - 1
            st.rerun()

    st.markdown("---")

    # 当前题目
    idx = ss.exam_index
    row = questions[idx]
    qid = row["id"]
    qtype = row["q_type"]
    options = (row["options"] or "").split("||") if row["options"] else []

    st.markdown(f'<div class="question-card">', unsafe_allow_html=True)
    st.markdown(f'<span class="tag">{escape_html(qtype)}</span>', unsafe_allow_html=True)  # 只显示题型
    st.markdown(f"**第 {idx + 1} / {len(questions)} 题：** {escape_html(row['text'])}")

    current_ans = ss.exam_answers.get(idx)

    if qtype == "单选题":
        default_idx = None
        if isinstance(current_ans, str) and current_ans:
            for i, opt in enumerate(options):
                if opt.startswith(current_ans):
                    default_idx = i
                    break
        choice = st.radio("请选择：", options, index=default_idx, key=f"exam_single_{idx}")
        if choice:
            ss.exam_answers[idx] = choice[0] if choice and choice[0].isalpha() else choice

    elif qtype == "多选题":
        st.write("请选择一个或多个答案：")
        selected = current_ans if isinstance(current_ans, list) else []
        new_selected = []
        for i, opt in enumerate(options):
            letter = opt[0] if opt and opt[0].isalpha() else str(i)
            checked = letter in selected
            if st.checkbox(opt, value=checked, key=f"exam_multi_{idx}_{i}"):
                new_selected.append(letter)
        ss.exam_answers[idx] = new_selected

    elif qtype == "判断题":
        default_idx = None
        if current_ans == "对":
            default_idx = 0
        elif current_ans == "错":
            default_idx = 1
        choice = st.radio("请选择：", ["对", "错"], index=default_idx, key=f"exam_judge_{idx}")
        if choice:
            ss.exam_answers[idx] = choice

    else:
        text = st.text_area("请填写答案：", value=current_ans or "", key=f"exam_blank_{idx}")
        ss.exam_answers[idx] = text

    st.markdown("</div>", unsafe_allow_html=True)

    # 标记按钮
    col_mark, col_prev, col_next, col_submit = st.columns(4)
    with col_mark:
        if idx in ss.exam_marked:
            if st.button("取消标记"):
                ss.exam_marked.discard(idx)
                st.rerun()
        else:
            if st.button("🚩 标记此题"):
                ss.exam_marked.add(idx)
                st.rerun()

    with col_prev:
        if st.button("上一题") and idx > 0:
            ss.exam_index -= 1
            st.rerun()

    with col_next:
        if st.button("下一题") and idx < len(questions) - 1:
            ss.exam_index += 1
            st.rerun()

    with col_submit:
        if st.button("交卷"):
            total, df = grade_exam(user_id, questions, ss.exam_answers)
            ss.exam_finished = True
            ss.exam_result = (total, df)
            st.rerun()


# ========= 错题汇总 =========
def render_wrong_summary(user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT q.chapter, q.q_type, q.text, q.answer, w.wrong_count
        FROM wrong_log w
        JOIN questions q ON w.question_id = q.id
        WHERE w.user_id = ?
        ORDER BY q.q_type, q.chapter, w.last_wrong_ts DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        st.info("当前用户暂无错题记录。做错的题目会自动添加到这里。")
        return

    data = []
    for r in rows:
        data.append({
            "章节": r["chapter"],
            "题型": r["q_type"],
            "题干": r["text"][:50] + "..." if len(r["text"]) > 50 else r["text"],
            "标准答案": r["answer"],
            "错误次数": r["wrong_count"],
        })
    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True)


if __name__ == "__main__":
    main()
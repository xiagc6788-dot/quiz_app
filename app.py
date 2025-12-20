# ... existing code ...
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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter TEXT NOT NULL,
            q_type TEXT NOT NULL,
            text TEXT NOT NULL,
            options TEXT,
            answer TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS wrong_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            wrong_count INTEGER NOT NULL DEFAULT 0,
            last_wrong_ts REAL NOT NULL,
            UNIQUE(user_id, question_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS answer_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            is_correct INTEGER NOT NULL,
            answer_text TEXT NOT NULL,
            ts REAL NOT NULL
        )
        """
    )

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
        cur.execute(
            """
            INSERT INTO questions (chapter, q_type, text, options, answer)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(row["chapter"]).strip(),
                str(row["q_type"]).strip(),
                str(row["text"]).strip(),
                str(row["options"]).strip(),
                str(row["answer"]).strip(),
            ),
        )
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
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


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

    # 填空题：完全匹配
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
def fetch_question_for_mode(
    user_id: str,
    mode: str,
    chapter: str = "全部",
    q_type_filter: str = "全部",
    exclude_ids=None,
):
    if exclude_ids is None:
        exclude_ids = []

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
        if exclude_ids:
            sql += f" AND id NOT IN ({','.join(['?'] * len(exclude_ids))})"
            params.extend(exclude_ids)
        sql += " ORDER BY RANDOM() LIMIT 1"
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.close()
        return row

    if mode == "错题重刷":
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
        if exclude_ids:
            sql += f" AND q.id NOT IN ({','.join(['?'] * len(exclude_ids))})"
            params.extend(exclude_ids)
        sql += " ORDER BY RANDOM() LIMIT 1"
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.close()
        return row

    if mode == "随机刷题":
        sql = "SELECT * FROM questions WHERE 1=1"
        params = []
        if q_type_filter != "全部":
            sql += " AND q_type = ?"
            params.append(q_type_filter)
        if exclude_ids:
            sql += f" AND id NOT IN ({','.join(['?'] * len(exclude_ids))})"
            params.extend(exclude_ids)
        sql += " ORDER BY RANDOM() LIMIT 1"
        cur.execute(sql, params)
        row = cur.fetchone()
        conn.close()
        return row

    conn.close()
    return None


def record_wrong(user_id: str, question_id: int):
    ts = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO wrong_log (user_id, question_id, wrong_count, last_wrong_ts)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, question_id) DO UPDATE SET
            wrong_count = wrong_count + 1,
            last_wrong_ts = excluded.last_wrong_ts
        """,
        (user_id, question_id, ts),
    )
    conn.commit()
    conn.close()


def remove_from_wrong(user_id: str, question_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM wrong_log WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    )
    conn.commit()
    conn.close()


def log_answer(user_id: str, question_id: int, is_correct: bool, answer_text: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO answer_log (user_id, question_id, is_correct, answer_text, ts)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, question_id, int(is_correct), str(answer_text), time.time()),
    )
    conn.commit()
    conn.close()


def get_question_stats(user_id: str, question_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct_cnt,
            SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS wrong_cnt
        FROM answer_log
        WHERE user_id = ? AND question_id = ?
        """,
        (user_id, question_id),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return 0, 0
    return row[0] or 0, row[1] or 0


def get_chapter_summary(user_id: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT chapter, COUNT(*) AS total
        FROM questions
        GROUP BY chapter
        ORDER BY chapter
        """
    )
    q_total = {r["chapter"]: r["total"] for r in cur.fetchall()}

    cur.execute(
        """
        SELECT q.chapter, COUNT(DISTINCT a.question_id) AS done_cnt
        FROM answer_log a
        JOIN questions q ON a.question_id = q.id
        WHERE a.user_id = ?
        GROUP BY q.chapter
        """,
        (user_id,),
    )
    q_done = {r["chapter"]: r["done_cnt"] for r in cur.fetchall()}

    cur.execute(
        """
        SELECT q.chapter, COUNT(*) AS wrong_cnt
        FROM wrong_log w
        JOIN questions q ON w.question_id = q.id
        WHERE w.user_id = ?
        GROUP BY q.chapter
        """,
        (user_id,),
    )
    q_wrong = {r["chapter"]: r["wrong_cnt"] for r in cur.fetchall()}

    conn.close()

    data = []
    for chap, total in q_total.items():
        done = q_done.get(chap, 0)
        wrong = q_wrong.get(chap, 0)
        data.append(
            {
                "章节": chap,
                "总题数": total,
                "已刷题数": done,
                "错题数": wrong,
                "待刷题数": max(total - done, 0),
            }
        )
    return pd.DataFrame(data)


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
        cnt = cur.fetchone()[0]
        conn.close()
        return cnt

    if mode == "错题重刷":
        sql = """
        SELECT COUNT(*) FROM questions q
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
        cnt = cur.fetchone()[0]
        conn.close()
        return cnt

    if mode == "随机刷题":
        sql = "SELECT COUNT(*) FROM questions WHERE 1=1"
        params = []
        if q_type_filter != "全部":
            sql += " AND q_type = ?"
            params.append(q_type_filter)
        cur.execute(sql, params)
        cnt = cur.fetchone()[0]
        conn.close()
        return cnt

    conn.close()
    return 0


# ========= 模拟考核 =========
def build_exam_paper():
    conn = get_conn()
    cur = conn.cursor()
    exam_questions = []

    for qtype in QTYPE_ORDER:
        cfg = EXAM_CONFIG.get(qtype)
        if not cfg:
            continue
        cur.execute(
            "SELECT id, chapter, q_type, text, options, answer FROM questions WHERE q_type = ?",
            (qtype,),
        )
        rows = list(cur.fetchall())
        random.shuffle(rows)
        need = min(cfg["count"], len(rows))
        exam_questions.extend(rows[:need])

    conn.close()
    exam_questions.sort(key=lambda r: QTYPE_ORDER.index(r["q_type"]))
    return exam_questions


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

        detail.append(
            {
                "题号": idx + 1,
                "题型": qtype,
                "得分": gain,
                "应得分": per_score,
                "是否正确": "√" if is_correct else "×",
            }
        )

    df = pd.DataFrame(detail)
    return total_score, df


# ========= SessionState =========
def init_session():
    ss = st.session_state
    if "mode" not in ss:
        ss.mode = "章节刷题"

    if "q_history" not in ss:
        ss.q_history = []
    if "q_index" not in ss:
        ss.q_index = -1

    if "show_answer" not in ss:
        ss.show_answer = False
    if "judge_result" not in ss:
        ss.judge_result = None

    if "user_choice" not in ss:
        ss.user_choice = None
    if "user_multi" not in ss:
        ss.user_multi = []
    if "user_text" not in ss:
        ss.user_text = ""

    if "practice_start_ts" not in ss:
        ss.practice_start_ts = None

    if "confirm_clear" not in ss:
        ss.confirm_clear = False

    if "exam_questions" not in ss:
        ss.exam_questions = []
    if "exam_answers" not in ss:
        ss.exam_answers = {}
    if "exam_index" not in ss:
        ss.exam_index = 0
    if "exam_start_ts" not in ss:
        ss.exam_start_ts = None
    if "exam_finished" not in ss:
        ss.exam_finished = False
    if "exam_result" not in ss:
        ss.exam_result = None


# ========= 主界面 =========
def main():
    st.set_page_config(
        page_title="刷题小玩意儿-川",
        page_icon="🧠",
        layout="wide",
    )
    init_session()
    init_db()
    import_csv_if_empty()
    ss = st.session_state

    # 全局样式：红黑主题
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top left, #470000 0, #070707 40%, #000000 100%);
            color: #f5f5f5;
        }
        /* 顶部标题 */
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
        /* 题目卡片 */
        .question-card {
            padding: 1.4rem 1.6rem;
            border-radius: 10px;
            border: 1px solid #ff525233;
            background: linear-gradient(145deg,#121212,#050505);
            box-shadow: 0 8px 20px rgba(0,0,0,0.5);
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
        /* 按钮统一红色 */
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
            box-shadow: 0 0 0 1px #ff8a65;
        }
        /* 侧边栏标题颜色 */
        section[data-testid="stSidebar"] h1, 
        section[data-testid="stSidebar"] h2, 
        section[data-testid="stSidebar"] h3 {
            color: #ff8a65;
        }
        /* tabs 边框 */
        .stTabs [data-baseweb="tab-list"] {
            gap: 1rem;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 999px;
            padding: 0.3rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="main-title">刷题小玩意儿-川</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-title">章节刷题 · 错题重刷 · 随机刷题 · 模拟考核</div>',
        unsafe_allow_html=True,
    )

    # 侧边栏
    with st.sidebar:
        st.header("基本设置")

        user_id = st.text_input("用户名", value="student01").strip() or "student01"

        mode = st.selectbox(
            "刷题模式",
            ["章节刷题", "错题重刷", "随机刷题", "模拟考核"],
            index=["章节刷题", "错题重刷", "随机刷题", "模拟考核"].index(ss.mode),
        )
        ss.mode = mode

        chapters = get_all_chapters()
        chapter = "全部"
        if mode in ["章节刷题", "错题重刷"]:
            chapter = st.selectbox(
                "按章节（仅章节刷题 / 错题重刷生效）",
                ["全部"] + chapters,
                index=0,
            )

        q_type_filter = "全部"
        if mode in ["章节刷题", "错题重刷", "随机刷题"]:
            q_type_filter = st.selectbox(
                "题型筛选",
                ["全部"] + QTYPE_ORDER,
                index=0 if mode != "随机刷题" else 1,
            )

        st.markdown("---")
        st.subheader("统计信息")
        total_cnt = get_available_count(user_id, mode, chapter, q_type_filter)
        st.write(f"当前模式可选题数：**{total_cnt}**")

        st.markdown("---")
        st.subheader("数据管理")
        if not ss.confirm_clear:
            if st.button("清空本用户错题本和答题记录"):
                ss.confirm_clear = True
                st.rerun()
        else:
            st.warning("确定要清空本用户的错题本和所有答题记录吗？此操作不可恢复。")
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                if st.button("确定清空"):
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM wrong_log WHERE user_id = ?", (user_id,))
                    cur.execute("DELETE FROM answer_log WHERE user_id = ?", (user_id,))
                    conn.commit()
                    conn.close()
                    ss.confirm_clear = False
                    st.success("已清空当前用户的错题本与答题记录。")
                    st.rerun()
            with col_c2:
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

    if ss.practice_start_ts is None:
        ss.practice_start_ts = time.time()

    if ss.q_index == -1 or not ss.q_history:
        q = fetch_question_for_mode(
            user_id,
            mode,
            chapter=chapter,
            q_type_filter=q_type_filter,
            exclude_ids=[],
        )
        if not q:
            st.info("当前条件下没有可用题目，请调整章节或题型筛选。")
            return
        ss.q_history = [dict(q)]
        ss.q_index = 0

    current = ss.q_history[ss.q_index]
    qid = current["id"]

    elapsed = int(time.time() - (ss.practice_start_ts or time.time()))
    st.markdown(f"**当前练习用时：{format_hms(elapsed)}**")
    st.markdown("---")

    st.markdown('<div class="question-card">', unsafe_allow_html=True)
    tag_html = (
        f'<span class="tag">{escape_html(current["chapter"])}</span>'
        f'<span class="tag">{escape_html(current["q_type"])}</span>'
    )
    st.markdown(tag_html, unsafe_allow_html=True)
    st.markdown(f"**第 {ss.q_index + 1} 题：** {escape_html(current['text'])}")

    options = (current["options"] or "").split("||") if current["options"] else []
    qtype = current["q_type"]

    if qtype == "单选题":
        ss.user_choice = st.radio(
            "请选择一个答案：",
            options,
            index=None,
            key=f"single_{qid}_{ss.q_index}",
        )
    elif qtype == "多选题":
        ss.user_multi = st.multiselect(
            "请选择一个或多个答案：",
            options,
            default=ss.user_multi,
            key=f"multi_{qid}_{ss.q_index}",
        )
    elif qtype == "判断题":
        ss.user_choice = st.radio(
            "请选择：",
            ["对", "错"],
            index=None,
            key=f"judge_{qid}_{ss.q_index}",
        )
    else:
        ss.user_text = st.text_area(
            "请填写答案：",
            value=ss.user_text,
            key=f"blank_{qid}_{ss.q_index}",
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("提交 / 检查答案"):
            std = current["answer"]
            if qtype == "多选题":
                user_ans = ss.user_multi
            elif qtype in ["单选题", "判断题"]:
                if ss.user_choice is None:
                    user_ans = ""
                else:
                    txt = str(ss.user_choice).strip()
                    user_ans = txt[0] if txt and txt[0].isalpha() else txt
            else:
                user_ans = ss.user_text

            is_correct = check_answer(qtype, user_ans, std)
            ans_str = (
                "".join(user_ans) if isinstance(user_ans, list) else str(user_ans)
            )
            log_answer(user_id, qid, is_correct, ans_str)
            if is_correct:
                remove_from_wrong(user_id, qid)
            else:
                record_wrong(user_id, qid)

            ss.show_answer = True
            ss.judge_result = is_correct

    with col2:
        if st.button("上一题"):
            if ss.q_index > 0:
                ss.q_index -= 1
                ss.show_answer = False
                ss.judge_result = None
                st.rerun()

    with col3:
        if st.button("下一题"):
            if ss.q_index < len(ss.q_history) - 1:
                ss.q_index += 1
            else:
                exclude_ids = [q["id"] for q in ss.q_history]
                q_next = fetch_question_for_mode(
                    user_id,
                    mode,
                    chapter=chapter,
                    q_type_filter=q_type_filter,
                    exclude_ids=exclude_ids,
                )
                if q_next:
                    ss.q_history.append(dict(q_next))
                    ss.q_index += 1
                else:
                    st.info("当前条件下没有更多题目了。")
            ss.show_answer = False
            ss.judge_result = None
            ss.user_choice = None
            ss.user_multi = []
            ss.user_text = ""
            st.rerun()

    if ss.show_answer and ss.judge_result is not None:
        std = current["answer"]
        if ss.judge_result:
            st.success(f"回答正确！标准答案：{std}")
        else:
            st.error(f"回答错误。标准答案：{std}")

    correct_cnt, wrong_cnt = get_question_stats(user_id, qid)
    st.info(f"本题统计 —— 答对：{correct_cnt} 次；答错：{wrong_cnt} 次。")

    st.markdown("</div>", unsafe_allow_html=True)

    time.sleep(1)
    st.rerun()


# ========= 模拟考核界面 =========
def render_exam_tab(user_id: str):
    ss = st.session_state

    if not ss.exam_questions and not ss.exam_finished:
        st.subheader("模拟考核说明")
        lines = []
        for qt in QTYPE_ORDER:
            cfg = EXAM_CONFIG.get(qt)
            if cfg:
                lines.append(f"- {qt}：{cfg['count']} 题，每题 {cfg['score']} 分")
        st.markdown("\n".join(lines))
        st.markdown("- 总时长：60 分钟，超时将自动交卷")
        st.markdown("- 题型顺序：**单选 → 多选 → 判断 → 填空**")

        if st.button("开始模拟考核"):
            ss.exam_questions = [dict(r) for r in build_exam_paper()]
            ss.exam_answers = {}
            ss.exam_index = 0
            ss.exam_start_ts = time.time()
            ss.exam_finished = False
            ss.exam_result = None
            st.rerun()
        return

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
            st.rerun()
        return

    questions = ss.exam_questions
    if not questions:
        st.info("暂无试卷，请重新开始模拟考核。")
        return

    if ss.exam_start_ts is None:
        ss.exam_start_ts = time.time()

    elapsed = int(time.time() - ss.exam_start_ts)
    remain = 60 * 60 - elapsed
    if remain <= 0:
        total, df = grade_exam(user_id, questions, ss.exam_answers)
        ss.exam_finished = True
        ss.exam_result = (total, df)
        st.warning("考试时间已结束，系统已自动交卷。")
        st.rerun()
        return

    st.markdown(
        f"**考试用时：{format_hms(elapsed)} ；剩余时间：{format_hms(remain)}**"
    )
    st.markdown("---")

    idx = ss.exam_index
    row = questions[idx]
    qid = row["id"]
    qtype = row["q_type"]
    options = (row["options"] or "").split("||") if row["options"] else []

    st.markdown('<div class="question-card">', unsafe_allow_html=True)
    tag_html = (
        f'<span class="tag">{escape_html(row["chapter"])}</span>'
        f'<span class="tag">{escape_html(row["q_type"])}</span>'
    )
    st.markdown(tag_html, unsafe_allow_html=True)
    st.markdown(f"**第 {idx + 1} 题 / 共 {len(questions)} 题：** {escape_html(row['text'])}")

    current_ans = ss.exam_answers.get(idx)

    if qtype == "单选题":
        if isinstance(current_ans, str) and current_ans:
            default_index = -1
            for i, opt in enumerate(options):
                if opt.strip().startswith(current_ans):
                    default_index = i
                    break
        else:
            default_index = None
        choice = st.radio(
            "请选择一个答案：",
            options,
            index=default_index,
            key=f"exam_single_{idx}",
        )
        if choice:
            txt = str(choice).strip()
            ans = txt[0] if txt and txt[0].isalpha() else txt
            ss.exam_answers[idx] = ans

    elif qtype == "多选题":
        default = current_ans if isinstance(current_ans, list) else []
        multi = st.multiselect(
            "请选择一个或多个答案：",
            options,
            default=default,
            key=f"exam_multi_{idx}",
        )
        letters = []
        for opt in multi:
            t = str(opt).strip()
            letters.append(t[0] if t and t[0].isalpha() else t)
        ss.exam_answers[idx] = letters

    elif qtype == "判断题":
        choice = st.radio(
            "请选择：",
            ["对", "错"],
            index=0 if current_ans == "对" else 1 if current_ans == "错" else None,
            key=f"exam_judge_{idx}",
        )
        if choice:
            ss.exam_answers[idx] = choice

    else:
        text = st.text_area(
            "请填写答案：",
            value=current_ans or "",
            key=f"exam_blank_{idx}",
        )
        ss.exam_answers[idx] = text

    st.markdown("</div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("上一题"):
            if ss.exam_index > 0:
                ss.exam_index -= 1
                st.rerun()
    with col2:
        if st.button("下一题"):
            if ss.exam_index < len(questions) - 1:
                ss.exam_index += 1
                st.rerun()
    with col3:
        if st.button("交卷"):
            total, df = grade_exam(user_id, questions, ss.exam_answers)
            ss.exam_finished = True
            ss.exam_result = (total, df)
            st.rerun()

    time.sleep(1)
    st.rerun()


# ========= 错题汇总 =========
def render_wrong_summary(user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            q.chapter,
            q.q_type,
            q.text,
            q.options,
            q.answer,
            w.wrong_count,
            w.last_wrong_ts
        FROM wrong_log w
        JOIN questions q ON w.question_id = q.id
        WHERE w.user_id = ?
        ORDER BY q.chapter, q.q_type, w.last_wrong_ts DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        st.info("当前用户暂无错题记录。")
        return

    data = []
    for r in rows:
        data.append(
            {
                "章节": r["chapter"],
                "题型": r["q_type"],
                "题干": r["text"],
                "标准答案": r["answer"],
                "错题次数": r["wrong_count"],
            }
        )
    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True)


if __name__ == "__main__":
    main()
# ... existing code ...
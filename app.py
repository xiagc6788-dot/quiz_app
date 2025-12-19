import streamlit as st
import sqlite3
import pandas as pd
from pathlib import Path
import time
import random

DB_PATH = Path("quiz.db")
CSV_PATH = Path("questions.csv")

# 模拟考核题量与分值配置
EXAM_CONFIG = {
    "单选题": {"count": 30, "score": 1},
    "多选题": {"count": 20, "score": 2},
    "判断题": {"count": 20, "score": 1},
    "填空题": {"count": 10, "score": 1},
}


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # 题目表
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter TEXT,
            q_type TEXT,
            text TEXT,
            options TEXT,
            answer TEXT
        )
        """
    )
    # 错题记录表（每题一条，记录是否曾错）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS wrong_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            question_id INTEGER,
            wrong_count INTEGER DEFAULT 1,
            last_wrong_ts REAL,
            UNIQUE(user_id, question_id)
        )
        """
    )
    # 答题记录表（每次作答一条，用于统计）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS answer_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            question_id INTEGER,
            is_correct INTEGER,
            answer_text TEXT,
            ts REAL
        )
        """
    )
    conn.commit()
    conn.close()


def import_csv_if_empty():
    """如果 questions 表为空，则从 questions.csv 导入题目"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) FROM questions")
    count = cur.fetchone()[0]
    if count == 0:
        if not CSV_PATH.exists():
            st.error(f"未找到题库文件 {CSV_PATH}, 请先准备 questions.csv")
            st.stop()
        df = pd.read_csv(CSV_PATH)
        df = df.fillna("")
        for _, row in df.iterrows():
            cur.execute(
                """
                INSERT INTO questions (chapter, q_type, text, options, answer)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["chapter"],
                    row["q_type"],
                    row["text"],
                    row.get("options", ""),
                    str(row["answer"]).strip(),
                ),
            )
        conn.commit()
    conn.close()


def get_chapters():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT chapter FROM questions ORDER BY chapter")
    chapters = [r[0] for r in cur.fetchall()]
    conn.close()
    return chapters


def fetch_random_question(user_id, mode, chapter=None, exclude_ids=None, q_type=None):
    """
    按模式/章节/题型随机抽一道题。
    mode: "章节刷题" / "错题重刷" / "随机刷题"
    """
    conn = get_conn()
    cur = conn.cursor()

    base_sql = "SELECT q.id, q.chapter, q.q_type, q.text, q.options, q.answer FROM questions q"
    clauses = []
    params = []

    if mode == "错题重刷":
        clauses.append(
            "q.id IN (SELECT question_id FROM wrong_log WHERE user_id = ?)"
        )
        params.append(user_id)

    if mode == "章节刷题" and chapter:
        clauses.append("q.chapter = ?")
        params.append(chapter)

    if mode == "随机刷题" and q_type:
        clauses.append("q.q_type = ?")
        params.append(q_type)

    if exclude_ids:
        placeholders = ",".join("?" for _ in exclude_ids)
        clauses.append(f"q.id NOT IN ({placeholders})")
        params.extend(exclude_ids)

    if clauses:
        base_sql += " WHERE " + " AND ".join(clauses)

    sql = base_sql + " ORDER BY RANDOM() LIMIT 1"
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "chapter": row[1],
        "q_type": row[2],
        "text": row[3],
        "options": row[4],
        "answer": row[5],
    }


def record_wrong(user_id, question_id):
    conn = get_conn()
    cur = conn.cursor()
    ts = time.time()
    cur.execute(
        """
        INSERT INTO wrong_log (user_id, question_id, wrong_count, last_wrong_ts)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, question_id)
        DO UPDATE SET wrong_count = wrong_count + 1, last_wrong_ts = excluded.last_wrong_ts
        """,
        (user_id, question_id, ts),
    )
    conn.commit()
    conn.close()


def remove_from_wrong(user_id, question_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM wrong_log WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    )
    conn.commit()
    conn.close()


def log_answer(user_id, question_id, is_correct: bool, answer_text: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO answer_log (user_id, question_id, is_correct, answer_text, ts)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, question_id, 1 if is_correct else 0, answer_text, time.time()),
    )
    conn.commit()
    conn.close()


def normalize_tf(x: str) -> str:
    x = x.strip()
    if x in ("对", "√", "True", "true"):
        return "对"
    if x in ("错", "×", "False", "false"):
        return "错"
    return x


def escape_html(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def check_answer(q_type: str, user_answer: str, std_answer: str) -> bool:
    """统一判分规则"""
    user_answer = (user_answer or "").strip()
    std_answer = (std_answer or "").strip()
    if q_type == "判断题":
        return normalize_tf(user_answer) == normalize_tf(std_answer)
    if q_type == "多选题":
        return "".join(sorted(user_answer)) == "".join(sorted(std_answer))
    # 单选/填空：完全匹配
    return user_answer == std_answer


def format_hms(seconds: float) -> str:
    """秒数格式化为 mm:ss 或 hh:mm:ss"""
    s = max(int(seconds), 0)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"


# -------- 统计相关 --------
def get_chapter_stats():
    """返回章节题目数量统计：{chapter: count}"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT chapter, COUNT(1) FROM questions GROUP BY chapter ORDER BY chapter"
    )
    rows = cur.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def get_total_question_count():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(1) FROM questions")
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_wrong_count(user_id, chapter=None):
    conn = get_conn()
    cur = conn.cursor()
    sql = """
        SELECT COUNT(DISTINCT q.id)
        FROM wrong_log wl
        JOIN questions q ON wl.question_id = q.id
        WHERE wl.user_id = ?
    """
    params = [user_id]
    if chapter:
        sql += " AND q.chapter = ?"
        params.append(chapter)
    cur.execute(sql, params)
    n = cur.fetchone()[0]
    conn.close()
    return n


def get_wrong_list(user_id, chapter=None):
    """返回当前用户的错题列表 + 每题正确/错误次数"""
    conn = get_conn()
    cur = conn.cursor()
    sql = """
        SELECT q.id, q.chapter, q.q_type, q.text, q.answer
        FROM wrong_log wl
        JOIN questions q ON wl.question_id = q.id
        WHERE wl.user_id = ?
    """
    params = [user_id]
    if chapter:
        sql += " AND q.chapter = ?"
        params.append(chapter)
    sql += " ORDER BY q.chapter"
    cur.execute(sql, params)
    rows = cur.fetchall()

    q_ids = [r[0] for r in rows]
    stats = {qid: {"correct": 0, "wrong": 0} for qid in q_ids}
    if q_ids:
        placeholders = ",".join("?" for _ in q_ids)
        cur.execute(
            f"""
            SELECT question_id,
                   SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct_cnt,
                   SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END) AS wrong_cnt
            FROM answer_log
            WHERE user_id = ?
              AND question_id IN ({placeholders})
            GROUP BY question_id
            """,
            [user_id, *q_ids],
        )
        for qid, c, w in cur.fetchall():
            stats[qid] = {"correct": c or 0, "wrong": w or 0}

    conn.close()

    result = []
    for r in rows:
        qid = r[0]
        result.append(
            {
                "id": qid,
                "chapter": r[1],
                "q_type": r[2],
                "text": r[3],
                "answer": r[4],
                "wrong_count": stats[qid]["wrong"],
                "correct_count": stats[qid]["correct"],
            }
        )
    return result


def get_user_summary_by_chapter(user_id):
    """返回每章：总题数 / 已做题数 / 错题数 / 待刷题数"""
    total = get_chapter_stats()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT q.chapter,
               COUNT(DISTINCT al.question_id) AS done_cnt,
               COUNT(DISTINCT CASE WHEN al.is_correct=0 THEN al.question_id END) AS wrong_cnt
        FROM answer_log al
        JOIN questions q ON al.question_id = q.id
        WHERE al.user_id = ?
        GROUP BY q.chapter
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()

    done_map = {r[0]: r[1] for r in rows}
    wrong_map = {r[0]: r[2] for r in rows}

    summary = []
    for chap, cnt in total.items():
        done = done_map.get(chap, 0)
        wrong = wrong_map.get(chap, 0)
        wait = max(cnt - done, 0)
        summary.append(
            {
                "chapter": chap,
                "total": cnt,
                "done": done,
                "wrong": wrong,
                "wait": wait,
            }
        )
    return summary


def get_available_question_count(user_id, mode, chapter=None, q_type=None):
    """
    当前刷题模式下，可用题目总数，用于显示“第 X / N 题”里的 N。
    """
    conn = get_conn()
    cur = conn.cursor()

    if mode == "章节刷题":
        if chapter:
            cur.execute(
                "SELECT COUNT(1) FROM questions WHERE chapter = ?", (chapter,)
            )
        else:
            cur.execute("SELECT COUNT(1) FROM questions")
    elif mode == "错题重刷":
        sql = """
            SELECT COUNT(DISTINCT q.id)
            FROM wrong_log wl
            JOIN questions q ON wl.question_id = q.id
            WHERE wl.user_id = ?
        """
        params = [user_id]
        if chapter:
            sql += " AND q.chapter = ?"
            params.append(chapter)
        cur.execute(sql, params)
    elif mode == "随机刷题":
        if q_type:
            cur.execute(
                "SELECT COUNT(1) FROM questions WHERE q_type = ?", (q_type,)
            )
        else:
            cur.execute("SELECT COUNT(1) FROM questions")
    else:
        cur.execute("SELECT COUNT(1) FROM questions")

    row = cur.fetchone()
    conn.close()
    return (row[0] or 0) if row else 0


# -------- 模拟考核相关 --------
def build_exam_paper():
    """按 EXAM_CONFIG 从题库中构建一次模拟考试试卷"""
    conn = get_conn()
    cur = conn.cursor()
    questions = []
    for q_type, cfg in EXAM_CONFIG.items():
        cur.execute(
            """
            SELECT id, chapter, q_type, text, options, answer
            FROM questions
            WHERE q_type = ?
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (q_type, cfg["count"]),
        )
        for row in cur.fetchall():
            questions.append(
                {
                    "id": row[0],
                    "chapter": row[1],
                    "q_type": row[2],
                    "text": row[3],
                    "options": row[4],
                    "answer": row[5],
                    "score": cfg["score"],
                }
            )
    conn.close()
    random.shuffle(questions)
    return questions


def save_exam_answer_for_current(user_answer_str):
    """将当前试题的作答存入 exam_answers"""
    if not st.session_state.exam_questions:
        return
    idx = st.session_state.exam_index
    if idx < 0 or idx >= len(st.session_state.exam_questions):
        return
    q = st.session_state.exam_questions[idx]
    st.session_state.exam_answers[q["id"]] = user_answer_str or ""


def grade_exam(user_id):
    """交卷评分，并写入答题记录 / 错题本"""
    questions = st.session_state.exam_questions
    answers = st.session_state.exam_answers
    total_score = 0
    by_type = {}
    for q_type in EXAM_CONFIG.keys():
        by_type[q_type] = {"score": 0, "max": 0}

    for q in questions:
        q_type = q["q_type"]
        score_each = q["score"]
        by_type[q_type]["max"] += score_each

        user_ans = (answers.get(q["id"], "") or "").strip()
        std_ans = (q["answer"] or "").strip()
        ok = check_answer(q_type, user_ans, std_ans)
        if ok:
            total_score += score_each
            by_type[q_type]["score"] += score_each
            log_answer(user_id, q["id"], True, user_ans)
            remove_from_wrong(user_id, q["id"])
        else:
            log_answer(user_id, q["id"], False, user_ans)
            record_wrong(user_id, q["id"])

    st.session_state.exam_finished = True
    st.session_state.exam_result = {
        "total": total_score,
        "by_type": by_type,
        "max_total": sum(
            cfg["count"] * cfg["score"] for cfg in EXAM_CONFIG.values()
        ),
    }


# ----------------- Streamlit UI -----------------

st.set_page_config(page_title="刷题小玩意儿-川", layout="wide")

init_db()
import_csv_if_empty()

# 简单美化：全局 CSS
st.markdown(
    """
    <style>
    .main > div {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    h1 {
        margin-bottom: 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 侧边栏：基础设置
st.sidebar.header("基本设置")
user_id = st.sidebar.text_input("用户名", value="student01")

mode = st.sidebar.selectbox(
    "刷题模式",
    ["章节刷题", "错题重刷", "随机刷题", "模拟考核"],
)

chapters = get_chapters()
chapter_stats = get_chapter_stats()

chapter_filter = st.sidebar.selectbox(
    "按章节（仅章节刷题/错题重刷时生效）", ["全部"] + chapters
)
if chapter_filter == "全部":
    chapter_filter = None

qtype_filter = None
if mode == "随机刷题":
    qtype_filter = st.sidebar.selectbox(
        "随机刷题 - 题型选择",
        ["单选题", "多选题", "判断题", "填空题"],
    )

# 侧边栏统计信息
st.sidebar.markdown("---")
total_q = get_total_question_count()

# 已做题数（全部）
conn_tmp = get_conn()
cur_tmp = conn_tmp.cursor()
cur_tmp.execute(
    "SELECT COUNT(DISTINCT question_id) FROM answer_log WHERE user_id = ?",
    (user_id,),
)
done_total = cur_tmp.fetchone()[0] or 0
conn_tmp.close()

wrong_total = get_wrong_count(user_id)
wait_total = max(total_q - done_total, 0)

if mode in ("章节刷题", "错题重刷") and chapter_filter:
    wrong_chap = get_wrong_count(user_id, chapter_filter)
else:
    wrong_chap = None

st.sidebar.markdown(f"**题目总数：** {total_q}")
st.sidebar.markdown(f"**已刷题数：** {done_total}")
st.sidebar.markdown(f"**待刷题数：** {wait_total}")
st.sidebar.markdown(f"**当前用户错题数（全部）：** {wrong_total}")
if wrong_chap is not None:
    st.sidebar.markdown(f"**当前章节错题数：** {wrong_chap}")

# 清空按钮增加确认
st.sidebar.markdown("---")
if "confirm_clear" not in st.session_state:
    st.session_state.confirm_clear = False

if st.sidebar.button("清空本用户错题本和答题记录"):
    st.session_state.confirm_clear = True

if st.session_state.confirm_clear:
    st.sidebar.warning("确认要清空本用户的错题本和答题记录吗？此操作不可恢复。")
    c1, c2 = st.sidebar.columns(2)
    with c1:
        if st.button("确定清空", key="btn_clear_yes"):
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM wrong_log WHERE user_id = ?", (user_id,))
            cur.execute("DELETE FROM answer_log WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            st.sidebar.success("已清空")
            st.session_state.confirm_clear = False
    with c2:
        if st.button("取消", key="btn_clear_no"):
            st.session_state.confirm_clear = False

# session_state 初始化
if "q_history" not in st.session_state:
    st.session_state.q_history = []  # 当前模式下已出过的题目
if "q_index" not in st.session_state:
    st.session_state.q_index = -1
if "show_answer" not in st.session_state:
    st.session_state.show_answer = False
if "user_choice" not in st.session_state:
    st.session_state.user_choice = None
if "user_multi" not in st.session_state:
    st.session_state.user_multi = []
if "user_text" not in st.session_state:
    st.session_state.user_text = ""
# 本题判分结果
if "judge_result" not in st.session_state:
    st.session_state.judge_result = None
# 练习 / 考试计时
if "practice_start_ts" not in st.session_state:
    st.session_state.practice_start_ts = None
if "exam_start_ts" not in st.session_state:
    st.session_state.exam_start_ts = None
if "exam_auto_timeout" not in st.session_state:
    st.session_state.exam_auto_timeout = False

# 记录上一次的模式/章节/题型，用于切换模式时重置历史
if "last_mode" not in st.session_state:
    st.session_state.last_mode = None
if "last_chapter_filter" not in st.session_state:
    st.session_state.last_chapter_filter = None
if "last_qtype_filter" not in st.session_state:
    st.session_state.last_qtype_filter = None

# 模拟考核状态
if "exam_questions" not in st.session_state:
    st.session_state.exam_questions = []
if "exam_index" not in st.session_state:
    st.session_state.exam_index = 0
if "exam_answers" not in st.session_state:
    st.session_state.exam_answers = {}
if "exam_finished" not in st.session_state:
    st.session_state.exam_finished = False
if "exam_result" not in st.session_state:
    st.session_state.exam_result = None


def reset_practice_state():
    st.session_state.q_history = []
    st.session_state.q_index = -1
    st.session_state.show_answer = False
    st.session_state.user_choice = None
    st.session_state.user_multi = []
    st.session_state.user_text = ""
    st.session_state.judge_result = None
    st.session_state.practice_start_ts = time.time()


def start_new_exam():
    paper = build_exam_paper()
    if not paper:
        st.warning("题库不足，无法生成模拟考核试卷。")
        return
    st.session_state.exam_questions = paper
    st.session_state.exam_index = 0
    st.session_state.exam_answers = {}
    st.session_state.exam_finished = False
    st.session_state.exam_result = None
    st.session_state.exam_auto_timeout = False
    st.session_state.exam_start_ts = time.time()


# 若模式 / 章节 / 题型改变，则重置练习状态
if (
    st.session_state.last_mode != mode
    or st.session_state.last_chapter_filter != chapter_filter
    or st.session_state.last_qtype_filter != qtype_filter
):
    reset_practice_state()
    st.session_state.last_mode = mode
    st.session_state.last_chapter_filter = chapter_filter
    st.session_state.last_qtype_filter = qtype_filter

st.title("刷题小玩意儿-川")

tab_quiz, tab_wrong, tab_summary = st.tabs(["刷题 / 考核", "错题汇总", "题目汇总"])

# ------------ 标签页 1：刷题 / 模拟考核 ------------
with tab_quiz:
    if mode == "模拟考核":
        st.subheader("模拟考核（总分 100 分）")
        st.markdown(
            """
            - 单选题：30 题，每题 1 分，共 30 分  
            - 多选题：20 题，每题 2 分，共 40 分（少选/错选均 0 分）  
            - 判断题：20 题，每题 1 分，共 20 分  
            - 填空题：10 题，每题 1 分，共 10 分（必须完全匹配）  
            - 考试时长：60 分钟  
            """
        )

        # 开始 / 重新开始按钮
        if not st.session_state.exam_questions or st.session_state.exam_finished:
            btn_label = (
                "开始模拟考核"
                if not st.session_state.exam_questions
                else "重新开始模拟考核"
            )
            if st.button(btn_label):
                start_new_exam()
                st.rerun()

        # 若已完成考试，直接显示成绩
        if st.session_state.exam_finished and st.session_state.exam_result:
            r = st.session_state.exam_result
            st.markdown("---")
            if st.session_state.exam_auto_timeout:
                st.warning("考试时间已到，系统已自动交卷。")
            st.success(
                f"本次模拟考核得分：**{r['total']} / {r['max_total']} 分**"
            )
            st.markdown("**各题型得分情况：**")
            for q_type, info in r["by_type"].items():
                st.markdown(
                    f"- {q_type}：{info['score']} / {info['max']} 分"
                )
            st.info("如需重考，请点击上方“重新开始模拟考核”。")

        elif not st.session_state.exam_questions:
            st.info("请点击上方按钮生成试卷。")
        else:
            # 考试进行中：倒计时 & 自动交卷
            now = time.time()
            if st.session_state.exam_start_ts is None:
                st.session_state.exam_start_ts = now
            elapsed = now - st.session_state.exam_start_ts
            remaining = 60 * 60 - elapsed

            if remaining <= 0:
                # 时间到，自动交卷（只触发一次）
                if not st.session_state.exam_finished:
                    save_exam_answer_for_current("")
                    grade_exam(user_id)
                    st.session_state.exam_auto_timeout = True
                    st.rerun()
                remaining = 0

            # 右上角显示用时 & 剩余时间
            c1, c2 = st.columns([3, 2])
            with c2:
                st.markdown(
                    f"**已用时间：{format_hms(elapsed)}**  \n"
                    f"**剩余时间：{format_hms(remaining)}**"
                )

            q = st.session_state.exam_questions[st.session_state.exam_index]
            total_num = len(st.session_state.exam_questions)
            st.markdown(
                f"**第 {st.session_state.exam_index + 1} / {total_num} 题**  "
                f"（章节：{q['chapter']}，题型：{q['q_type']}）"
            )
            st.markdown("---")
            st.markdown(q["text"])

            # 取已有答案以便切换题目时保留
            current_user_answer = st.session_state.exam_answers.get(q["id"], "")

            user_answer_str = None
            if q["q_type"] in ("单选题", "多选题"):
                option_str = q["options"] or ""
                options = [o.strip() for o in option_str.split("||") if o.strip()]
                if not options:
                    st.error("题目选项为空，请检查题库数据。")
                else:
                    if q["q_type"] == "单选题":
                        # 推断当前选择
                        default_index = 0
                        if current_user_answer:
                            for i, opt in enumerate(options):
                                letter = opt.split(".", 1)[0].strip()[0]
                                if letter == current_user_answer:
                                    default_index = i
                                    break
                        choice = st.radio("请选择：", options, index=default_index)
                        if "." in choice:
                            user_answer_str = choice.split(".", 1)[0].strip()[0]
                        else:
                            user_answer_str = choice[0].strip()
                    else:
                        default_multi = []
                        if current_user_answer:
                            letters_set = set(current_user_answer)
                            for opt in options:
                                letter = opt.split(".", 1)[0].strip()[0]
                                if letter in letters_set:
                                    default_multi.append(opt)
                        selected = st.multiselect("可多选：", options, default=default_multi)
                        if selected:
                            letters = []
                            for it in selected:
                                if "." in it:
                                    letters.append(it.split(".", 1)[0].strip()[0])
                                else:
                                    letters.append(it[0].strip())
                            user_answer_str = "".join(sorted(letters))
                        else:
                            user_answer_str = ""
            elif q["q_type"] == "判断题":
                default_idx = 0 if current_user_answer in ("对", "") else 1
                choice = st.radio("请选择：", ["对", "错"], index=default_idx)
                user_answer_str = normalize_tf(choice)
            elif q["q_type"] == "填空题":
                ans = st.text输入("请输入答案：", value=current_user_answer)
                user_answer_str = ans.strip()
            else:
                ans = st.text_area("请输入答案：", value=current_user_answer)
                user_answer_str = ans.strip()

            cols = st.columns(3)
            with cols[0]:
                if st.button("上一题") and st.session_state.exam_index > 0:
                    save_exam_answer_for_current(user_answer_str)
                    st.session_state.exam_index -= 1
                    st.rerun()
            with cols[1]:
                if st.button("下一题"):
                    save_exam_answer_for_current(user_answer_str)
                    if st.session_state.exam_index < len(
                        st.session_state.exam_questions
                    ) - 1:
                        st.session_state.exam_index += 1
                        st.rerun()
            with cols[2]:
                if st.button("交卷评分"):
                    save_exam_answer_for_current(user_answer_str)
                    grade_exam(user_id)
                    st.rerun()

            # 考试进行中自动每秒刷新一次
            time.sleep(1)
            st.rerun()

    else:
        # 普通刷题模式（章节刷题 / 错题重刷 / 随机刷题）
        # 练习用时（正序）——右上角显示
        if st.session_state.practice_start_ts is None:
            st.session_state.practice_start_ts = time.time()
        elapsed_practice = time.time() - st.session_state.practice_start_ts
        c1, c2 = st.columns([3, 2])
        with c2:
            st.markdown(f"**当前练习用时：{format_hms(elapsed_practice)}**")

        if mode == "章节刷题" and not chapter_filter:
            st.warning("章节刷题模式下，请先在左侧选择章节。")
        elif mode == "随机刷题" and not qtype_filter:
            st.warning("随机刷题模式下，请先在左侧选择题型。")
        else:
            # 如果没有题目历史，就加载第一题
            if st.session_state.q_index == -1 or not st.session_state.q_history:
                exclude_ids = None
                q = fetch_random_question(
                    user_id=user_id,
                    mode=mode,
                    chapter=chapter_filter,
                    exclude_ids=exclude_ids,
                    q_type=qtype_filter,
                )
                if q:
                    st.session_state.q_history.append(q)
                    st.session_state.q_index = 0

            if not st.session_state.q_history:
                if mode == "错题重刷":
                    st.info("当前模式下没有可刷的错题。")
                else:
                    st.info("当前模式下没有题目，请检查题库或筛选条件。")
            else:
                q = st.session_state.q_history[st.session_state.q_index]

                # 序号：第 X / N 题
                total_available = get_available_question_count(
                    user_id, mode, chapter_filter, qtype_filter
                )
                st.markdown(
                    f"**第 {st.session_state.q_index + 1} / {total_available} 题**"
                )

                st.markdown(f"**章节：{q['chapter']}**")
                st.markdown(f"**题型：{q['q_type']}**")
                st.markdown("---")
                st.markdown(q["text"])

                # 当前题统计：正确/错误次数
                conn_s = get_conn()
                cur_s = conn_s.cursor()
                cur_s.execute(
                    """
                    SELECT
                      SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct_cnt,
                      SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END) AS wrong_cnt
                    FROM answer_log
                    WHERE user_id = ? AND question_id = ?
                    """,
                    (user_id, q["id"]),
                )
                row_s = cur_s.fetchone()
                conn_s.close()
                correct_cnt = (row_s[0] or 0) if row_s else 0
                wrong_cnt = (row_s[1] or 0) if row_s else 0
                st.caption(f"本题统计：答对 {correct_cnt} 次，答错 {wrong_cnt} 次")

                user_answer_str = None

                if q["q_type"] in ("单选题", "多选题"):
                    option_str = q["options"] or ""
                    options = [o.strip() for o in option_str.split("||") if o.strip()]
                    if not options:
                        st.error("题目选项为空，请检查题库数据。")
                    else:
                        if q["q_type"] == "单选题":
                            st.session_state.user_choice = st.radio(
                                "请选择：", options, index=0 if options else -1
                            )
                            if st.session_state.user_choice:
                                if "." in st.session_state.user_choice:
                                    user_answer_str = (
                                        st.session_state.user_choice.split(".", 1)[
                                            0
                                        ].strip()[0]
                                    )
                                else:
                                    user_answer_str = (
                                        st.session_state.user_choice[0].strip()
                                    )
                        else:
                            st.session_state.user_multi = st.multiselect(
                                "可多选：", options
                            )
                            if st.session_state.user_multi:
                                letters = []
                                for it in st.session_state.user_multi:
                                    if "." in it:
                                        letters.append(
                                            it.split(".", 1)[0].strip()[0]
                                        )
                                    else:
                                        letters.append(it[0].strip())
                                user_answer_str = "".join(sorted(letters))
                            else:
                                user_answer_str = ""
                elif q["q_type"] == "判断题":
                    choice = st.radio("请选择：", ["对", "错"])
                    user_answer_str = normalize_tf(choice)
                elif q["q_type"] == "填空题":
                    st.session_state.user_text = st.text_input(
                        "请输入答案：", value=st.session_state.user_text
                    )
                    user_answer_str = st.session_state.user_text.strip()
                else:
                    st.session_state.user_text = st.text_area(
                        "请输入答案：", value=st.session_state.user_text
                    )
                    user_answer_str = st.session_state.user_text.strip()

                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("提交判分"):
                        if user_answer_str is None or user_answer_str == "":
                            st.warning("请先作答。")
                        else:
                            std_answer = q["answer"].strip()
                            ok = check_answer(q["q_type"], user_answer_str, std_answer)

                            log_answer(user_id, q["id"], ok, user_answer_str)

                            if ok:
                                st.session_state.judge_result = "correct"
                                remove_from_wrong(user_id, q["id"])
                            else:
                                st.session_state.judge_result = "wrong"
                                record_wrong(user_id, q["id"])
                            st.session_state.show_answer = True

                with col2:
                    if st.button("上一题") and st.session_state.q_index > 0:
                        st.session_state.q_index -= 1
                        st.session_state.show_answer = False
                        st.session_state.judge_result = None
                        st.rerun()

                with col3:
                    if st.button("下一题"):
                        if st.session_state.q_index < len(
                            st.session_state.q_history
                        ) - 1:
                            st.session_state.q_index += 1
                            st.session_state.show_answer = False
                            st.session_state.judge_result = None
                        else:
                            exclude_ids = [x["id"] for x in st.session_state.q_history]
                            q_new = fetch_random_question(
                                user_id=user_id,
                                mode=mode,
                                chapter=chapter_filter,
                                exclude_ids=exclude_ids,
                                q_type=qtype_filter,
                            )
                            if q_new:
                                st.session_state.q_history.append(q_new)
                                st.session_state.q_index = len(
                                    st.session_state.q_history
                                ) - 1
                                st.session_state.show_answer = False
                                st.session_state.judge_result = None
                            else:
                                st.info("当前模式下题目已刷完，将可能开始重复抽题。")
                        st.rerun()

                if st.session_state.show_answer:
                    st.markdown("---")
                    if st.session_state.judge_result == "correct":
                        st.success("回答正确！")
                    elif st.session_state.judge_result == "wrong":
                        st.error("回答错误。")
                    st.markdown(f"**正确答案：** {q['answer']}")

            # 普通刷题模式下，每秒自动刷新一次更新时间
            time.sleep(1)
            st.rerun()

# ------------ 标签页 2：错题汇总 ------------
with tab_wrong:
    st.subheader("错题汇总")

    wrong_chapter_filter = st.selectbox(
        "按章节筛选错题（可选）", ["全部"] + chapters, key="wrong_filter"
    )
    if wrong_chapter_filter == "全部":
        wrong_chapter_filter = None

    wrong_list = get_wrong_list(user_id, wrong_chapter_filter)
    if not wrong_list:
        st.info("当前条件下没有错题记录。")
    else:
        for idx, item in enumerate(wrong_list, 1):
            st.markdown(
                f"**{idx}. [{item['chapter']} - {item['q_type']}]**  {item['text']}"
            )
            st.markdown(
                f"<span style='color:red'>正确答案：{escape_html(item['answer'])}</span> "
                f"（答对 {item['correct_count']} 次，答错 {item['wrong_count']} 次）",
                unsafe_allow_html=True,
            )
            st.markdown("---")

# ------------ 标签页 3：题目汇总 ------------
with tab_summary:
    st.subheader("题目汇总（按章节）")

    summary = get_user_summary_by_chapter(user_id)
    if not summary:
        st.info("题库为空，请先导入 questions.csv。")
    else:
        df = pd.DataFrame(summary)
        df = df.rename(
            columns={
                "chapter": "章节",
                "total": "题目总数",
                "done": "已刷题数",
                "wrong": "错题数",
                "wait": "待刷题数",
            }
        )
        st.dataframe(df, use_container_width=True)
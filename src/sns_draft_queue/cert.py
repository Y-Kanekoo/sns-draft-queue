"""cert-study の選択式問題から下書きを作る。"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

from .config import Config
from .queue import Draft, create_draft, list_drafts
from .xtext import LIMIT, pack_blocks, weighted_length

EXAMS = ("fe", "ap", "jstqb")


def load_questions(source: Path, exam: str) -> tuple[str, list[Draft]]:
    root = source / "content" / exam
    info = cast(Draft, json.loads((root / "exam.json").read_text(encoding="utf-8")))
    questions: list[Draft] = []
    for path in sorted((root / "questions").glob("*.json")):
        items = cast(list[Draft], json.loads(path.read_text(encoding="utf-8")))
        questions.extend(
            q
            for q in items
            if q.get("status") == "verified"
            and q.get("origin") == "original"
            and q.get("type") in {"mcq", "multi"}
        )
    return str(info["shortName"]), sorted(questions, key=lambda q: str(q["id"]))


def choose_question(questions: list[Draft], day: date, used_ids: set[str]) -> Draft:
    available = [q for q in questions if str(q["id"]) not in used_ids] or questions
    if not available:
        raise ValueError("投稿対象の問題がありません")
    ranked = sorted(
        available, key=lambda q: hashlib.sha256(f"{day.isoformat()}:{q['id']}".encode()).hexdigest()
    )
    return ranked[0]


def make_daily(source: Path, exam: str, day: date, queue_dir: Path, config: Config) -> Draft:
    selected_exam = EXAMS[day.toordinal() % len(EXAMS)] if exam == "all" else exam
    short_name, questions = load_questions(source, selected_exam)
    used = {
        str(cast(Draft, draft.get("meta", {})).get("question_id"))
        for draft in list_drafts(queue_dir)
    }
    question = choose_question(questions, day, used)
    question_id = str(question["id"])
    choices = cast(list[str], question["choices"])
    letters = "ABCDE"
    choice_lines = [f"{letters[index]}. {choice}" for index, choice in enumerate(choices)]
    params = urlencode(
        {
            "utm_source": config.utm_source,
            "utm_medium": config.utm_medium,
            "utm_campaign": config.utm_campaign,
            "utm_content": question_id,
        }
    )
    app_url = config.apps[selected_exam].rstrip("/")
    separator = "&" if "?" in app_url else "?"
    url = f"{app_url}{separator}{params}"
    prefix = "PR\n" if config.sponsored else ""
    code = str(question.get("code", "")).strip()
    problem = f"【{short_name} 1日1問】\n{question['question']}"
    if question["type"] == "multi" and "つ選べ" not in problem:
        count = len(cast(list[int], question.get("answers", [])))
        problem += f"\n正しいものを{count}つ選べ。"
    if code:
        problem += f"\n{code}"
    sections = [
        prefix + problem,
        *(
            ["\n".join(choice_lines)]
            if weighted_length("\n".join(choice_lines)) <= LIMIT
            else choice_lines
        ),
        f"{config.answer_hint}\n{config.original_label}\n{config.app_label}: {url}\n{' '.join(config.hashtags[selected_exam])}",
    ]
    posts = pack_blocks(sections)
    correct = (
        cast(list[int], question["answers"])
        if question["type"] == "multi"
        else [cast(int, question["answer"])]
    )
    answer = "・".join(letters[index] for index in correct)
    notes = cast(list[str], question.get("choiceNotes", []))
    answer_blocks = [f"【解答】{answer}\n{question['explanation']}"]
    answer_blocks.extend(f"{letters[index]}: {note}" for index, note in enumerate(notes))
    label_length = weighted_length("\n" + config.ai_label)
    if label_length >= LIMIT:
        raise ValueError("AIラベルが長すぎます")
    last_block = answer_blocks.pop()
    if weighted_length(last_block) + label_length > LIMIT:
        last_parts = pack_blocks([last_block], LIMIT - label_length)
        answer_blocks.extend(last_parts[:-1])
        last_block = last_parts[-1]
    answer_blocks.append(last_block + "\n" + config.ai_label)
    answer_posts = pack_blocks(answer_blocks)
    diagram = (
        "┌ "
        + f"{short_name} 1日1問"
        + " ┐\n│ "
        + str(question["question"])
        + ("\n│ " + code if code else "")
        + "\n"
        + "\n".join("│ " + line for line in choice_lines)
        + "\n└ 正解は伏せる ┘"
    )
    meta: Draft = {
        "question_id": question_id,
        "exam": selected_exam,
        "topic": question["topic"],
        "source": "cert-study オリジナル問題",
        "generated_at": None,
        "diagram_text": diagram,
        "diagram_memo": "画像カードでは正解を載せず、文字の可読性と余白を確認する。"
        + config.ai_label,
    }
    draft = create_draft("cert", day.isoformat(), question_id, posts, meta, answer_posts)
    meta["generated_at"] = draft["created_at"]
    return draft

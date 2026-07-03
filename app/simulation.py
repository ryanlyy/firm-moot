import uuid
import json
from app.models import SimulationMode
from app.llm import chat_completion
from app.database import (
    get_case, get_session, save_session,
    get_case_records_text, get_past_context, save_analysis_history,
    save_generated_document,
)
from app.prompts import (
    opposing_counsel_prompt,
    judge_prompt,
    witness_prompt,
    analyst_prompt,
    question_predictor_prompt,
    document_generation_prompt,
)


async def _load_enrichment(case_id: int) -> tuple[str, str]:
    """Load case records text and past simulation/analysis context."""
    records_text = await get_case_records_text(case_id)
    past_context = await get_past_context(case_id)
    return records_text, past_context


async def run_simulation(
    case_id: int,
    mode: SimulationMode,
    user_message: str,
    session_id: str | None = None,
) -> dict:
    case = await get_case(case_id)
    if not case:
        raise ValueError(f"案件 {case_id} 不存在")

    if session_id:
        session = await get_session(session_id)
        history = session["messages"] if session else []
    else:
        session_id = str(uuid.uuid4())
        history = []

    records_text, past_context = await _load_enrichment(case_id)

    handler = _MODE_HANDLERS.get(mode)
    if not handler:
        raise ValueError(f"不支持的模拟模式: {mode}")

    result = await handler(case, user_message, history, records_text, past_context)

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": result["content"]})
    await save_session(session_id, case_id, mode.value, history)

    return {
        "session_id": session_id,
        "role": result["role"],
        "content": result["content"],
        "analysis": result.get("analysis"),
    }


async def _handle_adversarial(case: dict, user_message: str, history: list, records_text: str, past_context: str) -> dict:
    system = opposing_counsel_prompt(case, records_text, past_context)
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    content = await chat_completion(messages, temperature=0.8)
    return {"role": "opposing_counsel", "content": content}


async def _handle_full_trial(case: dict, user_message: str, history: list, records_text: str, past_context: str) -> dict:
    opp_role = "原告" if case["our_role"] == "defendant" else "被告"

    system = f"""你同时扮演两个角色来模拟一场完整的庭审：
1. 审判长 —— 负责主持庭审、归纳焦点、提出问题
2. {opp_role}代理律师 —— 负责反驳用户方的论点

请按以下格式输出：

【审判长】
（审判长的发言）

【{opp_role}代理律师】
（对方律师的发言）

---

{judge_prompt(case, records_text, past_context)}

---

{opposing_counsel_prompt(case, records_text, past_context)}
"""
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    content = await chat_completion(messages, temperature=0.7, max_tokens=6000)
    return {"role": "full_trial", "content": content}


async def _handle_witness_exam(case: dict, user_message: str, history: list, records_text: str, past_context: str) -> dict:
    system = witness_prompt(case, records_text, past_context)
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    content = await chat_completion(messages, temperature=0.9)
    return {"role": "witness", "content": content}


async def _handle_analysis(case: dict, user_message: str, history: list, records_text: str, past_context: str) -> dict:
    system = analyst_prompt(case, records_text, past_context)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]

    content = await chat_completion(messages, temperature=0.4, max_tokens=8000)
    return {"role": "analyst", "content": content}


async def run_analysis(case_id: int, focus: str) -> dict:
    case = await get_case(case_id)
    if not case:
        raise ValueError(f"案件 {case_id} 不存在")

    records_text, past_context = await _load_enrichment(case_id)

    focus_prompts = {
        "comprehensive": "请对本案进行全面深入的分析，涵盖所有分析维度。",
        "weakness": "请重点分析我方论证中的薄弱环节和潜在风险，以及对方可能利用的攻击点。",
        "strategy": "请为我方制定详细的庭审策略，包括开庭陈述要点、质证策略、辩论策略和结辩要点。",
        "questions": "请预测法官在庭审中可能提出的问题，并为每个问题准备回答策略。",
    }

    if past_context:
        extra = "\n\n请特别注意：结合此前的模拟和分析记录，对比发现新的改进点，避免重复已有建议，关注之前未覆盖的角度和薄弱环节。"
    else:
        extra = ""

    if focus == "questions":
        system = question_predictor_prompt(case, records_text, past_context)
    else:
        system = analyst_prompt(case, records_text, past_context)

    prompt = focus_prompts.get(focus, focus_prompts["comprehensive"]) + extra
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    content = await chat_completion(messages, temperature=0.3, max_tokens=8000)

    await save_analysis_history(case_id, focus, content)

    return {"analysis": content, "key_risks": [], "recommendations": []}


DOC_TYPE_TITLES = {
    "evidence_list": "证据清单",
    "legal_opinion": "代理词/辩护词",
    "cross_exam": "质证意见",
    "pretrial_checklist": "庭前准备清单",
    "debate_outline": "法庭辩论提纲",
    "closing_statement": "最后陈述/结辩词",
}


async def generate_document(case_id: int, doc_type: str) -> dict:
    case = await get_case(case_id)
    if not case:
        raise ValueError(f"案件 {case_id} 不存在")

    if doc_type not in DOC_TYPE_TITLES:
        raise ValueError(f"不支持的文书类型: {doc_type}")

    records_text, past_context = await _load_enrichment(case_id)
    system = document_generation_prompt(case, doc_type, records_text, past_context)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"请立即生成{DOC_TYPE_TITLES[doc_type]}。"},
    ]

    content = await chat_completion(messages, temperature=0.3, max_tokens=10000)

    doc_title = DOC_TYPE_TITLES[doc_type]
    saved = await save_generated_document(case_id, doc_type, doc_title, content)
    return saved


_MODE_HANDLERS = {
    SimulationMode.ADVERSARIAL: _handle_adversarial,
    SimulationMode.FULL_TRIAL: _handle_full_trial,
    SimulationMode.WITNESS_EXAM: _handle_witness_exam,
    SimulationMode.ARGUMENT_ANALYSIS: _handle_analysis,
}

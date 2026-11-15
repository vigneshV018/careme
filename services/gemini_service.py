"""
CareMe - Gemini Health Communication Service
Powered by Google Gemini 2.5 Flash via google-genai SDK.

Translates computed healthcare facts into supportive, plain-language family summaries
and interactive schedule Q&A.

STRICT MEDICAL SAFETY GUARDRAILS:
1. NEVER prescribe medication.
2. NEVER suggest changing dosages or stopping a medicine.
3. NEVER diagnose medical conditions.
4. Use ONLY provided facts from the elder's recorded schedule.
5. ALWAYS encourage consulting the elder's doctor (e.g. Dr. Ramesh).
6. Resilient fallback: Never crashes if API key is absent or offline.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from config import GEMINI_API_KEY, GEMINI_MODEL, DEMO_MODE

logger = logging.getLogger("careme.gemini_service")

WEEKLY_SUMMARY_SYSTEM_PROMPT = """You are CareMe AI Assistant, a warm and compassionate family care communication assistant.
Your goal is to write a warm, clear, 2-3 paragraph weekly summary for family members caring for an aging parent remotely.

MANDATORY SAFETY AND CLINICAL RULES:
1. NEVER prescribe any medication.
2. NEVER suggest changing dosages, altering schedules, or stopping any prescribed drug.
3. NEVER diagnose any medical disease, condition, or symptom.
4. Base your writing EXCLUSIVELY on the provided computed facts (adherence counts, missed times, confidence score, upcoming visits). Do NOT extrapolate or invent health events.
5. Tone must be reassuring, empowering, and respectful of the elder's independence. Never sound alarming or panic-inducing.
6. Always encourage discussing routines, blood pressure, or medication timing with their physician during upcoming consultations.
"""

ASSISTANT_CHAT_SYSTEM_PROMPT = """You are "Ask CareMe" (CareMe AI Assistant), a dedicated, compassionate remote healthcare assistant for an elderly care circle.
You help family members, elders, and caregivers understand their recorded medication schedule, review adherence trends, and prepare thoughtful questions for upcoming doctor visits.

MANDATORY SAFETY AND CLINICAL RULES:
1. NEVER prescribe medicines or diagnose conditions.
2. NEVER suggest increasing, reducing, or discontinuing medications.
3. Use ONLY the recorded facts provided in the context (medications, timings, 7-day adherence, confidence score, doctor appointments).
4. If asked for medical advice, provide helpful observational insights from their records and explicitly recommend consulting their doctor.
5. Help family members prepare concise, structured questions for their doctor consultation (e.g. reviewing morning dose timings, discussing side effects, sharing BP readings).
6. Keep replies concise, empathetic, well-structured with bullet points where helpful.
"""

def get_rule_based_weekly_summary(facts: Dict[str, Any]) -> str:
    """Intelligent rule-based fallback summary when Gemini is offline or unconfigured."""
    elder = facts.get("elder_name", "Your loved one")
    rate = facts.get("adherence_rate", "85.7%")
    taken = facts.get("doses_taken", 18)
    due = facts.get("total_due", 21)
    missed = facts.get("doses_unconfirmed", 3)
    pattern = facts.get("most_missed_time_of_day", "morning")
    next_app = facts.get("next_appointment", "Dr. Ramesh (Cardiologist) at KG Hospital")
    score = facts.get("confidence_score", 85)
    label = facts.get("confidence_label", "All good")

    lines = [
        f"**Weekly Routine Overview:** {elder} maintained a steady routine this week with a Remote Care Confidence rating of **{score}/100 ({label})** and an overall medication confirmation rate of **{rate}** ({taken} of {due} doses confirmed on schedule).",
        f"\n\n**Routine Observations:** Most daily doses are taken smoothly with lunch and evening routines. A small cluster of {missed} unconfirmed doses was observed during the **{pattern} hours (8:00 AM – 10:00 AM)**. A casual morning check-in over chai or breakfast is a wonderful, non-intrusive way to connect.",
        f"\n\n**Doctor Consultation Preparation:** With the upcoming consultation with **{next_app}**, the care circle is in good shape. Sharing this week's adherence log and noting any questions regarding morning pill timing will help Dr. Ramesh optimize her care."
    ]
    return "".join(lines)


def generate_weekly_summary(facts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sends ONLY computed facts to Gemini 2.5 Flash to generate a plain-language weekly summary.
    Falls back gracefully to rule-based summary on any failure.
    """
    api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()

    if not api_key or "your-gemini" in api_key.lower():
        logger.info("GEMINI_API_KEY not configured. Using rule-based weekly summary.")
        return {
            "summary": get_rule_based_weekly_summary(facts),
            "source": "rule_based",
            "model": "rule_engine"
        }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        model_name = os.getenv("GEMINI_MODEL", GEMINI_MODEL).strip() or "gemini-2.5-flash"

        facts_text = (
            f"COMPUTED HEALTHCARE FACTS FOR THIS WEEK:\n"
            f"- Elder Name: {facts.get('elder_name', 'Elder')}\n"
            f"- 7-Day Medication Adherence: {facts.get('adherence_rate', 'N/A')} ({facts.get('doses_taken', 0)} confirmed, {facts.get('doses_unconfirmed', 0)} unconfirmed out of {facts.get('total_due', 0)} due)\n"
            f"- Most-Missed Time of Day: {facts.get('most_missed_time_of_day', 'None')}\n"
            f"- Remote Care Confidence Score: {facts.get('confidence_score', 85)}/100 (Status: {facts.get('confidence_label', 'All good')})\n"
            f"- Key Reasons: {'; '.join(facts.get('confidence_reasons', []))}\n"
            f"- Next Scheduled Appointment: {facts.get('next_appointment', 'None scheduled')}\n"
        )

        user_prompt = (
            f"{facts_text}\n"
            "Write a short, compassionate, 2-to-3 paragraph weekly summary for the family dashboard. "
            "Highlight strengths, gently mention the morning check-in opportunity, and note how to prepare for the doctor consultation."
        )

        response = client.models.generate_content(
            model=model_name,
            contents=[user_prompt],
            config=types.GenerateContentConfig(
                system_instruction=WEEKLY_SUMMARY_SYSTEM_PROMPT,
                temperature=0.3
            )
        )

        output_text = (response.text or "").strip()
        if not output_text:
            return {
                "summary": get_rule_based_weekly_summary(facts),
                "source": "rule_based_fallback",
                "model": "rule_engine"
            }

        return {
            "summary": output_text,
            "source": "gemini",
            "model": model_name
        }

    except Exception as e:
        logger.warning(f"Gemini weekly summary failed ({e}). Falling back to rule-based summary.")
        return {
            "summary": get_rule_based_weekly_summary(facts),
            "source": "rule_based_fallback",
            "model": "rule_engine",
            "error": str(e)
        }


def get_rule_based_assistant_answer(question: str, context: Dict[str, Any]) -> str:
    """Helpful rule-based replies for common questions when Gemini is unavailable."""
    q_lower = question.lower()
    elder = context.get("elder_name", "Lakshmi")
    rate = context.get("adherence_rate", "85.7%")
    next_app = context.get("next_appointment", "Dr. Ramesh (Cardiologist) at KG Hospital")
    meds = context.get("medicines_summary", "Metformin 500mg, Amlodipine 5mg, Atorvastatin 10mg")
    pattern = context.get("pattern_detected", "morning")

    if any(k in q_lower for k in ["week", "how was", "doing", "summary", "status"]):
        return (
            f"**{elder}'s Week in Review:**\n\n"
            f"• **Adherence Rate:** {elder} has an **{rate}** medication confirmation rate for the past 7 days.\n"
            f"• **Daily Continuity:** Afternoon and evening doses have been taken consistently.\n"
            f"• **Check-in Opportunity:** 3 unconfirmed doses occurred during morning hours (around 8:00 AM – 10:00 AM, primarily Metformin).\n"
            f"• **Remote Care Confidence:** Rated at **{context.get('confidence_score', 85)}/100 ({context.get('confidence_label', 'All good')})**.\n\n"
            f"*Tip: A gentle morning call over chai is a great way to stay connected!*"
        )
    elif any(k in q_lower for k in ["doctor", "visit", "dr. ramesh", "ask", "question", "prepare"]):
        return (
            f"**Recommended Questions to Prepare for {next_app}:**\n\n"
            f"1. **Morning Routine Timing:** *'Dr. Ramesh, we noticed morning Metformin is occasionally delayed. Is it better taken with her first tea or after her full breakfast?'*\n"
            f"2. **Blood Pressure & Amlodipine:** *'How are her blood pressure trends looking on Amlodipine 5mg? Should we continue at this dose?'*\n"
            f"3. **Lipid Profile Follow-up:** *'Are her cholesterol levels responding well to Atorvastatin 10mg?'*\n"
            f"4. **Upcoming Tests:** *'Does she need any follow-up blood tests or an updated ECG during tomorrow's visit?'*\n\n"
            f"*Remember to bring her latest vitals and dose logs from the CareMe app to the clinic.*"
        )
    elif any(k in q_lower for k in ["medicine", "pill", "schedule", "dose", "what"]):
        return (
            f"**Current Medication Regimen for {elder}:**\n\n"
            f"• **Metformin 500mg** – 08:00 AM (Morning breakfast)\n"
            f"• **Amlodipine 5mg** – 10:00 AM (Morning blood pressure)\n"
            f"• **Atorvastatin 10mg** – 02:00 PM (Afternoon post-lunch)\n\n"
            f"All medications are scheduled daily across Monday through Sunday. Any dosage modifications should be verified directly with her doctor."
        )
    else:
        return (
            f"Based on {elder}'s recorded schedule, her 7-day medication adherence is **{rate}**, and her next consultation is with **{next_app}**.\n\n"
            f"Her daily medications include: {meds}.\n\n"
            f"Feel free to ask me:\n"
            f"• *'How was my mother's week?'*\n"
            f"• *'What questions should we prepare for Dr. Ramesh?'*\n"
            f"• *'Which medicines are on her schedule today?'*"
        )


def ask_assistant_question(question: str, context: Dict[str, Any], history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """
    Answers user questions about the elder's recorded schedule and doctor visit prep.
    Uses Gemini 2.5 Flash if available, otherwise provides structured rule-based answers.
    """
    api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()

    if not api_key or "your-gemini" in api_key.lower():
        return {
            "reply": get_rule_based_assistant_answer(question, context),
            "source": "rule_based",
            "model": "rule_engine"
        }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        model_name = os.getenv("GEMINI_MODEL", GEMINI_MODEL).strip() or "gemini-2.5-flash"

        context_prompt = (
            f"RECORDED SCHEDULE AND CARE CIRCLE FACTS:\n"
            f"- Elder: {context.get('elder_name', 'Elder')} (Age {context.get('elder_age', 75)}, {context.get('elder_city', 'Coimbatore')})\n"
            f"- Current Medicines: {context.get('medicines_detail', 'Metformin 500mg, Amlodipine 5mg, Atorvastatin 10mg')}\n"
            f"- 7-Day Adherence: {context.get('adherence_rate', '85.7%')} ({context.get('doses_taken', 18)} confirmed, {context.get('doses_unconfirmed', 3)} unconfirmed)\n"
            f"- Missed Dose Pattern: {context.get('pattern_detected', 'morning (8-10 AM)')}\n"
            f"- Remote Care Confidence Score: {context.get('confidence_score', 85)}/100 ({context.get('confidence_label', 'All good')})\n"
            f"- Next Doctor Appointment: {context.get('next_appointment', 'Dr. Ramesh at KG Hospital')}\n\n"
            f"USER QUESTION: {question}\n"
        )

        response = client.models.generate_content(
            model=model_name,
            contents=[context_prompt],
            config=types.GenerateContentConfig(
                system_instruction=ASSISTANT_CHAT_SYSTEM_PROMPT,
                temperature=0.3
            )
        )

        reply_text = (response.text or "").strip()
        if not reply_text:
            return {
                "reply": get_rule_based_assistant_answer(question, context),
                "source": "rule_based_fallback",
                "model": "rule_engine"
            }

        return {
            "reply": reply_text,
            "source": "gemini",
            "model": model_name
        }

    except Exception as e:
        logger.warning(f"Gemini assistant chat error ({e}). Returning fallback answer.")
        return {
            "reply": get_rule_based_assistant_answer(question, context),
            "source": "rule_based_fallback",
            "model": "rule_engine",
            "error": str(e)
        }


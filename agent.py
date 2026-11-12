"""
SSC GD Daily Paper Agent
Generates 80 bilingual MCQs (20 per section) and saves one Draft
document in Firestore collection: aiPaperDrafts.

Required GitHub Actions secrets:
  GEMINI_API_KEY
  FIREBASE_SERVICE_ACCOUNT_JSON

Optional GitHub Actions variables:
  GEMINI_MODEL (default: gemini-3.8-flash)
  EXPECTED_FIREBASE_PROJECT_ID (default: maharashtra-police-exam)
"""

import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types


IST = timezone(timedelta(hours=5, minutes=30))
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
EXPECTED_PROJECT_ID = os.getenv(
    "EXPECTED_FIREBASE_PROJECT_ID",
    "maharashtra-police-exam",
)
MAX_API_ATTEMPTS = 4

SECTIONS = [
    {
        "name": "Reasoning",
        "count": 20,
        "instruction": (
            "General Intelligence and Reasoning: analogy, classification, "
            "series, coding-decoding, directions, blood relations, "
            "non-verbal reasoning and basic logical reasoning."
        ),
    },
    {
        "name": "General Knowledge",
        "count": 20,
        "instruction": (
            "General Knowledge and General Awareness: Indian history, "
            "geography, polity, economy, science, sports and important "
            "general awareness. Avoid time-sensitive claims unless certain."
        ),
    },
    {
        "name": "Mathematics",
        "count": 20,
        "instruction": (
            "Elementary Mathematics: number system, simplification, "
            "percentage, ratio, average, profit and loss, interest, "
            "time and work, time and distance, mensuration."
        ),
    },
    {
        "name": "Hindi",
        "count": 20,
        "instruction": (
            "Hindi language and grammar: व्याकरण, संधि, समास, पर्यायवाची, "
            "विलोम, मुहावरे, लोकोक्तियाँ, वाक्य शुद्धि, शब्द ज्ञान "
            "and comprehension."
        ),
    },
]


def log(message):
    print(message, flush=True)


def initialize_services():
    log("Initializing services...")

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    firebase_json = os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT_JSON", ""
    ).strip()

    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY GitHub Secret is missing.")
    if not firebase_json:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON GitHub Secret is missing."
        )

    try:
        service_account = json.loads(firebase_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON."
        ) from exc

    actual_project_id = service_account.get("project_id")
    if not actual_project_id:
        raise RuntimeError(
            "Firebase service account JSON has no project_id."
        )

    if (
        EXPECTED_PROJECT_ID
        and actual_project_id != EXPECTED_PROJECT_ID
    ):
        raise RuntimeError(
            "Firebase project ID mismatch. Expected "
            f"{EXPECTED_PROJECT_ID}, got {actual_project_id}."
        )

    if not firebase_admin._apps:
        credential = credentials.Certificate(service_account)
        firebase_admin.initialize_app(
            credential,
            {"projectId": actual_project_id},
        )

    db = firestore.client()
    gemini = genai.Client(api_key=gemini_key)

    log(f"Firebase Project ID verified: {actual_project_id}")
    log(f"Gemini model selected: {MODEL_NAME}")
    log("Gemini and Firebase clients initialized.")

    return gemini, db


def extract_json_array(response_text):
    if not response_text:
        raise ValueError("Gemini returned an empty response.")

    text = response_text.strip()
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*```$", "", text)

    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("Gemini response did not contain a JSON array.")

    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("Gemini response is not a JSON array.")
    return parsed


def call_gemini_with_retry(gemini, prompt, section_name):
    last_error = None

    for attempt in range(1, MAX_API_ATTEMPTS + 1):
        try:
            log(
                f"Gemini request: {section_name} "
                f"(attempt {attempt}/{MAX_API_ATTEMPTS})"
            )
            response = gemini.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.25,
                    response_mime_type="application/json",
                ),
            )
            return extract_json_array(response.text or "")

        except Exception as exc:
            last_error = exc
            message = str(exc)
            log(
                f"Gemini request failed for {section_name}: "
                f"{type(exc).__name__}: {message[:500]}"
            )

            if attempt < MAX_API_ATTEMPTS:
                delay = min(15 * (2 ** (attempt - 1)), 90)
                log(f"Retrying in {delay} seconds...")
                time.sleep(delay)

    raise RuntimeError(
        f"Gemini failed for {section_name} after "
        f"{MAX_API_ATTEMPTS} attempts. Last error: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def build_prompt(section, required_count, attempt_note=""):
    return f"""
You are an experienced SSC GD Constable examination question setter.

Create exactly {required_count} ORIGINAL SSC GD-level MCQs.
Subject: {section['name']}
Syllabus focus: {section['instruction']}

Return ONLY a valid JSON array. No markdown, no comments, no text outside JSON.

Every array item must contain exactly these fields:
{{
  "text": "Question in English",
  "textHindi": "प्रश्न हिंदी में",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "correctOptionIndex": 0,
  "explanation": "Short explanation in English",
  "explanationHindi": "हिंदी में संक्षिप्त स्पष्टीकरण"
}}

Rules:
- Return exactly {required_count} objects, not more and not fewer.
- Four non-empty options per question.
- correctOptionIndex must be an integer: 0, 1, 2, or 3.
- Only one option must be correct.
- English and Hindi versions must ask the same question.
- Explanations must support the selected correct option.
- Questions must be unambiguous and appropriate for SSC GD.
- Mathematics calculations must be checked.
- Do not invent uncertain current-affairs facts.
- Avoid repeated questions and repeated options.
- In the Hindi section, questions may be primarily Hindi; still provide
  a clear English translation in "text".
{attempt_note}
"""


def validate_question(raw, section_name, index):
    if not isinstance(raw, dict):
        raise ValueError(
            f"{section_name} Q{index}: question must be a JSON object."
        )

    required = (
        "text",
        "textHindi",
        "options",
        "correctOptionIndex",
        "explanation",
        "explanationHindi",
    )
    for field in required:
        if field not in raw:
            raise ValueError(
                f"{section_name} Q{index}: missing field {field}."
            )

    text_fields = (
        "text",
        "textHindi",
        "explanation",
        "explanationHindi",
    )
    for field in text_fields:
        if not isinstance(raw[field], str) or not raw[field].strip():
            raise ValueError(
                f"{section_name} Q{index}: {field} must be non-empty text."
            )

    options = raw["options"]
    if (
        not isinstance(options, list)
        or len(options) != 4
        or not all(isinstance(x, str) and x.strip() for x in options)
    ):
        raise ValueError(
            f"{section_name} Q{index}: exactly four non-empty options required."
        )

    correct = raw["correctOptionIndex"]
    if (
        isinstance(correct, bool)
        or not isinstance(correct, int)
        or correct not in (0, 1, 2, 3)
    ):
        raise ValueError(
            f"{section_name} Q{index}: correctOptionIndex must be 0-3."
        )

    normalized_options = [option.strip() for option in options]
    if len({x.casefold() for x in normalized_options}) != 4:
        raise ValueError(
            f"{section_name} Q{index}: options must be distinct."
        )

    return {
        "id": (
            f"{section_name.lower().replace(' ', '_')}_"
            f"{index:02d}"
        ),
        "section": section_name,
        "language": "Bilingual",
        "questionType": "MCQ",
        "text": raw["text"].strip(),
        "textHindi": raw["textHindi"].strip(),
        "imageUrl": "",
        "options": normalized_options,
        "optionImageUrls": ["", "", "", ""],
        "correctOptionIndex": correct,
        "explanation": raw["explanation"].strip(),
        "explanationHindi": raw["explanationHindi"].strip(),
        "marks": 2,
        "negativeMarks": 0.25,
    }


def generate_section(gemini, section):
    section_name = section["name"]
    expected = section["count"]

    # If Gemini returns too few, ask once more for the missing count.
    # If it returns extra, keep the requested count after validation.
    raw_questions = call_gemini_with_retry(
        gemini,
        build_prompt(section, expected),
        section_name,
    )

    if len(raw_questions) < expected:
        missing = expected - len(raw_questions)
        log(
            f"{section_name}: received {len(raw_questions)}; "
            f"requesting {missing} additional questions."
        )
        supplement = call_gemini_with_retry(
            gemini,
            build_prompt(
                section,
                missing,
                "Generate only additional new questions. Do not repeat "
                "any question from the same section.",
            ),
            f"{section_name} supplement",
        )
        raw_questions.extend(supplement)

    if len(raw_questions) < expected:
        raise ValueError(
            f"{section_name}: expected {expected}, "
            f"received {len(raw_questions)}. Paper will not be saved."
        )

    if len(raw_questions) > expected:
        log(
            f"{section_name}: Gemini returned {len(raw_questions)}; "
            f"keeping the first {expected} after validation."
        )
        raw_questions = raw_questions[:expected]

    validated = [
        validate_question(item, section_name, index)
        for index, item in enumerate(raw_questions, start=1)
    ]

    log(f"VALIDATED: {section_name} {len(validated)}/{expected}")
    return validated


def check_duplicates(questions):
    seen = set()

    for question in questions:
        normalized = re.sub(
            r"\s+",
            " ",
            question["textHindi"].strip().casefold(),
        )
        digest = hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

        if digest in seen:
            raise ValueError(
                "Duplicate Hindi question detected. Draft not saved."
            )
        seen.add(digest)


def save_draft(db, questions):
    now = datetime.now(IST)
    date_key = now.strftime("%Y%m%d")
    paper_id = f"ssc_gd_daily_{date_key}"

    section_counts = {}
    for question in questions:
        section_counts[question["section"]] = (
            section_counts.get(question["section"], 0) + 1
        )

    paper = {
        "id": paper_id,
        "title": f"SSC GD Daily Practice Paper - {now.strftime('%d-%m-%Y')}",
        "examType": "SSC GD",
        "date": date_key,
        "status": "draft",
        "approvalStatus": "pending",
        "createdBy": "AI_DAILY_PAPER_AGENT",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "totalQuestions": len(questions),
        "totalMarks": 160,
        "duration": 60,
        "sections": section_counts,
        "questions": questions,
        "schemaVersion": 1,
        "generationModel": MODEL_NAME,
    }

    doc_ref = db.collection("aiPaperDrafts").document(paper_id)

    # Avoid overwriting an existing daily draft.
    try:
        doc_ref.create(paper)
    except Exception as exc:
        # Do not silently overwrite or duplicate an existing draft.
        raise RuntimeError(
            f"Could not create Firestore draft {paper_id}. "
            "It may already exist, or Firestore rejected the write. "
            f"Details: {type(exc).__name__}: {exc}"
        ) from exc

    log(f"FIRESTORE_DRAFT_SAVED: {paper_id}")
    log(f"TOTAL_QUESTIONS_SAVED: {len(questions)}")
    log("STATUS: draft")
    log("APPROVAL_STATUS: pending")
    return paper_id


def main():
    log("=" * 58)
    log("SSC GD DAILY PAPER AGENT")
    log("=" * 58)

    gemini, db = initialize_services()
    all_questions = []

    for section in SECTIONS:
        log(f"STARTING_SECTION: {section['name']}")
        section_questions = generate_section(gemini, section)
        all_questions.extend(section_questions)

    if len(all_questions) != 80:
        raise ValueError(
            f"Expected exactly 80 questions; got {len(all_questions)}."
        )

    expected_sections = {
        "Reasoning": 20,
        "General Knowledge": 20,
        "Mathematics": 20,
        "Hindi": 20,
    }
    actual_sections = {}
    for question in all_questions:
        name = question["section"]
        actual_sections[name] = actual_sections.get(name, 0) + 1

    if actual_sections != expected_sections:
        raise ValueError(
            f"Section count mismatch. Expected {expected_sections}; "
            f"got {actual_sections}."
        )

    check_duplicates(all_questions)
    random.shuffle(all_questions)

    paper_id = save_draft(db, all_questions)

    log("=" * 58)
    log("DAILY PAPER GENERATION SUCCESSFUL")
    log(f"PAPER_ID: {paper_id}")
    log("TOTAL_QUESTIONS: 80")
    log("ADMIN_APPROVAL_REQUIRED: YES")
    log("PUBLISHED: NO")
    log("=" * 58)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("=" * 58)
        log("DAILY PAPER GENERATION FAILED")
        log(f"ERROR_TYPE: {type(exc).__name__}")
        log(f"ERROR_DETAILS: {exc}")
        log("=" * 58)
        sys.exit(1)

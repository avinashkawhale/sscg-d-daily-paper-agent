
import os
import re
import json
import time
import hashlib
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

from google import genai
from google.genai import types

# =========================================================
# SSC GD DAILY AI PAPER AGENT
# 80 MCQs | Bilingual | Firebase Firestore Draft
# =========================================================

IST = timezone(timedelta(hours=5, minutes=30))

MODEL_NAME = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
)

EXPECTED_FIREBASE_PROJECT_ID = os.getenv(
    "EXPECTED_FIREBASE_PROJECT_ID",
    "maharashtra-police-exam"
)

QUESTION_MARKS = 2
NEGATIVE_MARKS = 0.25
EXAM_DURATION_MINUTES = 60

SECTIONS = [
    {
        "name": "Reasoning",
        "count": 20,
        "instruction": (
            "General Intelligence and Reasoning, "
            "analogies, series, coding-decoding, "
            "classification, spatial reasoning and logic"
        )
    },
    {
        "name": "General Knowledge",
        "count": 20,
        "instruction": (
            "Indian General Knowledge and General Awareness, "
            "Indian history, geography, polity, science, "
            "culture, economy and important current affairs"
        )
    },
    {
        "name": "Mathematics",
        "count": 20,
        "instruction": (
            "Elementary Mathematics, number system, "
            "percentage, ratio, average, profit and loss, "
            "time and work, time and distance, "
            "simple interest and mensuration"
        )
    },
    {
        "name": "Hindi",
        "count": 20,
        "instruction": (
            "Hindi language and grammar, vocabulary, "
            "synonyms, antonyms, idioms, spelling, "
            "sentence correction and comprehension"
        )
    }
]

# =========================================================
# 1. INITIALIZE SERVICES
# =========================================================

def initialize_services():

    print("Initializing services...")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    firebase_json = os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT_JSON"
    )

    if not gemini_key:
        raise RuntimeError(
            "GEMINI_API_KEY GitHub Secret is missing."
        )

    if not firebase_json:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON GitHub Secret is missing."
        )

    try:
        service_account = json.loads(firebase_json)
    except json.JSONDecodeError:
        raise RuntimeError(
            "Firebase Service Account JSON is invalid."
        )

    actual_project_id = service_account.get("project_id")

    if not actual_project_id:
        raise RuntimeError(
            "Firebase JSON does not contain project_id."
        )

    if actual_project_id != EXPECTED_FIREBASE_PROJECT_ID:
        raise RuntimeError(
            "Firebase Project ID mismatch. "
            f"Expected: {EXPECTED_FIREBASE_PROJECT_ID}; "
            f"Received: {actual_project_id}"
        )

    print("Firebase Project ID verified.")

    if not firebase_admin._apps:

        credential = credentials.Certificate(
            service_account
        )

        app = firebase_admin.initialize_app(
            credential
        )

    else:
        app = firebase_admin.get_app()

    db = firestore.client(app=app)

    gemini = genai.Client(
        api_key=gemini_key
    )

    print("Gemini client initialized.")
    print("Firebase client initialized.")

    return gemini, db

# =========================================================
# 2. JSON EXTRACTION
# =========================================================

def extract_json(response_text):

    if not response_text:
        raise ValueError(
            "Gemini returned an empty response."
        )

    text = response_text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    start = text.find("[")
    end = text.rfind("]")

    if start == -1 or end == -1:
        raise ValueError(
            "Gemini did not return a valid JSON array."
        )

    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON returned by Gemini: {error}"
        )

# =========================================================
# 3. GEMINI RETRY HANDLER
# =========================================================

def call_gemini_with_retry(gemini, prompt, section_name):

    max_attempts = 4

    for attempt in range(1, max_attempts + 1):

        try:

            print(
                f"Gemini request: {section_name} "
                f"(Attempt {attempt}/{max_attempts})"
            )

            response = gemini.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                    max_output_tokens=8192
                )
            )

            if not response.text:
                raise ValueError(
                    "Gemini returned an empty response."
                )

            return response

        except Exception as error:

            error_text = str(error).lower()

            temporary_error_terms = [
                "503",
                "429",
                "500",
                "502",
                "504",
                "unavailable",
                "resource_exhausted",
                "remoteprotocolerror",
                "server disconnected",
                "readtimeout",
                "connecterror",
                "timed out",
                "deadline exceeded",
                "internal server error"
            ]

            is_temporary = any(
                term in error_text
                for term in temporary_error_terms
            )

            if not is_temporary:
                raise

            if attempt == max_attempts:
                raise RuntimeError(
                    f"Gemini failed after {max_attempts} attempts. "
                    f"Last error: {type(error).__name__}"
                ) from error

            wait_seconds = 20 * (2 ** (attempt - 1))

            print(
                f"Temporary API error: "
                f"{type(error).__name__}"
            )

            print(
                f"Retrying after {wait_seconds} seconds..."
            )

            time.sleep(wait_seconds)

    raise RuntimeError(
        "Gemini request failed."
    )

# =========================================================
# 4. GENERATE SECTION PROMPT
# =========================================================

def create_prompt(section):

    section_name = section["name"]
    count = section["count"]

    return f"""
You are an expert SSC GD Constable examination question setter.

Generate EXACTLY {count} original MCQ questions.

SUBJECT:
{section_name}

TOPICS:
{section['instruction']}

STRICT REQUIREMENTS:

1. Follow SSC GD examination difficulty and syllabus.
2. Generate original and non-repeated questions.
3. Provide English question text.
4. Provide Hindi question text.
5. Provide exactly four answer options.
6. Provide exactly one correct answer.
7. correctOptionIndex must be 0, 1, 2 or 3.
8. Provide English explanation.
9. Provide Hindi explanation.
10. Mathematics answers must be mathematically correct.
11. Reasoning questions must have unambiguous answers.
12. GK facts must be reliable and accurate.
13. Do not invent current affairs, dates or statistics.
14. Hindi questions must test Hindi grammar and vocabulary.
15. Do not include markdown or any extra commentary.
16. Return only valid JSON.

OUTPUT FORMAT:

[
  {{
    "text": "Question in English",
    "textHindi": "प्रश्न हिंदी में",
    "options": [
      "Option A",
      "Option B",
      "Option C",
      "Option D"
    ],
    "correctOptionIndex": 0,
    "explanation": "English explanation",
    "explanationHindi": "हिंदी में स्पष्टीकरण"
  }}
]

IMPORTANT:
Return exactly {count} question objects.
"""

# =========================================================
# 5. VALIDATE QUESTIONS
# =========================================================

def generate_section(gemini, section):

    section_name = section["name"]
    expected_count = section["count"]

    prompt = create_prompt(section)

    response = call_gemini_with_retry(
        gemini,
        prompt,
        section_name
    )

    questions = extract_json(response.text)

    if not isinstance(questions, list):
        raise ValueError(
            f"{section_name}: Response is not a JSON array."
        )

    if len(questions) != expected_count:
        raise ValueError(
            f"{section_name}: Expected "
            f"{expected_count} questions, "
            f"received {len(questions)}."
        )

    validated_questions = []

    required_fields = [
        "text",
        "textHindi",
        "options",
        "correctOptionIndex",
        "explanation",
        "explanationHindi"
    ]

    for index, question in enumerate(questions):

        question_number = index + 1

        if not isinstance(question, dict):
            raise ValueError(
                f"{section_name} Q{question_number}: "
                "Invalid question object."
            )

        for field in required_fields:

            if field not in question:
                raise ValueError(
                    f"{section_name} Q{question_number}: "
                    f"Missing field {field}."
                )

        text_fields = [
            "text",
            "textHindi",
            "explanation",
            "explanationHindi"
        ]

        for field in text_fields:

            value = question[field]

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{section_name} Q{question_number}: "
                    f"Invalid {field}."
                )

        options = question["options"]

        if not isinstance(options, list):
            raise ValueError(
                f"{section_name} Q{question_number}: "
                "Options must be a list."
            )

        if len(options) != 4:
            raise ValueError(
                f"{section_name} Q{question_number}: "
                "Exactly four options are required."
            )

        if not all(
            isinstance(option, str) and option.strip()
            for option in options
        ):
            raise ValueError(
                f"{section_name} Q{question_number}: "
                "Invalid answer options."
            )

        correct_index = question["correctOptionIndex"]

        if (
            isinstance(correct_index, bool)
            or not isinstance(correct_index, int)
            or correct_index not in [0, 1, 2, 3]
        ):
            raise ValueError(
                f"{section_name} Q{question_number}: "
                "Invalid correctOptionIndex."
            )

        question_id = (
            f"{section_name.lower().replace(' ', '_')}_"
            f"{question_number:02d}"
        )

        validated_questions.append({

            "id": question_id,

            "examId": "",

            "section": section_name,

            "language": "Bilingual",

            "questionType": "MCQ",

            "text": question["text"].strip(),

            "textHindi": question["textHindi"].strip(),

            "imageUrl": "",

            "options": [
                option.strip()
                for option in options
            ],

            "optionImageUrls": ["", "", "", ""],

            "correctOptionIndex": correct_index,

            "explanation": question["explanation"].strip(),

            "explanationHindi": question[
                "explanationHindi"
            ].strip(),

            "marks": QUESTION_MARKS,

            "negativeMarks": NEGATIVE_MARKS

        })

    print(
        f"SUCCESS: {len(validated_questions)} "
        f"questions validated for {section_name}."
    )

    return validated_questions

# =========================================================
# 6. DUPLICATE CHECK
# =========================================================

def check_duplicates(questions):

    print("Checking duplicate questions...")

    seen = set()

    for question in questions:

        text_values = [
            question["text"].strip().lower(),
            question["textHindi"].strip().lower()
        ]

        for text in text_values:

            normalized = re.sub(
                r"\s+",
                " ",
                text
            )

            text_hash = hashlib.sha256(
                normalized.encode("utf-8")
            ).hexdigest()

            if text_hash in seen:
                raise ValueError(
                    "Duplicate question detected. "
                    "Paper will not be saved."
                )

            seen.add(text_hash)

    print("Duplicate check passed.")

# =========================================================
# 7. SAVE DRAFT TO FIRESTORE
# =========================================================

def save_draft(db, questions):

    print("Preparing Firestore Draft...")

    if len(questions) != 80:
        raise ValueError(
            "Only exactly 80 questions can be saved."
        )

    today = datetime.now(IST).strftime("%Y%m%d")

    paper_id = f"ssc_gd_daily_{today}"

    paper_ref = (
        db.collection("aiPaperDrafts")
        .document(paper_id)
    )

    metadata = {

        "id": paper_id,

        "title": f"SSC GD Daily Practice Paper - {today}",

        "examType": "SSC GD",

        "date": today,

        "status": "draft",

        "approvalStatus": "pending",

        "createdBy": "AI_DAILY_PAPER_AGENT",

        "createdAt": firestore.SERVER_TIMESTAMP,

        "totalQuestions": 80,

        "totalMarks": 160,

        "duration": EXAM_DURATION_MINUTES,

        "sections": {
            "Reasoning": 20,
            "General Knowledge": 20,
            "Mathematics": 20,
            "Hindi": 20
        },

        "marksPerQuestion": QUESTION_MARKS,

        "negativeMarks": NEGATIVE_MARKS

    }

    # 81 writes total: 1 metadata + 80 questions.
    # All writes are committed atomically.

    batch = db.batch()

    # Create prevents overwriting an existing daily paper.
    batch.create(
        paper_ref,
        metadata
    )

    for question in questions:

        question["examId"] = paper_id

        question_ref = (
            paper_ref
            .collection("questions")
            .document(question["id"])
        )

        batch.set(
            question_ref,
            question
        )

    batch.commit()

    print(
        f"SUCCESS: Draft saved: {paper_id}"
    )

    print(
        "Total questions saved: 80"
    )

    print(
        "Status: draft"
    )

    print(
        "Approval: pending"
    )

# =========================================================
# 8. MAIN
# =========================================================

def main():

    print("=" * 55)
    print("SSC GD DAILY AI PAPER AGENT")
    print("=" * 55)

    print(
        f"Using Gemini Model: {MODEL_NAME}"
    )

    gemini, db = initialize_services()

    all_questions = []

    # Generate all four sections.

    for section in SECTIONS:

        print("")
        print(
            f"Starting Section: {section['name']}"
        )

        section_questions = generate_section(
            gemini,
            section
        )

        all_questions.extend(
            section_questions
        )

    # Verify total count.

    if len(all_questions) != 80:

        raise ValueError(
            f"Expected 80 questions, "
            f"received {len(all_questions)}."
        )

    print("")
    print("All 80 questions generated.")

    # Check duplicates.

    check_duplicates(all_questions)

    # Save only after all validation passes.

    save_draft(
        db,
        all_questions
    )

    print("")
    print("=" * 55)
    print("DAILY PAPER GENERATION SUCCESSFUL")
    print("Total Questions: 80")
    print("Firestore Status: DRAFT")
    print("Admin Approval: REQUIRED")
    print("=" * 55)

# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("")
        print("DAILY PAPER GENERATION FAILED")
        print(
            f"Error Type: {type(error).__name__}"
        )
        print(
            f"Error Details: {error}"
        )

        raise

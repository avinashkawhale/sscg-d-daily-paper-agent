
import os
import json
import re
import hashlib
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types


# =====================================================
# SSC GD DAILY PAPER AGENT
# Generates 80 bilingual MCQs and saves as Firestore Draft
# =====================================================

IST = timezone(timedelta(hours=5, minutes=30))

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SECTIONS = [
    {
        "name": "Reasoning",
        "count": 20,
        "instruction": "General Intelligence and Reasoning"
    },
    {
        "name": "General Knowledge",
        "count": 20,
        "instruction": "General Knowledge and General Awareness"
    },
    {
        "name": "Mathematics",
        "count": 20,
        "instruction": "Elementary Mathematics"
    },
    {
        "name": "Hindi",
        "count": 20,
        "instruction": "Hindi language and grammar"
    }
]


def initialize_services():
    """Initialize Gemini and Firebase Admin SDK."""

    gemini_key = os.environ.get("GEMINI_API_KEY")
    firebase_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY secret is missing.")

    if not firebase_json:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON secret is missing."
        )

    gemini = genai.Client(api_key=gemini_key)

    service_account = json.loads(firebase_json)

    if not firebase_admin._apps:
        credential = credentials.Certificate(service_account)
        firebase_admin.initialize_app(credential)

    db = firestore.client()

    return gemini, db


def extract_json(text):
    """Extract JSON safely from Gemini response."""

    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(r"\s*```$", "", text)

    start = text.find("[")
    end = text.rfind("]")

    if start == -1 or end == -1:
        raise ValueError("Gemini did not return a valid JSON array.")

    return json.loads(text[start:end + 1])


def generate_section(gemini, section):
    """Generate and validate exactly 20 MCQs."""

    section_name = section["name"]
    count = section["count"]

    prompt = f"""
You are an expert SSC GD Constable examination question setter.

Generate EXACTLY {count} original multiple-choice questions.

SUBJECT: {section_name}
TOPIC: {section['instruction']}

REQUIREMENTS:

1. Questions must follow SSC GD examination level and syllabus.
2. All questions must be factually correct.
3. Questions must be original, not repeated.
4. Provide both English and Hindi question text.
5. Provide exactly four answer options.
6. Provide exactly one correct answer.
7. correctOptionIndex must be 0, 1, 2 or 3.
8. Provide explanations in English and Hindi.
9. Mathematics questions must have correct calculations.
10. Reasoning questions must have unambiguous answers.
11. Hindi section questions must test Hindi grammar,
    vocabulary, comprehension or language knowledge.
12. Avoid fabricated facts and ambiguous questions.
13. Do not include markdown or commentary.

Return ONLY a valid JSON array.

Each object must follow this structure:

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
  "explanation": "Explanation in English",
  "explanationHindi": "हिंदी में स्पष्टीकरण"
}}

IMPORTANT:
Return exactly {count} question objects.
"""

    response = gemini.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json"
        )
    )

    if not response.text:
        raise ValueError(
            f"Empty Gemini response for {section_name}"
        )

    questions = extract_json(response.text)

    if not isinstance(questions, list):
        raise ValueError("Response is not a JSON list.")

    if len(questions) != count:
        raise ValueError(
            f"{section_name}: Expected {count}, "
            f"received {len(questions)}."
        )

    validated = []

    for index, q in enumerate(questions):

        required_fields = [
            "text",
            "textHindi",
            "options",
            "correctOptionIndex",
            "explanation",
            "explanationHindi"
        ]

        for field in required_fields:
            if field not in q:
                raise ValueError(
                    f"{section_name} Q{index + 1}: Missing {field}"
                )

        if not all(
            isinstance(q[field], str) and q[field].strip()
            for field in [
                "text",
                "textHindi",
                "explanation",
                "explanationHindi"
            ]
        ):
            raise ValueError(
                f"{section_name} Q{index + 1}: Empty text field."
            )

        options = q["options"]

        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(
                f"{section_name} Q{index + 1}: "
                "Exactly four options required."
            )

        if not all(
            isinstance(option, str) and option.strip()
            for option in options
        ):
            raise ValueError(
                f"{section_name} Q{index + 1}: Invalid option."
            )

        correct_index = q["correctOptionIndex"]

        if (
            isinstance(correct_index, bool)
            or not isinstance(correct_index, int)
            or correct_index not in [0, 1, 2, 3]
        ):
            raise ValueError(
                f"{section_name} Q{index + 1}: Invalid answer index."
            )

        validated.append({
            "id": f"{section_name.lower().replace(' ', '_')}_{index + 1:02d}",
            "section": section_name,
            "language": "Bilingual",
            "questionType": "MCQ",
            "text": q["text"].strip(),
            "textHindi": q["textHindi"].strip(),
            "imageUrl": "",
            "options": [option.strip() for option in options],
            "optionImageUrls": ["", "", "", ""],
            "correctOptionIndex": correct_index,
            "explanation": q["explanation"].strip(),
            "explanationHindi": q["explanationHindi"].strip(),
            "marks": 2,
            "negativeMarks": 0.25
        })

    print(f"Validated {len(validated)} questions: {section_name}")

    return validated


def check_duplicates(questions):
    """Reject duplicate question text within the paper."""

    seen = set()

    for question in questions:

        text = question["textHindi"].strip().lower()
        text_hash = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

        if text_hash in seen:
            raise ValueError(
                "Duplicate question detected. Draft not saved."
            )

        seen.add(text_hash)


def save_draft(db, questions):
    """Save the completed paper in a separate Draft collection."""

    today = datetime.now(IST).strftime("%Y%m%d")

    paper_id = f"ssc_gd_daily_{today}"

    paper = {
        "id": paper_id,
        "title": f"SSC GD Daily Practice Paper - {today}",
        "examType": "SSC GD",
        "date": today,
        "status": "draft",
        "approvalStatus": "pending",
        "createdBy": "AI_DAILY_PAPER_AGENT",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "totalQuestions": len(questions),
        "totalMarks": 160,
        "duration": 60,
        "sections": {
            "Reasoning": 20,
            "General Knowledge": 20,
            "Mathematics": 20,
            "Hindi": 20
        },
        "questions": questions
    }

    document = db.collection("aiPaperDrafts").document(paper_id)

    # create() prevents accidental overwriting of an existing draft.
    document.create(paper)

    print(f"Draft saved successfully: {paper_id}")


def main():

    print("Starting SSC GD Daily Paper Agent...")

    gemini, db = initialize_services()

    all_questions = []

    for section in SECTIONS:

        print(f"Generating: {section['name']}")

        questions = generate_section(gemini, section)

        all_questions.extend(questions)

    if len(all_questions) != 80:
        raise ValueError(
            f"Expected 80 questions, got {len(all_questions)}"
        )

    check_duplicates(all_questions)

    save_draft(db, all_questions)

    print("SUCCESS: 80-question Draft created.")
    print("Admin approval is required before publication.")


if __name__ == "__main__":
    main()

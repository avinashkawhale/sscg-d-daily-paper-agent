
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
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON GitHub Secret is missing.")




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

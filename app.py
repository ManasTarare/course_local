from __future__ import annotations

import copy
import json
import os
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, url_for
from google import genai
from pydantic import BaseModel


load_dotenv()

app = Flask(__name__, static_folder="styles", static_url_path="/styles")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

TEXT_FIELDS = {
    "title", "description", "body", "content", "text", "question", "answer",
    "options", "caption", "alt_text", "transcript", "example", "feedback", "hint",
}


class GlossarySuggestion(BaseModel):
    source_term: str
    target_term: str


class CulturalAdaptation(BaseModel):
    segment_index: int
    adapted_text: str
    reason: str


class CourseAnalysis(BaseModel):
    glossary_suggestions: list[GlossarySuggestion]
    cultural_adaptations: list[CulturalAdaptation]


def context_for(profile: dict[str, str]) -> str:
    notes = profile.get("notes", "").strip()
    return (
        f"Target locale: {profile.get('locale') or profile['target_language']}. "
        f"Audience: {profile.get('audience') or 'General audience'}. "
        f"Tone: {profile.get('tone') or 'Clear and natural'}. "
        f"Adaptation notes: {notes}"
    )


def collect_text(node: Any, path: list[Any] | None = None, result: list[tuple[list[Any], str]] | None = None):
    path = path or []
    result = result if result is not None else []
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = path + [key]
            if key in TEXT_FIELDS:
                if isinstance(value, str) and value.strip():
                    result.append((child_path, value))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, str) and item.strip():
                            result.append((child_path + [index], item))
                        else:
                            collect_text(item, child_path + [index], result)
            else:
                collect_text(value, child_path, result)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            collect_text(value, path + [index], result)
    return result


def set_path(node: Any, path: list[Any], text: str) -> None:
    current = node
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = text


def deepl_translate(texts: list[str], profile: dict[str, str]) -> list[str]:
    key = os.getenv("DEEPL_AUTH_KEY", "").strip()
    if not key or key == "put_your_deepl_api_key_here":
        raise ValueError("DeepL key is not configured. Add DEEPL_AUTH_KEY to your .env file, or use Preview course.")

    base_url = os.getenv("DEEPL_API_BASE_URL", "https://api-free.deepl.com").rstrip("/")
    payload: dict[str, Any] = {
        "text": texts,
        "source_lang": profile.get("source_language") or "EN",
        "target_lang": profile["target_language"],
        "context": context_for(profile),
    }
    glossary_id = profile.get("glossary_id", "").strip()
    if glossary_id:
        payload["glossary_id"] = glossary_id

    response = requests.post(
        f"{base_url}/v2/translate",
        headers={"Authorization": f"DeepL-Auth-Key {key}"},
        json=payload,
        timeout=60,
    )
    if not response.ok:
        raise ValueError(f"DeepL returned {response.status_code}: {response.text[:400]}")
    translations = response.json().get("translations", [])
    if len(translations) != len(texts):
        raise ValueError("DeepL returned an unexpected number of translated fields.")
    return [item["text"] for item in translations]


def create_deepl_glossary(name: str, source_language: str, target_language: str, raw_terms: str) -> tuple[str, int, bool]:
    key = os.getenv("DEEPL_AUTH_KEY", "").strip()
    if not key or key == "put_your_deepl_api_key_here":
        raise ValueError("DeepL key is not configured. Add DEEPL_AUTH_KEY to your .env file first.")

    terms: list[tuple[str, str]] = []
    seen_sources: set[str] = set()
    for line_number, raw_line in enumerate(raw_terms.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            source, target = line.split("\t", 1)
        elif "=>" in line:
            source, target = line.split("=>", 1)
        else:
            raise ValueError(f"Term line {line_number} must use Source => Target (or a tab between terms).")
        source, target = source.strip(), target.strip()
        if not source or not target:
            raise ValueError(f"Term line {line_number} has an empty source or target.")
        normalized = source.casefold()
        if normalized in seen_sources:
            raise ValueError(f"Duplicate source term on line {line_number}: {source}")
        seen_sources.add(normalized)
        terms.append((source, target))
    if not terms:
        raise ValueError("Enter at least one source/target term pair.")

    base_url = os.getenv("DEEPL_API_BASE_URL", "https://api-free.deepl.com").rstrip("/")
    response = requests.post(
        f"{base_url}/v2/glossaries",
        headers={"Authorization": f"DeepL-Auth-Key {key}"},
        json={
            "name": name.strip() or "Course glossary",
            "source_lang": source_language.strip().lower(),
            "target_lang": target_language.strip().lower(),
            "entries": "\n".join(f"{source}\t{target}" for source, target in terms),
            "entries_format": "tsv",
        },
        timeout=60,
    )
    if not response.ok:
        raise ValueError(f"DeepL glossary request failed ({response.status_code}): {response.text[:400]}")
    data = response.json()
    return data["glossary_id"], len(terms), bool(data.get("ready", True))


def analyze_course_with_ai(entries: list[tuple[list[Any], str]], profile: dict[str, str]) -> CourseAnalysis:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("AI adaptation needs GEMINI_API_KEY in .env. DeepL translation still works with the regular button.")
    if sum(len(text) for _, text in entries) > 100_000:
        raise ValueError("This first AI pass supports up to 100,000 characters of learner-facing text. Split a larger course into modules.")

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    segments = [
        {"segment_index": index, "json_path": path, "source_text": source}
        for index, (path, source) in enumerate(entries)
    ]
    prompt = {
        "target_language": profile.get("target_language", "ES"),
        "target_locale": profile.get("locale") or profile.get("target_language", "ES"),
        "audience": profile.get("audience", "General audience"),
        "tone": profile.get("tone", "Clear and natural"),
        "additional_instructions": profile.get("notes", ""),
        "segments": segments,
    }
    prompt_text = (
        "You are a course localization editor. Analyze the supplied course text for the stated target audience. "
        "Suggest a compact glossary only for recurring, specialized, branded, or course-specific terms where consistency matters. "
        "Do not add generic dictionary words. For idioms, sayings, jokes, and culture-bound examples, return a complete adapted translation "
        "for that segment using a familiar target-locale equivalent when one is appropriate, preserving the lesson's intended meaning. "
        "If no safe equivalent exists, use a clear meaning-based translation rather than inventing a local fact. "
        "Only include a cultural_adaptation when a literal translation would sound unnatural or lose the intended meaning. "
        "The segment_index must refer to the supplied segment. Keep source_term values exactly as they appear in the source text. "
        "Return only the requested structured result.\n\nCOURSE PROFILE AND TEXT:\n"
        + json.dumps(prompt, ensure_ascii=False)
    )
    try:
        response = client.interactions.create(
            model=model,
            input=prompt_text,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": CourseAnalysis.model_json_schema(),
            },
        )
        analysis = CourseAnalysis.model_validate_json(response.output_text)
    except Exception as exc:
        raise ValueError(f"Gemini course analysis failed: {exc}") from exc
    valid_indexes = set(range(len(entries)))
    analysis.cultural_adaptations = [
        adaptation for adaptation in analysis.cultural_adaptations
        if adaptation.segment_index in valid_indexes and adaptation.adapted_text.strip()
    ]
    return analysis


def localize_with_ai(course: Any, profile: dict[str, str]) -> tuple[Any, int, list[dict[str, str]], list[dict[str, str]], str]:
    entries = collect_text(course)
    if not entries:
        raise ValueError("No learner-facing text found. Add relevant keys to TEXT_FIELDS in app.py.")
    analysis = analyze_course_with_ai(entries, profile)

    term_pairs: list[tuple[str, str]] = []
    seen_terms: set[str] = set()
    for suggestion in analysis.glossary_suggestions:
        source, target = suggestion.source_term.strip(), suggestion.target_term.strip()
        if (
            source
            and target
            and source.casefold() not in seen_terms
            and any(source.casefold() in text.casefold() for _, text in entries)
        ):
            seen_terms.add(source.casefold())
            term_pairs.append((source, target))

    auto_glossary_id = ""
    glossary_ready = True
    if term_pairs:
        term_data = "\n".join(f"{source}\t{target}" for source, target in term_pairs)
        title = "Course glossary " + (profile.get("locale") or profile.get("target_language", "target"))
        auto_glossary_id, _, glossary_ready = create_deepl_glossary(
            title[:200],
            profile.get("source_language") or "EN",
            profile.get("target_language") or "ES",
            term_data,
        )
        if not glossary_ready:
            raise ValueError("DeepL created the AI glossary but it is not ready yet. Wait briefly, then retry AI adapt & translate.")

    translate_profile = profile
    if term_pairs:
        translate_profile = {**profile, "glossary_id": auto_glossary_id}
    localized, translated_count = localize(course, translate_profile)

    adaptation_rows: list[dict[str, str]] = []
    for adaptation in analysis.cultural_adaptations:
        path, source = entries[adaptation.segment_index]
        set_path(localized, path, adaptation.adapted_text)
        adaptation_rows.append({"source": source, "result": adaptation.adapted_text, "reason": adaptation.reason})

    term_rows = [{"source": source, "target": target} for source, target in term_pairs]
    return localized, translated_count, term_rows, adaptation_rows, auto_glossary_id


def localize(course: Any, profile: dict[str, str]) -> tuple[Any, int]:
    localized = copy.deepcopy(course)
    entries = collect_text(localized)
    if not entries:
        raise ValueError("No learner-facing text found. Add relevant keys to TEXT_FIELDS in app.py.")

    # Keep requests below DeepL's request-size limit while preserving path/result alignment.
    index = 0
    while index < len(entries):
        batch: list[tuple[list[Any], str]] = []
        size = 0
        while index < len(entries) and len(batch) < 40:
            entry = entries[index]
            entry_size = len(entry[1].encode("utf-8"))
            if batch and size + entry_size > 90_000:
                break
            batch.append(entry)
            size += entry_size
            index += 1
        translated = deepl_translate([text for _, text in batch], profile)
        for (path, _), text in zip(batch, translated):
            set_path(localized, path, text)
    return localized, len(entries)


@app.route("/", methods=["GET", "POST"])
def home():
    result = None
    error = None
    notice = None
    count = 0
    ai_details = None
    profile = {
        "source_language": "EN",
        "target_language": "ES",
        "locale": "es-MX",
        "audience": "Adult beginners in Mexico",
        "tone": "Friendly, clear, and respectful",
        "notes": "Keep product names unchanged. Adapt examples only when the source gives enough information.",
        "glossary_id": request.args.get("glossary_id", ""),
    }
    glossary_note = request.args.get("glossary_note", "")
    glossary_error = request.args.get("glossary_error", "")

    if request.method == "POST":
        for name in profile:
            profile[name] = request.form.get(name, profile[name]).strip()
        upload = request.files.get("course_file")
        if not upload or not upload.filename:
            error = "Choose a course JSON file first."
        else:
            try:
                course = json.loads(upload.read().decode("utf-8-sig"))
                if not isinstance(course, (dict, list)):
                    raise ValueError("The JSON root must be an object or an array.")
                action = request.form.get("action")
                if action == "ai_translate":
                    if not profile["target_language"]:
                        raise ValueError("Enter a target language code, such as ES or DE.")
                    result, count, terms, adaptations, generated_id = localize_with_ai(course, profile)
                    if generated_id:
                        profile["glossary_id"] = generated_id
                    ai_details = {"terms": terms, "adaptations": adaptations}
                    notice = (
                        f"AI reviewed {count} text fields, generated {len(terms)} glossary terms, "
                        f"and applied {len(adaptations)} cultural or idiom adaptations before displaying the course."
                    )
                elif action == "translate":
                    if not profile["target_language"]:
                        raise ValueError("Enter a target language code, such as ES or DE.")
                    result, count = localize(course, profile)
                    notice = f"Translated {count} text fields. Review the course before publishing."
                else:
                    result = course
                    notice = "Course preview. The uploaded source has not been translated."
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                error = f"Could not read this file as UTF-8 JSON: {exc}"
            except (ValueError, requests.RequestException, KeyError) as exc:
                error = str(exc)

    return render_template(
        "index.html", result=result, error=error, notice=notice, count=count, profile=profile,
        glossary_note=glossary_note, glossary_error=glossary_error, ai_details=ai_details,
    )


@app.route("/glossary", methods=["POST"])
def make_glossary():
    name = request.form.get("glossary_name", "Course glossary").strip()
    source_language = request.form.get("glossary_source_language", "EN").strip()
    target_language = request.form.get("glossary_target_language", "ES").strip()
    raw_terms = request.form.get("glossary_terms", "")
    try:
        glossary_id, term_count, ready = create_deepl_glossary(name, source_language, target_language, raw_terms)
        note = f"Created glossary with {term_count} term pairs. Glossary ID copied into the localization profile."
        if not ready:
            note += " DeepL is still preparing it; wait briefly before translating."
        return redirect(url_for("home", glossary_id=glossary_id, glossary_note=note))
    except (ValueError, requests.RequestException, KeyError) as exc:
        return redirect(url_for("home", glossary_error=str(exc)))


@app.errorhandler(413)
def file_too_large(_error):
    return render_template(
        "index.html",
        result=None,
        error="File is larger than the 10 MB local upload limit.",
        notice=None,
        count=0,
        profile={},
        glossary_note="",
        glossary_error="",
        ai_details=None,
    ), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

"""Translate learner-facing strings in a course JSON file using DeepL."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


TEXT_FIELDS = {
    "title",
    "description",
    "body",
    "content",
    "text",
    "question",
    "answer",
    "options",
    "caption",
    "alt_text",
    "transcript",
    "example",
    "feedback",
    "hint",
}


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def build_context(profile: dict[str, Any]) -> str:
    parts = [
        f"Target locale: {profile.get('target_locale', profile['target_language'])}.",
        f"Audience: {profile.get('audience', 'General audience')}.",
        f"Tone: {profile.get('tone', 'Clear and natural')}.",
    ]
    notes = profile.get("adaptation_notes", [])
    if notes:
        parts.append("Adaptation notes: " + " ".join(str(note) for note in notes))
    return " ".join(parts)


def collect_strings(node: Any, fields: set[str], found: list[tuple[list[Any], str]], path: list[Any] | None = None) -> None:
    path = path or []
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = path + [key]
            if key in fields:
                if isinstance(value, str) and value.strip():
                    found.append((child_path, value))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, str) and item.strip():
                            found.append((child_path + [index], item))
                        else:
                            collect_strings(item, fields, found, child_path + [index])
            else:
                collect_strings(value, fields, found, child_path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            collect_strings(value, fields, found, path + [index])


def set_at_path(node: Any, path: list[Any], value: str) -> None:
    current = node
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value


def translate_texts(texts: list[str], profile: dict[str, Any], auth_key: str, base_url: str) -> list[str]:
    payload: dict[str, Any] = {
        "text": texts,
        "target_lang": profile["target_language"],
        "source_lang": profile.get("source_language", "EN"),
        "context": build_context(profile),
    }
    glossary_id = profile.get("glossary_id", "").strip()
    if glossary_id:
        payload["glossary_id"] = glossary_id

    response = requests.post(
        f"{base_url.rstrip('/')}/v2/translate",
        headers={"Authorization": f"DeepL-Auth-Key {auth_key}"},
        json=payload,
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"DeepL request failed ({response.status_code}): {response.text[:500]}")
    translations = response.json().get("translations", [])
    if len(translations) != len(texts):
        raise RuntimeError("DeepL returned a different number of translations than requested.")
    return [item["text"] for item in translations]


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate learner-facing text in a course JSON file.")
    parser.add_argument("--input", required=True, type=Path, help="Source course JSON")
    parser.add_argument("--profile", required=True, type=Path, help="Localization profile JSON")
    parser.add_argument("--output", required=True, type=Path, help="Destination localized JSON")
    args = parser.parse_args()

    load_dotenv()
    auth_key = os.getenv("DEEPL_AUTH_KEY", "").strip()
    base_url = os.getenv("DEEPL_API_BASE_URL", "https://api-free.deepl.com").strip()
    if not auth_key or auth_key == "put_your_deepl_api_key_here":
        print("Set DEEPL_AUTH_KEY in .env before running localization.", file=sys.stderr)
        return 2

    try:
        course = read_json(args.input)
        profile = read_json(args.profile)
        if not profile.get("target_language"):
            raise ValueError("The profile must include target_language, for example ES.")
        entries: list[tuple[list[Any], str]] = []
        collect_strings(course, TEXT_FIELDS, entries)
        if not entries:
            raise ValueError("No translatable strings found. Check TEXT_FIELDS in localize_course.py.")

        # DeepL limits request size. Send small batches and keep each result aligned with its JSON path.
        for start in range(0, len(entries), 40):
            batch = entries[start : start + 40]
            translated = translate_texts([text for _, text in batch], profile, auth_key, base_url)
            for (json_path, _), translated_text in zip(batch, translated):
                set_at_path(course, json_path, translated_text)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(course, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Localized {len(entries)} text fields to {args.output}")
        print("Review examples, images, units, links, and assessments with someone familiar with the target audience.")
        return 0
    except (ValueError, RuntimeError, requests.RequestException, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

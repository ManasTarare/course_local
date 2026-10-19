# Course Localizer Web UI

A local Flask app for uploading course JSON, previewing it as HTML, and localizing it with Gemini and DeepL. The AI workflow suggests glossary terms, adapts idioms for the target audience, creates a DeepL glossary, and translates the course in one action.

## Run on Windows

Open PowerShell in this folder, then run:

```powershell
py -m venv env
.\env\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Replace `put_your_deepl_api_key_here` in `.env` with your DeepL API key and `put_your_gemini_api_key_here` with a Gemini API key, then save. The app uses Gemini for AI analysis/adaptation and DeepL for translation and glossary creation.

Set `GEMINI_MODEL` to a model available to your API account if the default is unavailable. **Preview course** is local and needs no API keys. **AI adapt + translate** requires both Gemini and DeepL keys.

```powershell
.\env\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000 in your browser. Upload a JSON course and choose **Preview course** to view it locally, or **AI adapt + translate** to generate a glossary, adapt idioms, translate with DeepL, and view the localized course. The app supports uploads up to 10 MB.

## AI adaptation flow

Choose **AI adapt + translate** to send the learner-facing text and audience profile to Gemini. It returns structured glossary suggestions and target-locale rewrites for idioms or culture-bound passages. The app creates a DeepL glossary from relevant suggested terms, translates the course through DeepL using that glossary, and applies the AI rewrites to the identified passages. The result page lists the suggested terms and each special adaptation so you can review what changed. Gemini structured output keeps the analysis in the fields the app expects. See [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

The AI button needs both a Gemini API key and a DeepL API key. Each provider processes the text sent to it under its own service terms and billing. Actual image pixels and non-JSON attachments are not included in this first version: JSON image paths remain references, while fields such as `alt_text` can be translated. To analyze or generate image assets, include them in an uploaded course bundle and add a visual-asset workflow. Google recommends storing the Gemini key in an environment variable; this app reads it from `.env`. See [Gemini API key guidance](https://ai.google.dev/gemini-api/docs/generate-content/api-key).

To try the idiom path, upload `sample_idiom_course.json`, set source language to `EN`, target language to `PT`, locale to `pt-PT`, and choose **AI adapt + translate**. The AI should provide a meaning-preserving Portuguese adaptation of the bird-in-the-hand proverb and show its reasoning in the localization notes. AI wording can vary, so review it before publishing.

## Course JSON fields

The app retains the uploaded JSON structure and translates string values under these keys by default: `title`, `description`, `body`, `content`, `text`, `question`, `answer`, `options`, `caption`, `alt_text`, `transcript`, `example`, `feedback`, and `hint`. Add your course's text-bearing keys to `TEXT_FIELDS` in `app.py` if needed.

The HTML view renders nested objects, arrays, and text into course sections and cards. It shows image/file references as asset labels; it does not upload image files or embed them. Review examples, assets, units, links, and assessments with a person familiar with the target locale.

## API key and privacy

Keep your key in `.env`; do not paste it into source code or share it. Previewing only reads the uploaded file locally. Choosing translation sends text fields to DeepL. The development server binds to `127.0.0.1`, so it is intended for local use.

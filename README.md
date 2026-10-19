# Course Localizer Web UI

A local Flask app for uploading a course JSON file and viewing it as a readable HTML course page. It offers a plain DeepL translation flow and an AI adaptation flow that analyzes course terminology and idioms, creates a DeepL glossary automatically, then renders the localized course as HTML.

## Run on Windows

Open PowerShell in this folder, then run:

```powershell
py -m venv env
.\env\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Replace `put_your_deepl_api_key_here` in `.env` with your DeepL API key and `put_your_gemini_api_key_here` with a Gemini API key, then save. The app uses Gemini for AI analysis/adaptation and DeepL for translation and glossary creation.

Set `GEMINI_MODEL` to a model available to your API account if the default is unavailable. The regular **Translate with DeepL** and **Preview course** actions do not require a Gemini key.

```powershell
.\env\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000 in your browser. Select a JSON course and choose **Preview course** to render it as HTML, or **Translate with DeepL** to translate and render it. The app supports uploads up to 10 MB.

## AI adaptation flow

Choose **AI adapt + translate** to send the learner-facing text and audience profile to Gemini. It returns structured glossary suggestions and target-locale rewrites for idioms or culture-bound passages. The app creates a DeepL glossary from relevant suggested terms, translates the course through DeepL using that glossary, and applies the AI rewrites to the identified passages. The result page lists the suggested terms and each special adaptation so you can review what changed. Gemini structured output keeps the analysis in the fields the app expects. See [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

The AI button needs both a Gemini API key and a DeepL API key. Each provider processes the text sent to it under its own service terms and billing. Actual image pixels and non-JSON attachments are not included in this first version: JSON image paths remain references, while fields such as `alt_text` can be translated. To analyze or generate image assets, include them in an uploaded course bundle and add a visual-asset workflow. Google recommends storing the Gemini key in an environment variable; this app reads it from `.env`. See [Gemini API key guidance](https://ai.google.dev/gemini-api/docs/generate-content/api-key).

To try the idiom path, upload `sample_idiom_course.json`, set source language to `EN`, target language to `PT`, locale to `pt-PT`, and choose **AI adapt + translate**. The AI should provide a meaning-preserving Portuguese adaptation of the bird-in-the-hand proverb and show its reasoning in the localization notes. AI wording can vary, so review it before publishing.

## Create and use a glossary manually (optional)

You can skip this when using **AI adapt + translate**, which proposes terms from the course. If you want to provide terms yourself, use the **Optional: create a glossary yourself** section. Enter a name, source/target language codes, and one term pair per line, for example:

```text
customer support => atención al cliente
learning module => módulo de aprendizaje
BrandName => BrandName
```

Choose **Create glossary in DeepL**. The app sends the term pairs to DeepL's glossary endpoint. After DeepL returns an ID, the app shows it in the **DeepL glossary ID** field in the localization profile. Then upload the course and click **Translate with DeepL** to apply it. A glossary must use the same source/target language pair as the course translation.

## Course JSON fields

The app retains the uploaded JSON structure and translates string values under these keys by default: `title`, `description`, `body`, `content`, `text`, `question`, `answer`, `options`, `caption`, `alt_text`, `transcript`, `example`, `feedback`, and `hint`. Add your course's text-bearing keys to `TEXT_FIELDS` in `app.py` if needed.

The HTML view renders nested objects, arrays, and text into course sections and cards. It shows image/file references as asset labels; it does not upload image files or embed them. Review examples, assets, units, links, and assessments with a person familiar with the target locale.

## API key and privacy

Keep your key in `.env`; do not paste it into source code or share it. Previewing only reads the uploaded file locally. Choosing translation sends text fields to DeepL. The development server binds to `127.0.0.1`, so it is intended for local use.

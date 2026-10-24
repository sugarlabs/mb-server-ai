# mb-server-ai

The server behind the two AI widgets in Music Blocks, Reflection and the AI debugger. Music
Blocks runs in the browser and can't keep a key secret, so the widgets send their requests
here, and this server calls the model with the key.

Music Blocks expects it at `https://api.musicblocks.sugarlabs.org` (see `BACKENDS` in
`js/widgets/reflection.js` and `ALLOWED_BACKENDS` in `js/widgets/aidebugger.js`). On your own
computer the widgets look for it at `http://127.0.0.1:8000`.

## What it answers

| Path | Widget | What it does |
|---|---|---|
| `POST /projectcode` | Reflection | Describes the project and guesses what it is for |
| `POST /updatecode` | Reflection | Says what changed since the last description |
| `POST /chat` | Reflection | A reply from one of the three mentors |
| `POST /analysis` | Reflection | A short report of the chat |
| `POST /analyze` | AI debugger | A first look at the project, then answers |
| `POST /fix` | AI debugger | "Fix it for me": the project changed as the chat asked |
| `POST /make` | AI debugger | "Make a new project" from a description |
| `GET /health` | | How many requests were answered today |

Every failure comes back as `{"error": "..."}` with a short message the widget can show a child.

## How it is protected

- Only pages on `https://musicblocks.sugarlabs.org` and `https://sugarlabs.github.io` are
  answered. Browsers send the page's site and don't let a page change it, so other websites
  can't use this server. A script can still claim any site, so the limits below are what stop
  scripts.
- Each visitor gets 10 requests a minute and 100 a day, and everyone together gets 500 a day.
  Requests that are malformed or from another site are refused before they count. The counts are
  kept in memory, so they start again when the server restarts.
- Every prompt tells the model that a child aged 8 to 14 is writing, keeps it to Music Blocks,
  and tells it never to ask for personal information.
- The model writes projects as block trees, and `project.py` turns them into Music Blocks' save
  format, so the model never writes that format itself. A tree that can't be built is sent back
  to the model once with the error, then refused.

## Run it

```
pip install -r requirements.txt
BEDROCK_API_KEY=... ALLOWED_ORIGINS=http://127.0.0.1:3000 uvicorn app:app --port 8000
```

Then start Music Blocks with `npm run serve` (port 3000) and open a Reflection or AI debugger
block.

With Docker, put the settings in `mb-server-ai.env` and run:

```
docker build -t mb-server-ai .
docker run --env-file mb-server-ai.env -p 8000:8000 mb-server-ai
```

Behind a proxy that adds the visitor's address to `X-Forwarded-For` (Caddy does this), the
limits count each visitor apart.

## Settings

| Variable | Default | |
|---|---|---|
| `BEDROCK_API_KEY` | none, required | An Amazon Bedrock API key |
| `ALLOWED_ORIGINS` | the two Music Blocks sites | Comma separated |
| `BEDROCK_MODEL` | `us.openai.gpt-6-luna` | Any model Bedrock serves through its OpenAI-style API |
| `BEDROCK_REASONING` | `medium` | For "Fix it for me" and "Make a new project". The other replies have reasoning off, since the widgets give up after 30 seconds |
| `PER_MINUTE_LIMIT` | 10 | For each visitor |
| `DAILY_VISITOR_LIMIT` | 100 | For each visitor |
| `DAILY_REQUEST_LIMIT` | 500 | For everyone together |

## Tests

```
pip install pytest
pytest
```

`test_project.py` reads the example projects in a Music Blocks checkout, `../musicblocks` by
default or the path in `MUSICBLOCKS`. The tests use a fake model, so they need no key.

## Updating the block data

`data/blocks.json` holds every block's definition and `data/knowledge.json` the block cards,
guide sections and example projects the prompts quote. Both are built from a Music Blocks
checkout, so after Music Blocks adds or changes blocks:

```
node extract_blocks.cjs ../musicblocks > data/blocks.json
python knowledge.py ../musicblocks
```

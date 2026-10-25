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
| `POST /fix` | AI debugger | "Change my project": the project changed as the child asked |
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

## Try it with Groq

Sugar Labs runs this on Bedrock, which is why the settings start with `BEDROCK_`, but any
OpenAI-style API works. Groq gives free keys, so it is the easiest way to try it. You need Python
3.11 or newer, Node.js 22, git and a key from https://console.groq.com/keys.

Start the server:

```
git clone https://github.com/sugarlabs/mb-server-ai
cd mb-server-ai
pip install -r requirements.txt

export BEDROCK_API_KEY=gsk_your_groq_key
export BEDROCK_BASE_URL=https://api.groq.com/openai/v1
export BEDROCK_MODEL=qwen/qwen3.8-27b
export ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
uvicorn app:app --port 8000
```

In another terminal, start Music Blocks:

```
git clone https://github.com/sugarlabs/musicblocks
cd musicblocks
npm install
npm run serve
```

Nothing in Music Blocks needs changing. When the page is on `127.0.0.1` or `localhost`, the widgets
send their requests to port 8000 on the same computer. The debugger's Edit project tab is new in
sugarlabs/musicblocks#9802, so until that is merged, run `git fetch origin pull/9802/head:ai-widgets`
and `git checkout ai-widgets` before `npm run serve` to try it.

Then in the browser:

1. Open http://127.0.0.1:3000 and wait for the blocks to load.
2. Click the Widgets palette on the left.
3. Drag the "reflection" block or the "debugger" block onto the canvas.
4. Click the block to run it. Its window opens.
5. In Reflection, pick a mentor and ask a question. In the debugger, ask about the project in the
   Chat tab, or open the Edit project tab and try "Change my project" or "Make a new project".

Each request shows up in the server's terminal. If a window says it can't reach the server,
check that uvicorn is still running on port 8000 and that the page address is in
`ALLOWED_ORIGINS`.

Groq's free keys allow 8,000 tokens a minute. A big project can use most of that in one request,
so if Groq says you are over the limit, wait a minute and try again.

## Settings

| Variable | Default | |
|---|---|---|
| `BEDROCK_API_KEY` | none, required | An Amazon Bedrock API key |
| `ALLOWED_ORIGINS` | the two Music Blocks sites | Comma separated |
| `BEDROCK_MODEL` | `us.openai.gpt-6-luna` | Any model Bedrock serves through its OpenAI-style API |
| `BEDROCK_REASONING` | `medium` | For "Change my project" and "Make a new project". The other replies have reasoning off, since the widgets give up after 30 seconds |
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

## License

GNU Affero General Public License v3 or later, the same as Music Blocks. See `LICENSE`.

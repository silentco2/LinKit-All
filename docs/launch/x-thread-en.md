# X thread (English)

Post 1 carries the GIF. The GitHub link goes in a reply (X ranks posts with links lower).
Post 5 carries the comparison table as an image: screenshot the "How it compares" table from
the README.

---

**1/** (GIF)
I built an open-source job search agent that runs on your own computer.

It finds jobs, ranks them against your CV, tailors the CV a few words per job, and fills in the applications.

And it never presses Submit until you say so. 🧵

**2/**
Finding: 295 sources. Public job APIs of Greenhouse, Lever, Ashby, Workday and 100+ other ATSs, LinkedIn and Indeed listings, regional boards, any careers page you paste.

Ranking runs locally. No AI cost.

**3/**
Tailoring is where AI tools lie for you.

Here the model can only propose small patches. Plain code refuses any patch that changes an employer, title, date, number or contact detail, or adds a tool you don't have.

**4/**
Visa, salary, demographics: never sent to the AI. Answered from your profile, or the job waits for you.

LinkedIn, Indeed, Glassdoor: never driven by a bot (accounts get banned). A browser extension fills them while you press Submit.

**5/** (comparison table image)
How it compares with AIHawk and ApplyPilot, from each project's own README.

**6/**
Bring your own AI: ChatGPT or Claude plan, an API key, or a local model with Ollama.

Honest number: 115 real postings in Practice mode → 67 of the 70 it may finish alone (96%) went as far as Practice mode allows. Small sample. Nothing submitted.

**7/**
Free, AGPL-3.0, Windows / macOS / Linux, English and Arabic.

`uv tool install linkit-all`

Link below. If it saves you an application, a ⭐ helps others find it.

**Reply to 1/:**
https://github.com/silentco2/LinKit-All

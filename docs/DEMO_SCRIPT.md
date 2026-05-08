# paper2vis — 4-Minute Demo Script

---

## SETUP (before recording)
- Have a good math/ML paper ready (e.g. "Attention Is All You Need")
- Start dev server (`uvicorn src.api.main:app` + `next dev`)
- Open browser to `http://localhost:3000` — home page visible
- Have a previous completed job ready to jump to for the animation showcase

---

## SEGMENT 1 — The Problem (0:00 – 0:40)

**[Screen: a dense PDF of an academic paper — zoom in on an equation]**

> "This is what research looks like. Dense notation, pages of proof, figures that assume years of domain knowledge. If you want to understand a paper — really understand it — you're looking at hours of work. And if you're teaching it? Even longer."

> "What if a paper could explain itself? What if you could hand any PDF to an AI and get back animated, narrated explanations of every key concept — in seconds?"

> "That's paper2vis."

**[Cut to: browser at localhost:3000, the upload page]**

---

## SEGMENT 2 — Upload & Configure (0:40 – 1:10)

**[Screen: upload page — drag PDF onto the drop zone]**

> "We start simple. Drop a paper. I'm using the original Transformer paper — Attention Is All You Need."

> "A few options: how many concepts to extract, the quality level, whether to use voice narration. We'll do 4 concepts at high quality with narration on."

**[Click "Generate Animations"]**

> "And we're off. The pipeline starts immediately."

---

## SEGMENT 3 — Live Pipeline (1:10 – 1:55)

**[Screen: job page — show the pipeline stage tracker updating in real time]**

> "Watch what happens. The PDF gets parsed in under a second. The AI reads every section and identifies the most visualizable concepts — atomic operations it can animate."

**[Show the activity feed ticking, concept stubs appearing one by one]**

> "Four concepts found. Scaled dot-product attention. Softmax normalization. Positional encoding. Multi-head projection. Each one is now being animated in parallel."

**[Concept skeletons appear, then one by one fill in with videos]**

> "For each concept the pipeline runs: it generates Manim code, renders it, then an AI critic reviews keyframes and scores the result. If the score is too low, it fixes the code and re-renders — automatically."

> "No human in the loop. Just the paper and the pipeline."

---

## SEGMENT 4 — The Animations (1:55 – 3:05)

**[Switch to the pre-completed job — scroll to first ConceptCard]**

> "Let's look at what came out."

**[Play the Softmax animation — let it run for ~20 seconds]**

> "Softmax normalization. The raw attention scores — 1.2, 0.3, 2.1 — flow in, exponentiated, normalized. You watch the probability mass shift. In a textbook this is one line of notation. Here you see it."

**[Click the history timeline — show the initial render vs critic fix]**

> "And here's something interesting. The critic scored this first attempt a 6 out of 10 — the bars weren't animating, just appearing statically. It flagged that, applied a fix, re-rendered. The second version scored a 9."

**[Scroll to the Positional Encoding card — play it]**

> "Positional encoding. Sine waves at different frequencies. Values changing, phase offsets visible. The paper describes this in two dense paragraphs. The animation shows it in 30 seconds."

**[Click "Storyboard" to briefly show the storyboard panel]**

> "Every animation has a full storyboard — the AI's director's notes. Beat by beat, exactly what appears on screen."

---

## SEGMENT 5 — The Concept Map (3:05 – 3:35)

**[Scroll up to the interactive concept map]**

> "But individual animations aren't the whole picture. paper2vis also builds a concept map — a structured graph of how the ideas relate."

**[Hover over a node, show edge labels appear]**

> "Positional encoding feeds into multi-head attention. Softmax is a prerequisite for the attention score. The concepts are ordered by dependency — not by page number."

**[Click a node — it scrolls smoothly to the concept card]**

> "And every node is live. Click it, jump directly to that animation. This is what we're calling a liquid paper — not a static document, but a navigable, verified knowledge graph."

---

## SEGMENT 6 — Wrap (3:35 – 4:00)

**[Screen: full job page with multiple completed cards visible]**

> "paper2vis turns any research PDF into an animated knowledge base. Concept extraction, Manim animation, AI critique, narration, and an interactive concept graph — end to end, in minutes."

> "We're building toward a world where every paper is executable, every concept is explorable, and understanding doesn't require hours of careful reading. It requires pressing a button."

---

## PRODUCTION NOTES

| Segment | Duration | Key visual |
|---------|----------|------------|
| Problem | 0:40 | Zoom into dense PDF equation |
| Upload | 0:30 | Drag-and-drop, options panel |
| Pipeline | 0:45 | Live activity feed, stubs populating |
| Animations | 1:10 | 2 animations + history timeline |
| Concept map | 0:30 | Node hover + click-to-scroll |
| Wrap | 0:25 | Full results page |

**Recording tips:**
- Use QuickTime screen recording at 1440p
- Mic: speak slowly, pause at visual beats
- Edit out any API latency with a jump cut + "60 seconds later" title card
- Background music: something minimal/ambient, -20dB under voice

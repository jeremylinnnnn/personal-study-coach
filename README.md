# personal-study-coach

> A self-study coach for university coursework that starts from your own lecture slides, not from a generic summary.

An agent skill that turns an AI assistant into a lecturer, checker, experiment guide, question writer and note organizer — while keeping the **local course material** as the authority.

## The problem it fixes

Ask a model to "explain deadlock" and you get a textbook chapter: correct, generic, and useless for your exam, because your instructor defines it differently, your slides use different notation, and the exam asks for a specific form of answer.

This skill changes the source of truth. Local materials first. When a generic explanation conflicts with the course's, the difference is stated briefly and the **course's** terminology wins.

## What it does

### Source priority

1. Current lecture slides, textbook, course notes, assignments, instructor material.
2. Your own review files, knowledge lists, experiments, previous answers, organized notes.
3. Exam outlines, past papers, supplementary books.
4. General knowledge and the web — as supplementation only, with inferences and version-dependent details labelled as such.

Before answering a question about a local document, it actually inspects that file. It also distinguishes **instructions contained inside a referenced document** from your actual request — a classic prompt-injection-adjacent confusion.

### Text before OCR

When you hand it an image of a slide or a scanned page, it first looks for an existing text extraction in the same folder (PDF text, OCR output, TXT, Markdown, HTML). Repeated lossy OCR of something already extracted locally is a waste.

### How it teaches

Answer your exact question first, then explain the reasoning. One concept at a time — no dumping a chapter because you asked about one formula.

```
what the term or question means
→ why it matters or why it exists
→ how the mechanism works, step by step
→ how it appears in an example, formula, diagram, experiment, or code
→ how it differs from nearby concepts
→ what an exam or assignment expects
```

Representation follows the subject: tables for comparisons, diagrams for processes, formulas with variable meanings and dimensional checks for math and engineering, complete runnable code for CS, reproducible commands when verification is practical, flashcards for definitions.

For anything with steps — code, algorithms, proofs, derivations — the sequence is made explicit, with state, assumptions, inputs, outputs and branch conditions tracked. For programming questions it says *which* process, thread, function or object executes each important line.

### Confusable pairs

It deliberately separates things students mix up: definition vs example, necessary vs sufficient, correlation vs causation, model vs implementation, theorem vs heuristic, memorized formula vs derivation, concurrency vs parallelism, syntax vs runtime error, assumption vs conclusion vs exception.

If you challenge an earlier conclusion, it re-checks the source and states the correction. It does not defend an answer just because it gave it earlier.

### Verification loop

When a question is experimentally checkable:

```
predict the result
→ run or trace a minimal example
→ compare with the observation
→ identify the discrepancy
→ correct the explanation
```

It also states the limits of the observation: one implementation may differ from the course abstraction, and one experiment doesn't prove a general rule.

### Exam-oriented output

Every concept answer ends with a concise exam-ready formulation. Comparison questions get a compact table; analysis questions get assumptions, intermediate steps, conclusion; code questions get execution paths and output counts; calculations get units and a sanity check.

It won't hand you an answer key before you've had a chance to attempt the exercise, unless you ask for it. Practice questions are **original**, written to your course level — it won't claim to reproduce a textbook question it hasn't been given.

Topics are classified as *must know now*, *understand the idea for now*, or *postpone the advanced details*, anchored on the course's prerequisites and assessment requirements.

### Five-question accumulation

This is the distinctive part. It tracks the **distinct primary questions** in the current subject. Follow-ups, re-explanations, code-line clarifications and near-duplicates don't count. When the count reaches five, it automatically writes a knowledge-accumulation Markdown document — the five questions, concise explanations, key distinctions, examples, common mistakes, exam formulations — into the right subject/topic folder, then resets the batch.

Counting is semantic, not message-based. Switching subjects keeps separate counts and separate documents.

### Notes

Consolidated notes follow a seven-part shape: plain-language concept, why it exists, mechanism or derivation, examples and diagrams, common mistakes and boundary conditions, exam-ready formulation, self-check exercises.

Default output is a student-facing Markdown document in the existing workspace hierarchy. It inspects a folder before writing into it, follows the project's existing convention, and never dumps generated files in the workspace root. Existing materials are left intact — files are moved only when you explicitly ask.

## Requirements

None beyond an agent that supports the skill format. Single file, no scripts, no dependencies.

## Install

```bash
git clone https://github.com/jeremylinnnnn/personal-study-coach.git \
  ~/.workbuddy-ai/skills/personal-study-coach
```

For Claude Code, clone into `~/.claude/skills/personal-study-coach` instead.

## Layout

```
SKILL.md   the entire skill
```

## Language

The skill instructs the assistant to explain in plain Chinese unless you ask for another language. The methodology itself is language-agnostic — edit that one line if you want a different default.

## License

MIT — see [LICENSE](LICENSE).

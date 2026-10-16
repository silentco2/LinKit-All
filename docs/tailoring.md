# Tailoring your CV

For each job it is going to apply to, LinKit All makes a version of your CV that fits the
posting a little better. The edits are small and strictly checked. The layout is never touched.

Tailoring happens just before applying, and only for jobs that will really be applied to. A
job that comes back from the [Action Center](action-center.md) reuses its tailored CV, so
you do not pay for it twice.

## How it works

1. Your CV is split into **numbered text segments**: body text, tables, text boxes, headers
   and footers.
2. The AI reads the segments and the job description. It replies with **patches only**:

    ```json
    {"segment_id": 12, "old_text": "built APIs", "new_text": "built REST APIs", "reason": "the job asks for REST"}
    ```

    It never rewrites the CV as a whole.
3. LinKit All checks every patch against the rules below. Bad patches are rejected one by one.
4. The good patches are written into a copy of your CV.
5. The copy is turned into a PDF, and the PDF is checked against the original.
6. If the check passes, the PDF is the file that gets submitted. If it fails, everything is
   rolled back (see [Verify and roll back](#verify-and-roll-back)).

## Locked facts

A patch is rejected if it changes anything you locked.

- **Locked facts** are the lines you list in the wizard (employers, job titles, degrees). A
  patch may not add, remove or change them.
- **Numbers, dates, metrics and contact details** are always locked, even if you list
  nothing. A patch may not add, remove or change any word that has a digit, an `@`, `%`,
  `$`, a currency sign, a link, or a `www.` address.

## The rules

A patch is rejected when it:

- names a segment that does not exist, or its `old_text` is not found exactly once in
  that segment;
- changes nothing, or adds a tab or line break;
- touches a locked fact, or changes a number, date, metric or contact detail;
- **adds a skill or claim that is not in your CV or your skills list.** Words that look like
  names, tools or acronyms (`Kubernetes`, `Node.js`, `AWS`) must already appear in your CV or
  skills list. Plain lowercase rewording passes;
- makes a segment more than **10%** longer (in characters); or
- pushes the total changed words past **15%** of the CV.

Patches are accepted in order until the total word budget is used up. Every accepted and
rejected patch is saved with its reason.

!!! note "A heuristic, not a guarantee"
    The check for new skills is a word-shape check. A tool name written in lowercase can slip
    through. Read the red-line before you go live. The limits can be changed with
    `LINKIT_TAILOR_MAX_GROWTH` and `LINKIT_TAILOR_MAX_WORD_CHANGE`.

## CV formats

| Format | How it is handled |
|---|---|
| **Word (`.docx`)** | Edited directly. New text goes into the first run of a span and the other runs are emptied, so fonts, colors and styles stay. Text boxes and headers and footers are covered. Most reliable. |
| **OpenDocument (`.odt`)** | Converted to Word by LibreOffice when you upload it. |
| **PDF** | Converted to Word once, with `pdf2docx`. Conversion can garble things, so you must **approve the converted CV** in the wizard before it is used. After that it is treated as Word. |
| **LaTeX (`.tex`)** | Only the text is edited, never commands. Compiled with Tectonic. Must be one self-contained file (no `\input`). A patch that would touch anything but text is rejected on its own. |

The submitted file is always a PDF: LibreOffice makes it for Word, ODT and PDF CVs, and Tectonic
for LaTeX.

## Verify and roll back

After the tailored PDF is made, LinKit All compares it with a PDF of your original CV:

- the **page count** is the same;
- every page looks like the original, with a similarity score (SSIM) of at least **0.85**
  (`LINKIT_TAILOR_MIN_SSIM`);
- the text can be read back out of the PDF.

If a check fails, LinKit All tries once more with only the patches that do not make text
longer (growth is what usually breaks layout). If that fails too, it **rolls back**: your
original CV is used, unchanged, and the patches are recorded as dropped with the reason.
An untailored CV is always better than a broken one.

## Seeing what changed

Try tailoring on its own with any job text:

```bash
linkit tailor jd.txt --title "Backend Engineer" --company "Acme"
```

It prints each patch as a red-line (removed text in red, added text in green), then the
rejected patches with their reasons, the layout check, and the PDF path.

```text
[12] the job asks for REST
  - built APIs
  + built REST APIs
1 applied, 0 rejected -> ...\tailored\adhoc-20261016-120000\cv.pdf
```

During a normal run, each job's tailored CV is stored under `tailored/job_<id>/` in your data
folder. Its patch list (applied and rejected, with reasons) and layout check are saved in the
database. The web page does not show a red-line view yet.

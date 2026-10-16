# Action Center

The Action Center is the list of jobs that stopped and need you. LinKit All parks a job here
instead of guessing. Open **Action Center** in the left menu. A badge shows how many items
are waiting. Turn on **Desktop notifications** (bottom of the menu) to get a browser alert
when something needs you, or when a run finishes or pauses. Alerts work while LinKit All is
open in a browser tab.

Each item shows the job, a message, and screenshots of the page when it stopped.

## Kinds of items

| Kind | What it means | What to do |
|---|---|---|
| **Unknown question** | The form asked something LinKit All cannot answer from your profile, saved answers or CV, or it is a [sensitive question](#sensitive-questions). | Answer each question. Required ones must be filled. Press **Save answers and retry**. |
| **Ready to submit** | Live mode, and *Submit without asking* is off. The form is filled and waiting. | Check the screenshot and the table of filled answers (each has a source badge). Press **Submit application** or **Skip**. |
| **CAPTCHA** | The site showed a CAPTCHA. LinKit All never solves them. | Open the application page and finish by hand, then **I applied by hand**. Or press **Retry**. |
| **Validation error** | The form rejected an answer, or a required field could not be filled. The message says which. | Read the screenshot. **Retry**, or open the page and apply by hand. |
| **Login issue** | The site needs an account and LinKit All could not sign in: the vault is locked, the mailbox is not connected, the verification email did not arrive, the saved login was rejected, or the page is a sign-in page. | Fix the cause the message names (unlock the vault, connect email), then **Retry**. Or apply by hand. |
| **Two-factor** | The site asked for a sign-in code. | Apply by hand, or retry after you have dealt with the code. |

## Buttons

- **Save answers and retry** (unknown questions): your answers go into the
  [answer bank](#answer-bank) as yours, and the job returns to the apply queue.
- **Submit application** (ready to submit): confirms the job. The next Apply run submits it.
- **Retry**: puts the job back in the apply queue unchanged.
- **Open application page**: opens the posting's apply link in a new tab.
- **I applied by hand**: records the job as applied, because you did it yourself.
- **Skip**: drops the job.

!!! note "After you answer"
    Resolving an item does not apply right away. It puts the job back in the queue. Start
    **Apply** from the **Live run** page (or `linkit run apply`) to continue. The tailored CV
    is reused, so nothing is paid for twice.

## Sensitive questions

These categories are **never sent to the AI**:

- work authorization, visa and sponsorship;
- salary and pay expectations;
- gender, race or ethnicity, Hispanic or Latino, veteran status, disability, and other
  personal details (sexual orientation, pronouns, religion, marital status, age, date of birth);
- criminal record;
- being recorded or transcribed (for example AI note-takers in interviews);
- legal statements: arbitration, "I certify", non-compete, legally binding terms;
- privacy notices and data consent.

They are answered only from your [Application answers](setup.md#5-application-answers), or from
an earlier answer you typed yourself with almost identical wording. Otherwise they come here,
marked **Sensitive**. Your answer is stored on your computer only.

LinKit All also never picks "Prefer not to say" on its own. You must choose it.

## Answer bank

Every answer you give here is saved to the **Answer bank** page, where you can read, edit and
delete it. Answers drafted by the AI are marked `ai`. Editing one changes it to `user`.
Later forms with similar questions reuse the answer, matched by meaning. Sensitive answers are
reused only when the wording is nearly identical.

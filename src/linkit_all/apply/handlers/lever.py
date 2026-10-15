"""Lever: one-page form at <posting>/apply with native inputs."""

import re

from linkit_all.apply.handlers.base import Handler, JobInfo


class Lever(Handler):
    ats = "lever"
    container = "li.application-question"
    label = ".application-label"
    submit_button = "#btn-submit"  # runs Lever's hCaptcha check, then submits
    confirmation = re.compile(
        r"application submitted|thanks? (you )?for applying|we.ve received your application"
    )

    def form_url(self, job: JobInfo) -> str:
        return job.apply_url if job.apply_url.endswith("/apply") else f"{job.url.rstrip('/')}/apply"

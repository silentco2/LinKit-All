"""Ashby: React form at <posting>/application; yes/no questions are buttons."""

import re

from linkit_all.apply.handlers.base import Handler, JobInfo


class Ashby(Handler):
    ats = "ashby"
    container = (
        ".ashby-application-form-field-entry, fieldset.ashby-application-form-input-radio-group, "
        "fieldset.ashby-application-form-input-checkbox-group"
    )
    label = ".ashby-application-form-question-title, legend, label"
    description = ".ashby-application-form-question-description"
    submit_button = "button.ashby-application-form-submit-button"
    confirmation = re.compile(
        r"application (was )?(successfully )?submitted|thanks? (you )?for applying|"
        r"we.ve received your application"
    )

    def form_url(self, job: JobInfo) -> str:
        return (
            job.apply_url
            if job.apply_url.endswith("/application")
            else f"{job.url.rstrip('/')}/application"
        )

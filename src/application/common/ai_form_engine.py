from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import re
import asyncio

from .adaptive_form_runtime import FormObserver, AdaptiveWidgetFiller
from .question_router import QuestionIntentRouter


class AIFormEngine:
    """
    Deterministic form-filling engine.

    Responsibilities:
    - Inspect visible form controls
    - Infer semantic meaning from HTML attributes + labels
    - Fill safe profile-backed fields
    - Upload resume
    - Avoid guessing sensitive/unknown questions
    - Support text inputs, textareas, native selects, radios and checkboxes
    """

    SENSITIVE_FIELDS = {
        "work_authorization",
        "sponsorship",
        "salary",
        "current_ctc",
        "expected_ctc",
        "relocation",
        "gender",
        "date_of_birth",
    }

    SKIP_FIELDS = {
        "unknown",
        "choice",
        "submit",
        "resume",
        "cover_letter",
        "message",
        "date",
        "time",
        "full_name",
    }

    def __init__(
        self,
        page=None,
        profile: Optional[Dict[str, Any]] = None,
        enable_resume_upload: bool = True,
    ):
        self.page = page
        self.profile = profile or {}
        self.enable_resume_upload = bool(enable_resume_upload)

        self.fields = []
        self.fields_filled = 0
        self.resume_uploaded = False

        self.ai_fields_filled = 0
        self.fallback_fields_filled = 0
        self.total_fields_filled = 0
        self.observer = FormObserver()
        self.widget_filler = AdaptiveWidgetFiller()
        self.reasoner = None
        self.snapshot = []
        self.question_router = QuestionIntentRouter()

    # ================================================================
    # PROFILE
    # ================================================================

    def _get_nested(self, *paths, default=None):
        for path in paths:
            value = self.profile

            try:
                for key in path.split("."):
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        value = None
                        break
            except Exception:
                value = None

            if value is not None and value != "":
                return value

        return default

    def get_profile_value(self, semantic: str):
        personal = self.profile.get(
            "personal",
            {},
        )

        employment = self.profile.get(
            "employment",
            {},
        )

        preferences = self.profile.get(
            "preferences",
            {},
        )

        company_history = self.profile.get(
            "company_history",
            {},
        )

        personal_details = self.profile.get(
            "personal_details",
            {},
        )

        contact = self.profile.get("contact", {})
        candidate = self.profile.get("candidate", {})
        online_profiles = self.profile.get("online_profiles", {})

        education = self.profile.get(
            "education",
            {},
        )
        education_details = self.profile.get(
            "education_details",
            {},
        )
        if not isinstance(education, dict):
            education = {}
        if not isinstance(education_details, dict):
            education_details = {}

        links = self.profile.get(
            "links",
            {},
        )

        preferred_locations = preferences.get(
            "preferred_locations",
            [],
        )

        if not isinstance(preferred_locations, list):
            if preferred_locations in (None, ""):
                preferred_locations = []
            else:
                preferred_locations = [preferred_locations]

        return {
            "first_name": personal.get("first_name") or str(contact.get("name", "")).split(" ")[0] or candidate.get("first_name"),

            "last_name": personal.get("last_name") or (" ".join(str(contact.get("name", "")).split(" ")[1:]) or candidate.get("last_name")),

            "full_name": personal.get("full_name") or contact.get("name") or candidate.get("name"),

            "email": personal.get("email") or contact.get("email") or candidate.get("email"),

            "phone": personal.get("phone") or contact.get("phone") or candidate.get("phone"),

            "city": personal.get("city") or contact.get("city") or candidate.get("city"),

            "state": personal.get("state") or contact.get("state") or candidate.get("state"),

            "country": personal.get("country") or contact.get("country") or candidate.get("work_country"),

            "pincode": personal.get("pin_code") or contact.get("pin_code") or candidate.get("pincode"),

            "current_company": employment.get(
                "current_company"
            ),

            "currently_employed": employment.get(
                "currently_employed"
            ),

            "experience_years": employment.get(
                "total_experience_years",
                0,
            ),

            "experience_months": employment.get(
                "total_experience_months",
                0,
            ),

            "current_ctc": employment.get(
                "current_ctc"
            ),

            "last_drawn_salary": employment.get(
                "last_drawn_salary"
            ),

            "expected_ctc": employment.get(
                "expected_ctc"
            ),

            "notice_period": employment.get(
                "notice_period"
            ),

            "available_to_join": employment.get(
                "available_to_join"
            ),

            "work_authorization": employment.get(
                "work_authorization"
            ),

            "sponsorship": (
                "Yes"
                if employment.get(
                    "requires_sponsorship"
                ) is True
                else "No"
                if employment.get(
                    "requires_sponsorship"
                ) is False
                else None
            ),

            "relocation": employment.get(
                "willing_to_relocate"
            ),

            "preferred_location_1": (
                preferred_locations[0]
                if len(preferred_locations) > 0
                else None
            ),

            "preferred_location_2": (
                preferred_locations[1]
                if len(preferred_locations) > 1
                else None
            ),

            "preferred_location_3": (
                preferred_locations[2]
                if len(preferred_locations) > 2
                else None
            ),

            "ust_employment": company_history.get(
                "ust_previous_employment"
            ),

            "gender": personal_details.get(
                "gender"
            ),

            "date_of_birth": personal_details.get(
                "date_of_birth"
            ),

            "degree": (
                education.get("degree")
                or education_details.get("degree")
                or str(candidate.get("education", "")).split(",", 1)[0].strip()
            ),

            "specialization": (
                education.get("specialization")
                or education.get("branch")
                or education_details.get("specialization")
                or education_details.get("branch")
                or (
                    str(candidate.get("education", "")).split(",", 1)[1].strip()
                    if "," in str(candidate.get("education", ""))
                    else None
                )
            ),

            "college": (
                education.get("college")
                or education_details.get("college")
                or self.profile.get("questionnaire_facts", {}).get("college")
            ),

            "graduation_year": (
                education.get("graduation_year")
                or education_details.get("graduation_year")
                or candidate.get("graduation_year")
                or self.profile.get("questionnaire_facts", {}).get("graduation_year")
            ),

            "cgpa": (
                education.get("cgpa")
                or education_details.get("cgpa")
                or candidate.get("cgpa")
                or self.profile.get("questionnaire_facts", {}).get("cgpa")
            ),

            "current_year_of_study": education.get("current_year_of_study") or education_details.get("current_year_of_study"),

            "currently_studying": education.get("currently_studying") if "currently_studying" in education else education_details.get("currently_studying"),

            "linkedin": links.get("linkedin") or online_profiles.get("linkedin"),

            "github": links.get("github") or online_profiles.get("github"),

            "job_role": self._get_nested(
                "application_job_role",
                "job_role",
                "candidate.current_designation",
            ),

            "joining_date": self._get_nested(
                "joining_date",
                "employment.joining_date",
            ),

            "available_to_join": employment.get(
                "available_to_join",
                self.profile.get("candidate", {}).get("available_to_join_immediately"),
            ),

            "notice_period_days": self._get_nested(
                "employment.notice_period_days",
                "candidate.notice_period_days",
                "questionnaire_facts.notice_period_days",
                default=0,
            ),

            "city": personal.get("city") or self.profile.get("contact", {}).get("city"),

            "address": personal.get("street_address") or self.profile.get("contact", {}).get("street_address"),

            "bio": self._get_nested(
                "professional_summary",
                "candidate.professional_summary",
                default="",
            ),

            "professional_summary": self._get_nested(
                "professional_summary",
                default="",
            ),
        }.get(semantic)

    # ================================================================
    # LABEL DETECTION
    # ================================================================

    async def _find_label(self, locator):
        # Prefer true semantic labels and ARIA references. Avoid using a broad
        # row/container as the label when it contains multiple controls.
        try:
            field_id = await locator.get_attribute("id")
            if field_id:
                labels = self.page.locator(f"label[for=\"{field_id}\"]")
                if await labels.count():
                    text = (await labels.first.inner_text()).strip()
                    if text:
                        return text
        except Exception:
            pass

        try:
            labelled = await locator.get_attribute("aria-labelledby")
            if labelled:
                parts = []
                for token in re.split(r"\s+", labelled.strip()):
                    if not token:
                        continue
                    try:
                        node = self.page.locator(f"#{token}")
                        if await node.count():
                            text = (await node.first.inner_text()).strip()
                            if text:
                                parts.append(text)
                    except Exception:
                        continue
                if parts:
                    return " ".join(parts).strip()
        except Exception:
            pass

        for selector in (
            "xpath=ancestor::label[1]",
            "xpath=ancestor::*[self::mat-form-field or self::div][1]//mat-label[1]",
            "xpath=ancestor::*[self::mat-form-field or self::div][1]//*[contains(concat(' ', normalize-space(@class), ' '), ' mdc-floating-label ')][1]",
        ):
            try:
                node = locator.locator(selector)
                if await node.count():
                    text = (await node.first.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue

        for levels in (1, 2, 3):
            try:
                node = locator
                for _ in range(levels):
                    node = node.locator("xpath=..")
                controls = node.locator("input, textarea, select")
                if await controls.count() != 1:
                    continue
                text = (await node.inner_text()).strip()
                if text and len(text) <= 240:
                    return re.sub(r"\s+", " ", text)
            except Exception:
                continue

        return ""

    # ================================================================
    # FIELD METADATA
    # ================================================================

    async def _field_metadata(self, locator):
        try:
            tag = (
                await locator.evaluate(
                    "(el) => el.tagName"
                )
            ).lower()
        except Exception:
            tag = ""

        attrs = {}

        for attr in [
            "id",
            "name",
            "type",
            "placeholder",
            "aria-label",
            "autocomplete",
            "class",
        ]:
            try:
                attrs[attr] = (
                    await locator.get_attribute(
                        attr
                    )
                    or ""
                )
            except Exception:
                attrs[attr] = ""

        label = await self._find_label(
            locator
        )

        return {
            "locator": locator,
            "tag": tag,
            "label": label,
            **attrs,
        }

    # ================================================================
    # TEXT CLASSIFICATION
    # ================================================================

    def _classify_text(self, text: str):
        if text is None:
            text = ""
        else:
            text = str(text)

        text = (
            text
            .lower()
            .strip()
        )

        # ------------------------------------------------------------
        # IMPORTANT:
        # Middle Name must NEVER become full_name.
        # ------------------------------------------------------------

        if re.search(
            r"\bmiddle\s+name\b",
            text,
        ):
            return "unknown"

        if any(
            x in text
            for x in [
                "linkedin",
                "linkedin profile",
            ]
        ):
            return "linkedin"

        if any(
            x in text
            for x in [
                "github",
                "github profile",
            ]
        ):
            return "github"

        if any(
            x in text
            for x in [
                "portfolio",
                "personal website",
            ]
        ):
            return "portfolio"

        if any(
            x in text
            for x in [
                "resume",
                "cv",
                "curriculum vitae",
            ]
        ):
            return "resume"

        if any(
            x in text
            for x in [
                "cover letter",
                "coverletter",
            ]
        ):
            return "cover_letter"

        if "first name" in text:
            return "first_name"

        if "last name" in text:
            return "last_name"

        # ONLY explicit full/candidate name.
        # Do NOT use generic "name".
        if (
            "full name" in text
            or "candidate name" in text
        ):
            return "full_name"

        if any(
            x in text
            for x in [
                "email",
                "e-mail",
            ]
        ):
            return "email"

        if any(
            x in text
            for x in [
                "phone",
                "mobile",
                "telephone",
                "contact number",
            ]
        ):
            return "phone"

        if any(
            x in text
            for x in [
                "pin code",
                "pincode",
                "postal code",
                "zip code",
                "zipcode",
            ]
        ):
            return "pincode"

        if "current company" in text:
            return "current_company"

        if any(
            x in text
            for x in [
                "current location",
                "present location",
                "location currently",
            ]
        ):
            return "city"

        if any(
            x in text
            for x in [
                "preferred location 1",
                "preferred location",
                "preferred city",
            ]
        ):
            return "preferred_location_1"

        if "preferred location 2" in text:
            return "preferred_location_2"

        if "preferred location 3" in text:
            return "preferred_location_3"

        if any(
            x in text
            for x in [
                "current salary",
                "current ctc",
                "current compensation",
                "last drawn salary",
                "last salary",
            ]
        ):
            return "current_ctc"

        if any(
            x in text
            for x in [
                "expected salary",
                "expected ctc",
                "expected compensation",
                "annual salary",
            ]
        ):
            return "expected_ctc"

        if any(
            x in text
            for x in [
                "notice period",
                "joining availability",
                "available to join",
            ]
        ):
            return "notice_period"

        # ``experience`` is intentionally NOT enough to mean years.  Route
        # yes/no and open-ended experience questions to the grounded reasoner.
        experience_route = self.question_router.route(label=text)
        if experience_route["intent"] == "experience_years":
            return "experience_years"
        if experience_route["intent"] in {
            "skill_experience_yes_no", "project_experience_yes_no",
            "experience_yes_no", "experience_text", "project_text", "open_text",
        }:
            return "unknown"

        if any(
            x in text
            for x in [
                "work authorization",
                "legally authorized",
                "authorized to work",
            ]
        ):
            return "work_authorization"

        if any(
            x in text
            for x in [
                "sponsorship",
                "visa sponsorship",
                "require sponsorship",
            ]
        ):
            return "sponsorship"

        if any(
            x in text
            for x in [
                "relocate",
                "relocation",
                "willing to relocate",
            ]
        ):
            return "relocation"

        if any(
            x in text
            for x in [
                "date of birth",
                "dob",
                "birth date",
            ]
        ):
            return "date_of_birth"

        if any(
            x in text
            for x in [
                "gender",
                "sex",
            ]
        ):
            return "gender"

        if any(
            x in text
            for x in [
                "degree",
                "qualification",
                "education",
            ]
        ):
            return "degree"

        if any(
            x in text
            for x in [
                "college",
                "university",
                "institution",
            ]
        ):
            return "college"

        if any(
            x in text
            for x in [
                "graduation year",
                "passing year",
            ]
        ):
            return "graduation_year"

        if any(
            x in text
            for x in [
                "cgpa",
                "gpa",
                "percentage",
            ]
        ):
            return "cgpa"

        if any(
            x in text
            for x in [
                "ust",
                "past employment",
                "previous employment",
                "worked at",
            ]
        ):
            return "ust_employment"

        return "unknown"

    # ================================================================
    # CLASSIFICATION
    # ================================================================

    def _classify(
        self,
        name="",
        field_id="",
        field_type="",
        label="",
        placeholder="",
        aria_label="",
        tag="",
        role="",
        context="",
        options=None,
    ):
        name = "" if name is None else str(name)
        field_id = "" if field_id is None else str(field_id)
        field_type = "" if field_type is None else str(field_type)
        label = "" if label is None else str(label)
        placeholder = "" if placeholder is None else str(placeholder)
        aria_label = "" if aria_label is None else str(aria_label)
        tag = "" if tag is None else str(tag)

        strong = (
            f"{name} {field_id}"
            .lower()
            .replace("_", "")
            .replace("-", "")
            .replace(" ", "")
        )

        explicit_text = " ".join([label, aria_label, placeholder]).lower()
        if any(
            phrase in explicit_text
            for phrase in (
                "leave this field empty",
                "do not fill this field",
                "honeypot",
            )
        ):
            return "honeypot"
        if re.search(r"\bmiddle\s+name\b", explicit_text):
            return "unknown"
        if re.search(r"\bfirst\s+name\b", explicit_text):
            return "first_name"
        if re.search(r"\b(?:last|family)\s+name\b|\bsurname\b", explicit_text):
            return "last_name"
        if re.search(r"\b(?:full|candidate)\s+name\b", explicit_text):
            return "full_name"
        if re.fullmatch(r"\s*name\s*\*?\s*", label):
            return "full_name"
        if re.search(r"\benter\s+name\b", explicit_text):
            return "full_name"
        if re.search(r"\b(?:e[- ]?mail|email\s+id|email address)\b", explicit_text):
            return "email"
        if re.search(r"\b(?:phone|mobile(?:\s+(?:number|no))?|telephone|contact number|contact no)\b", explicit_text):
            return "phone"

        label_text = " ".join([label, placeholder, aria_label, name, field_id]).lower()

        # High-signal education labels must beat page-wide section context.
        # A form may place all education controls inside one parent whose text
        # contains "education", "degree", "college", and "cgpa". Using that
        # parent text for every control causes each input to be misclassified
        # as the degree field. Prefer the actual control label/metadata for
        # these fields and leave the rest of the classifier unchanged.
        explicit_label = str(label or "").strip().lower()
        explicit_meta = " ".join([explicit_label, str(aria_label or "").lower(), str(placeholder or "").lower()])
        if "highest qualification" in explicit_meta or "highest education" in explicit_meta or "educational qualification" in explicit_meta:
            return "degree"
        if any(x in explicit_meta for x in ("college / university", "college/university", "college name", "university name", "institution name")):
            return "college"
        if any(x in explicit_meta for x in ("cgpa / %", "cgpa/ %", "cgpa", "gpa", "percentage")):
            return "cgpa"
        if any(x in explicit_meta for x in ("graduation year", "year of graduation", "passing year")):
            return "graduation_year"
        if any(x in explicit_meta for x in ("current year of study", "year of study", "current year")):
            return "current_year_of_study"
        if "currently studying" in explicit_meta or "still pursuing this qualification" in explicit_meta:
            return "currently_studying"
        if any(x in explicit_meta for x in ("field / branch", "field/branch", "branch of study", "degree branch")):
            return "specialization"

        # High-signal semantic labels win over declared HTML type.  Many
        # real forms incorrectly mark Full Name as type=email, etc.
        # Explicit field identity must beat surrounding/question context.
        # A form can place an Age or Position control inside a container whose
        # text mentions First Name; never let that sibling/page context turn
        # the current control into first_name.
        if re.search(r"^age\s*[*:：-]?\s*$", explicit_meta):
            return "age"
        if re.search(r"^position\s*[*:：-]?\s*$", explicit_meta):
            return "job_role"
        if "full name" in label_text or "candidate name" in label_text:
            return "full_name"
        if (
            re.search(r"^(?:role|position)\s*[*:：-]?\s*$", explicit_meta)
            or name.strip().lower() in {"role", "position"}
            or field_id.strip().lower() in {"role", "position"}
            or any(
                x in label_text
                for x in (
                    "job role",
                    "role applying",
                    "position applying",
                    "position you are applying",
                    "role to which you want to apply",
                )
            )
        ):
            return "job_role"
        if any(x in label_text for x in ("when can you join", "joining date", "date you can join", "earliest joining date")):
            return "joining_date"
        if any(x in label_text for x in ("available in days", "days to join", "days until joining")):
            return "notice_period_days"
        if re.search(r"\b(address|street address|residential address|home address|current address)\b", label_text):
            return "address"
        if re.fullmatch(r"\s*(?:city|town|place|location|current city|current place|current location)\s*[*:：-]?\s*", explicit_meta):
            return "city"
        if re.search(r"\b(?:place of residence|current place|current location|current city)\b", label_text):
            return "city"
        if re.fullmatch(r"\s*contact\s*[*:：-]?\s*", explicit_meta):
            # Many external ATS forms use the bare label "Contact" for the
            # applicant phone field and omit useful input metadata. Prefer the
            # explicit field label over a generic/LLM interpretation.
            return "phone"
        if re.search(r"\b(bio|about yourself|about you|professional summary)\b", label_text):
            return "bio"
        if "country" in label_text:
            return "country"

        if "expmonths" in strong:
            return "experience_months"

        if "experiencemonths" in strong:
            return "experience_months"

        if "totalexperiencemonths" in strong:
            return "experience_months"

        if "expyears" in strong:
            return "experience_years"

        if "experienceyears" in strong:
            return "experience_years"

        if "totalexperienceyears" in strong:
            return "experience_years"

        if any(x in label_text for x in ("available to join", "can join", "joining availability")):
            return "available_to_join"
        if any(x in label_text for x in ("days to join", "available in days", "days until joining")):
            return "notice_period_days"
        if "country" in label_text:
            return "country"
        if any(x in label_text for x in ("address", "street address", "residential address")):
            return "address"

        if any(
            x in strong
            for x in [
                "currentcompany",
                "employer",
                "currentemployer",
            ]
        ):
            return "current_company"

        if any(
            x in strong
            for x in [
                "currentctc",
                "lastdrawnsalary",
                "currentsalary",
                "lastsalary",
            ]
        ):
            return "current_ctc"

        if any(
            x in strong
            for x in [
                "expectedctc",
                "expectedsalary",
            ]
        ):
            return "expected_ctc"

        if any(
            x in strong
            for x in [
                "noticeperiod",
                "notice",
            ]
        ):
            return "notice_period"

        if any(
            x in strong
            for x in [
                "preferredlocation1",
                "preferredcity1",
            ]
        ):
            return "preferred_location_1"

        if any(
            x in strong
            for x in [
                "preferredlocation2",
                "preferredcity2",
            ]
        ):
            return "preferred_location_2"

        if any(
            x in strong
            for x in [
                "preferredlocation3",
                "preferredcity3",
            ]
        ):
            return "preferred_location_3"

        if any(
            x in strong
            for x in [
                "ustemployment",
                "workedatust",
                "pastust",
            ]
        ):
            return "ust_employment"

        if any(
            x in strong
            for x in [
                "workauthorization",
                "legallyauthorized",
                "authorizedtowork",
            ]
        ):
            return "work_authorization"

        if any(
            x in strong
            for x in [
                "sponsorship",
                "requiresponsorship",
                "visasponsorship",
            ]
        ):
            return "sponsorship"

        if any(
            x in strong
            for x in [
                "relocation",
                "willingtorelocate",
            ]
        ):
            return "relocation"

        if any(
            x in strong
            for x in [
                "dateofbirth",
                "dob",
                "birthdate",
            ]
        ):
            return "date_of_birth"

        if "gender" in strong:
            return "gender"

        # A native experience <select> is deterministic. Keep it out of the
        # open-ended experience reasoner, even when its helper text says
        # "your experience".
        if tag.strip().lower() == "select" and (
            "experience" in label_text
            or "experiencelevel" in strong
            or "experience_level" in field_id.lower()
        ):
            return "experience"

        route = self.question_router.route(
            label=label, placeholder=placeholder, aria_label=aria_label,
            name=name, field_id=field_id, field_type=field_type, tag=tag,
            role=role, context=context, options=options,
        )
        if route["intent"] == "experience_years":
            return "experience_years"
        if route["intent"] in {
            "skill_experience_yes_no", "project_experience_yes_no",
            "experience_yes_no", "experience_text", "project_text", "open_text",
        }:
            # Reasoner-owned question: never fall through to a numeric
            # ``experience_years`` profile fact.
            return "unknown"

        if field_type == "file":
            return "resume"

        combined = " ".join(
            [
                context,
                label,
                placeholder,
                aria_label,
                name,
                field_id,
            ]
        )

        semantic = self._classify_text(
            combined
        )

        # Some ATS pages incorrectly declare unrelated inputs as type=email
        # (for example an "Age" or "Message" field). Page-wide context can
        # also contain the word "email", which must never override the field's
        # own label/metadata. Email is therefore allowed only when the control
        # itself explicitly signals that it is an email field.
        explicit_contact_meta = " ".join([label, placeholder, aria_label, name, field_id]).lower()
        explicit_email_signal = bool(
            re.search(
                r"\b(?:e[- ]?mail|email\s+id|email address)\b",
                explicit_contact_meta,
            )
            or re.search(r"(?:^|[_-])e?mail(?:$|[_-])", name.lower())
            or re.search(r"(?:^|[_-])e?mail(?:$|[_-])", field_id.lower())
        )
        narrative_signal = bool(
            re.search(
                r"\b(?:message|tell\s+us|about\s+(?:yourself|you)|relevant\s+experience|experience|summary|motivation|cover\s+letter|introduction|why\s+(?:do|are|should)|additional\s+information)\b",
                explicit_contact_meta,
            )
            or tag.strip().lower() == "textarea"
        )

        if semantic == "email" and not explicit_email_signal:
            return "message" if narrative_signal else "unknown"

        if semantic == "unknown" and field_type == "email":
            if explicit_email_signal:
                return "email"
            return "message" if narrative_signal else "unknown"

        if semantic == "unknown" and field_type == "tel":
            explicit_phone_signal = bool(
                re.search(
                    r"\b(?:phone|mobile(?:\s+(?:number|no))?|telephone|contact number|contact no)\b",
                    " ".join([label, placeholder, aria_label, name, field_id]).lower(),
                )
                or re.search(r"(?:^|[_-])(?:phone|mobile|tel)(?:$|[_-])", name.lower())
                or re.search(r"(?:^|[_-])(?:phone|mobile|tel)(?:$|[_-])", field_id.lower())
            )
            if explicit_phone_signal:
                return "phone"
            return "unknown"

        if field_type == "checkbox":
            if any(
                x in combined.lower()
                for x in [
                    "terms",
                    "privacy",
                    "agree",
                    "accept",
                ]
            ):
                return "terms"

        if field_type == "radio":
            return semantic

        if tag == "textarea":
            if semantic != "unknown":
                return semantic

            return "message"

        return semantic

    # ================================================================
    # FORM INSPECTION
    # ================================================================

    async def _derive_job_role(self):
        if self.profile.get("application_job_role"):
            return self.profile["application_job_role"]
        try:
            for selector in ("h1", "h2", "h3"):
                nodes = self.page.locator(selector)
                for i in range(min(await nodes.count(), 3)):
                    text = (await nodes.nth(i).inner_text()).strip()
                    if 2 <= len(text) <= 180:
                        self.profile["application_job_role"] = text
                        return text
        except Exception:
            pass
        try:
            title = (await self.page.title()).strip()
            if title:
                self.profile["application_job_role"] = re.split(r"\s+[|–-]\s+", title)[0].strip()
                return self.profile["application_job_role"]
        except Exception:
            pass
        return None

    async def inspect_form(self):
        if self.page is None:
            return []

        await self._derive_job_role()
        self.snapshot = await self.observer.snapshot(self.page)
        self.fields = []

        for metadata in self.snapshot:
            semantic = self._classify(
                name=metadata.get("name", ""),
                field_id=metadata.get("id", ""),
                field_type=metadata.get("type", ""),
                label=metadata.get("label", ""),
                placeholder=metadata.get("placeholder", ""),
                aria_label=metadata.get("aria_label", ""),
                tag=metadata.get("tag", ""),
                role=metadata.get("role", ""),
                context=metadata.get("question_context") or metadata.get("context", ""),
                options=metadata.get("options", []),
            )
            # Navigation/action controls are never application questions.
            # Keep the existing generic question-answer path intact for all
            # real fields, while preventing Back/Cancel/Next/Submit buttons
            # from being routed to ProfileReasoner.
            tag = str(metadata.get("tag") or "").lower()
            field_type = str(metadata.get("type") or "").lower()
            role = str(metadata.get("role") or "").lower()
            if tag == "button" or field_type in {"submit", "button", "reset", "image"} or role == "button":
                # A real button is an action control, never a user-answer field.
                # Do not depend on its label text: some ATS DOMs incorrectly
                # associate the previous form label with the button.
                continue

            metadata["semantic"] = semantic
            self.fields.append(metadata)

        print(f"form_inspected: fields={len(self.fields)} frames={len(set(x.get('scope_index', 0) for x in self.fields))}")
        return self.fields

    # ================================================================
    # VALUE HELPERS
    # ================================================================

    def _stringify(self, value):
        if value is None:
            return ""

        if isinstance(value, bool):
            return (
                "Yes"
                if value
                else "No"
            )

        return str(value)

    def _salary_value(self, value):
        if value is None:
            return ""

        try:
            number = int(
                float(
                    str(value).replace(",", "").strip()
                )
            )

            sign = "-" if number < 0 else ""
            digits = str(abs(number))

            if len(digits) <= 3:
                formatted = digits
            else:
                last_three = digits[-3:]
                rest = digits[:-3]
                groups = []

                while len(rest) > 2:
                    groups.insert(0, rest[-2:])
                    rest = rest[:-2]

                if rest:
                    groups.insert(0, rest)

                formatted = ",".join(
                    groups + [last_three]
                )

            return sign + formatted

        except Exception:
            return str(value)

    # ================================================================
    # TEXT FILL
    # ================================================================

    async def _fill_text(
        self,
        locator,
        value,
    ):
        value = self._stringify(
            value
        )

        ok = await self.widget_filler.safe_text(locator, value)
        if not ok:
            raise RuntimeError("text_fill_verification_failed")

    # ================================================================
    # SELECT
    # ================================================================

    async def _select_value(
        self,
        locator,
        value,
    ):
        """Select a native option with exact/semantic/range matching."""
        value = self._stringify(value).strip()
        if not value:
            return False
        try:
            options = await locator.locator("option").evaluate_all(
                "els => els.map(o => ({value:o.value, text:(o.innerText||o.textContent||'').trim(), disabled:o.disabled}))"
            )
        except Exception:
            options = []
        # Experience and notice-period values often use human labels instead
        # of the numeric profile value.  The adaptive matcher handles both.
        candidates = [value]
        normalized_degree = re.sub(r"[^a-z]+", " ", value.lower()).strip()
        if normalized_degree in {
            "b e b tech",
            "b tech b e",
        }:
            candidates.extend([
                "B.Tech / B.E.",
                "B.E. / B.Tech",
                "B.Tech/B.E.",
            ])

        for candidate in candidates:
            ok = await self.widget_filler.select_native(locator, candidate, options)
            if ok:
                return True

        print("select_option_not_matched: value=%r" % value)
        return False

    # ================================================================
    # TERMS
    # ================================================================

    async def _check_terms(self):
        if self.page is None:
            return False

        selectors = [
            "#termscondition",
            "input[name='termscondition']",
            "input[id*='termscondition' i]",
            "input[name*='terms' i]",
            "input[id*='terms' i]",
        ]

        for selector in selectors:
            try:
                boxes = self.page.locator(
                    selector
                )

                count = await boxes.count()

                for i in range(count):
                    box = boxes.nth(i)

                    try:
                        if await box.is_checked():
                            return True
                    except Exception:
                        pass

                    try:
                        await box.check(
                            force=True
                        )
                    except Exception:
                        pass

                    try:
                        if await box.is_checked():
                            return True
                    except Exception:
                        pass

                    try:
                        field_id = (
                            await box.get_attribute(
                                "id"
                            )
                        )

                        if field_id:
                            label = self.page.locator(
                                f"label[for='{field_id}']"
                            )

                            if await label.count():
                                await label.click(
                                    force=True
                                )

                                if await box.is_checked():
                                    return True

                    except Exception:
                        pass

            except Exception:
                continue

        try:
            boxes = self.page.locator(
                "input[type='checkbox']"
            )

            count = await boxes.count()

            for i in range(count):
                box = boxes.nth(i)

                context = ""

                try:
                    context = await box.evaluate(
                        """
                        el => {
                            const p = el.parentElement;
                            return p ? p.innerText : '';
                        }
                        """
                    )
                except Exception:
                    pass

                context_lower = (
                    context or ""
                ).lower()

                if any(
                    x in context_lower
                    for x in [
                        "terms",
                        "privacy",
                        "accept",
                        "agree",
                    ]
                ):
                    try:
                        await box.check(
                            force=True
                        )
                    except Exception:
                        try:
                            await box.click(
                                force=True
                            )
                        except Exception:
                            pass

                    try:
                        if await box.is_checked():
                            return True
                    except Exception:
                        pass

        except Exception:
            pass

        return False

    # ================================================================
    # RADIO
    # ================================================================

    async def _fill_radio(
        self,
        locator,
        value,
    ):
        """Select an answer from the semantic radio group, not the whole page."""
        if value is None or locator is None:
            return False

        wanted = self._stringify(value).lower().strip()
        scope = None
        try:
            scope = locator.locator(
                "xpath=ancestor::fieldset[1]"
            )
            if await scope.count() == 0:
                scope = locator.locator(
                    "xpath=ancestor::*[@role='radiogroup'][1]"
                )
            if await scope.count() == 0:
                scope = locator.locator(
                    "xpath=ancestor::*[@role='group'][1]"
                )
            if await scope.count() == 0:
                scope = locator.locator("xpath=..")
        except Exception:
            scope = None

        container = scope.first if scope is not None and await scope.count() else locator
        try:
            radios = container.locator("input[type='radio'], [role='radio']")
            count = await radios.count()
        except Exception:
            radios = locator
            count = 1

        for i in range(count):
            try:
                radio = radios.nth(i)
                radio_value = (await radio.get_attribute("value") or "").strip().lower()
                radio_id = (await radio.get_attribute("id") or "").strip().lower()
                aria = (await radio.get_attribute("aria-label") or "").strip().lower()
                label_text = ""
                rid = await radio.get_attribute("id")
                if rid:
                    labels = self.page.locator(f"label[for='{rid}']")
                    if await labels.count():
                        label_text = (await labels.first.inner_text()).strip().lower()
                own_text = ""
                try:
                    own_text = (await radio.inner_text()).strip().lower()
                except Exception:
                    pass
                candidates = (radio_value, radio_id, aria, label_text, own_text)
                if any(wanted == x or (x and (wanted in x or x in wanted)) for x in candidates):
                    try:
                        await radio.check(force=True)
                    except Exception:
                        await radio.click(force=True)
                    try:
                        return bool(await radio.is_checked())
                    except Exception:
                        return True
            except Exception:
                continue
        return False

    # ================================================================
    # FIELD FILL
    # ================================================================

    def _parse_dob(self, value):
        """Parse common DOB formats into day/month/year."""
        if value in (None, ""):
            return None

        text = str(value).strip()

        # YYYY-MM-DD / YYYY/MM/DD
        m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
        if m:
            year, month, day = m.groups()
            return {
                "day": str(int(day)),
                "month": str(int(month)),
                "year": year,
            }

        # DD-MM-YYYY / DD/MM/YYYY
        m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", text)
        if m:
            day, month, year = m.groups()
            return {
                "day": str(int(day)),
                "month": str(int(month)),
                "year": year,
            }

        # DD-April-YYYY / DD April YYYY
        m = re.fullmatch(
            r"(\d{1,2})[-/\s]+([A-Za-z]+)[-/\s]+(\d{4})",
            text,
        )
        if m:
            day, month, year = m.groups()
            return {
                "day": str(int(day)),
                "month": month,
                "year": year,
            }

        return None

    def _dob_component(self, field, dob):
        """Determine whether this DOB select is day, month, or year."""
        if not dob:
            return None

        text = " ".join(
            str(field.get(key) or "")
            for key in (
                "name",
                "id",
                "label",
                "placeholder",
                "aria_label",
            )
        ).lower()

        if "year" in text:
            return dob["year"]

        if "month" in text:
            return dob["month"]

        if "day" in text:
            return dob["day"]

        # Some ATSes call the day dropdown "date".
        if "date" in text and "birth" in text:
            return dob["day"]

        return None

    async def _fill_dob_select(self, field, dob):
        """Fill one DOB dropdown using its actual option value/text."""
        component = self._dob_component(field, dob)

        if component is None:
            return False

        locator = field.get("locator")
        if locator is None:
            return False

        options = locator.locator("option")
        count = await options.count()

        wanted = str(component).strip().lower()

        months = {
            "1": "january", "01": "january", "jan": "january", "january": "january",
            "2": "february", "02": "feb", "feb": "february", "february": "february",
            "3": "march", "03": "march", "mar": "march", "march": "march",
            "4": "april", "04": "april", "apr": "april", "april": "april",
            "5": "may", "05": "may",
            "6": "june", "06": "june", "jun": "june", "june": "june",
            "7": "july", "07": "july", "jul": "july", "july": "july",
            "8": "august", "08": "aug", "august": "august",
            "9": "september", "09": "sep", "september": "september",
            "10": "october", "oct": "october",
            "11": "november", "nov": "november",
            "12": "december", "dec": "december",
        }

        wanted_month = months.get(wanted, wanted)

        selected_value = None

        for i in range(count):
            option = options.nth(i)
            option_text = (
                await option.inner_text()
            ).strip().lower()
            option_value = (
                await option.get_attribute("value")
                or ""
            ).strip().lower()

            if (
                option_text == wanted
                or option_value == wanted
            ):
                selected_value = (
                    await option.get_attribute("value")
                    or option_text
                )
                break

            if "month" in " ".join(
                str(field.get(key) or "")
                for key in ("name", "id", "label", "placeholder")
            ).lower():
                if (
                    months.get(option_text) == wanted_month
                    or months.get(option_value) == wanted_month
                ):
                    selected_value = (
                        await option.get_attribute("value")
                        or option_text
                    )
                    break

        if selected_value is None:
            await self._record(
                "select_option_not_matched",
                semantic="date_of_birth",
                value=component,
            )
            return False

        try:
            await locator.select_option(
                value=selected_value,
                timeout=3000,
            )
            return True
        except Exception:
            try:
                await locator.select_option(
                    label=selected_value,
                    timeout=3000,
                )
                return True
            except Exception:
                return False

    def _custom_answer(self, field):
        try:
            from custom_qa_store import find_custom_answer
        except Exception:
            return None

        candidates = []
        for key in (
            "label",
            "question_context",
            "placeholder",
            "aria_label",
            "name",
            "id",
            "context",
        ):
            value = str(field.get(key) or "").strip()
            if value and value not in candidates:
                candidates.append(value)

        options = []
        for item in field.get("options") or []:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            text = str(text).strip()
            if text and text not in options:
                options.append(text)

        best = None
        for question in candidates:
            try:
                custom_answer = find_custom_answer(question, options=options or None, exact_only=True)
            except Exception:
                continue
            result = custom_answer
            if result and (best is None or float(result.get("score", 0)) > float(best.get("score", 0))):
                best = result
        return best

    async def _fill_field(
        self,
        field,
    ):
        semantic = field.get(
            "semantic"
        )

        locator = field.get(
            "locator"
        )

        tag = field.get(
            "tag"
        )

        field_type = field.get(
            "type",
            "",
        )

        # Deterministic profile-backed values are authoritative. Saved Custom
        # Q&A is consulted only when the profile cannot answer the field.
        deterministic_value = self.get_profile_value(semantic)
        custom_answer = None
        if deterministic_value in (None, ""):
            custom = self._custom_answer(field)
            custom_answer = custom.get("answer") if custom else None

        # Keep structural controls protected, but allow Custom Q&A to fill
        # otherwise-unknown company-specific text/select/radio questions.
        if semantic in self.SKIP_FIELDS and deterministic_value in (None, "") and custom_answer in (None, ""):
            return False

        if semantic == "terms" and deterministic_value in (None, "") and custom_answer in (None, ""):
            return False

        # DOB is represented by separate Day / Month / Year selects.
        # Keep every other field path unchanged.
        if (
            semantic == "date_of_birth"
            and tag == "select"
        ):
            dob = self.get_profile_value(
                "date_of_birth"
            )

            if not dob:
                return False

            parsed = self._parse_dob(dob)

            if not parsed:
                return False

            return await self._fill_dob_select(
                field,
                parsed,
            )

        value = deterministic_value if deterministic_value not in (None, "") else custom_answer

        if value is None or value == "":
            return False

        if field_type == "checkbox":
            if semantic == "currently_studying" and bool(value):
                try:
                    await locator.check(force=True)
                    return await locator.is_checked()
                except Exception:
                    return False
            return False

        if field_type == "radio":
            return await self._fill_radio(
                locator,
                value,
            )

        if tag == "select":
            return await self._select_value(
                locator,
                value,
            )

        if field.get("role") == "combobox" or field_type == "combobox":
            scope = field.get("scope") or self.page
            return await self.widget_filler.select_custom(scope, locator, value)

        if semantic == "experience_years":
            value = int(value)

        if semantic == "experience_months":
            value = int(value)

        if semantic in [
            "current_ctc",
            "expected_ctc",
        ]:
            value = self._salary_value(
                value
            )

        try:
            await self._fill_text(
                locator,
                value,
            )

            return True

        except Exception:
            return False

    # ================================================================
    # RESUME
    # ================================================================

    def get_resume_path(self):
        configured = self._get_nested(
            "documents.resume",
            "resume.path",
            default=None,
        )

        project_root = (
            Path(__file__)
            .resolve()
            .parents[3]
        )

        candidates = []

        if configured:
            configured_path = Path(
                str(configured)
            )

            if configured_path.is_absolute():
                candidates.append(
                    configured_path
                )
            else:
                candidates.append(
                    project_root
                    / configured_path
                )

        candidates.append(
            project_root
            / "resume"
            / "resume.pdf"
        )

        candidates.append(
            Path.cwd()
            / "resume"
            / "resume.pdf"
        )

        for path in candidates:
            if path.exists():
                return str(
                    path.resolve()
                )

        return None

    async def upload_resume(self):
        if self.page is None:
            return False

        resume_path = (
            self.get_resume_path()
        )

        if not resume_path:
            print(
                "resume_not_found"
            )

            return False

        selectors = [
            "input[type='file']",
            "input[name*='resume' i]",
            "input[id*='resume' i]",
            "input[name*='cv' i]",
            "input[id*='cv' i]",
        ]

        for selector in selectors:
            try:
                files = self.page.locator(
                    selector
                )

                count = await files.count()

                for i in range(count):
                    field = files.nth(i)

                    try:
                        await field.set_input_files(
                            resume_path
                        )

                        self.resume_uploaded = True

                        print(
                            "resume_uploaded: "
                            f"{resume_path}"
                        )

                        return True

                    except Exception:
                        continue

            except Exception:
                continue

        print(
            "resume_upload_failed"
        )

        return False

    # ================================================================
    # SAFE FILL
    # ================================================================

    def _get_reasoner(self):
        if self.reasoner is not None:
            return self.reasoner
        try:
            from profile_reasoner import ProfileReasoner
            self.reasoner = ProfileReasoner(base_dir=Path(__file__).resolve().parents[3])
        except Exception:
            try:
                from common.profile_reasoner import ProfileReasoner
                self.reasoner = ProfileReasoner(base_dir=Path(__file__).resolve().parents[3])
            except Exception:
                self.reasoner = False
        return self.reasoner

    async def _reason_and_fill(self, field):
        reasoner = self._get_reasoner()
        if not reasoner:
            return False
        # Prefer the visible field label over helper/context text.
        # Saved Custom Q&A entries normally use the field label, while helper
        # text can contain generic words such as "experience" or "projects"
        # that cause false fuzzy matches.
        question = (
            field.get("label")
            or field.get("question_context")
            or field.get("placeholder")
            or field.get("aria_label")
            or field.get("context")
        )
        options = [x.get("text", "") if isinstance(x, dict) else str(x) for x in field.get("options", []) if x]
        if not question:
            return False

        # Never let a generic model answer identity-like filler into a short
        # geography/contact field.  External ATS forms commonly use labels
        # such as "Address", "Place", "Location", or "Contact".  If the
        # requested profile fact is not actually present, leave it unresolved
        # instead of guessing a name such as "Anuroop".
        qn = re.sub(r"\s+", " ", str(question).strip().lower())
        # Normalize trailing field markers such as `*` before applying the
        # short-field safety checks.  Oracle-style forms frequently render
        # labels as `Current Location *` or `Role:`.
        qn = re.sub(r"[\s*:：\-]+$", "", qn)
        protected_geo = bool(re.fullmatch(
            r"(?:address|street address|residential address|home address|current address|place|location|city|town|current place|current location|current city|role|position|job role|current role)",
            qn,
        ))
        protected_contact = bool(re.fullmatch(r"(?:contact|contact person|contact name)", qn))
        if field.get("semantic") == "address" and self.get_profile_value("address") in (None, ""):
            return False
        if field.get("semantic") == "city" and self.get_profile_value("city") in (None, ""):
            return False
        if protected_geo and field.get("semantic") in {None, "", "unknown"}:
            return False
        if protected_contact and field.get("semantic") in {None, "", "unknown"}:
            return False

        try:
            context = {
                "job_role": self.profile.get("application_job_role"),
                "field_semantic": field.get("semantic"),
                "widget": field.get("role") or field.get("type") or field.get("tag"),
                "question_context": field.get("question_context"),
                "local_context": field.get("context"),
            }
            result = await asyncio.to_thread(reasoner.reason, question, options, context)
        except Exception as exc:
            print(f"reasoner_error: {type(exc).__name__}: {exc}")
            return False
        if not isinstance(result, dict):
            return False
        confidence = float(result.get("confidence") or 0)
        answer = result.get("answer")
        selected = result.get("selected_options") or []
        if confidence < 0.65 or answer in (None, ""):
            return False

        # A single-line input is not a safe destination for an open-ended
        # paragraph.  Keep the generic reasoner available for legitimate
        # short answers, but reject an obviously narrative-sized answer before
        # it can contaminate a short field such as location or role.
        is_long_form = str(field.get("tag") or "").lower() == "textarea"
        if not is_long_form and len(str(answer)) > 150:
            print(
                "reasoned_answer_rejected_too_long_for_single_line: "
                f"question={question!r}"
            )
            return False

        # Final defense-in-depth: never write a profile email into an unrelated
        # field, including stale Custom Q&A results.
        if field.get("semantic") != "email":
            answer_text = str(answer)
            if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", answer_text, flags=re.I):
                print(
                    "reasoned_answer_rejected_contact_leak: "
                    f"semantic={field.get('semantic')!r} question={question!r}"
                )
                return False
        try:
            if field.get("tag") == "select":
                ok = await self._select_value(field["locator"], selected[0] if selected else answer)
            elif field.get("role") == "combobox":
                scope = field.get("scope") or self.page
                ok = await self.widget_filler.select_custom(scope, field["locator"], selected[0] if selected else answer)
            else:
                ok = await self._fill_text(field["locator"], answer)
            if ok is not False:
                self.fallback_fields_filled += 1
                self.total_fields_filled += 1
                print(f"reasoned_field_filled: semantic={field.get('semantic')!r} confidence={confidence:.2f}")
                return True
        except Exception as exc:
            print(f"reasoned_field_fill_error: {exc}")
        return False

    async def fill_safe_fields(self):
        if self.page is None:
            return {
                "fields_filled": 0,
                "resume_uploaded": False,
            }

        if not self.fields:
            await self.inspect_form()

        filled = 0

        for field in self.fields:
            semantic = field.get(
                "semantic"
            )

            # Never fill a generic/full-name field.
            # The ATS may have separate First/Middle/Last fields.
            if semantic == "full_name":
                continue

            if semantic in [
                "unknown",
                "honeypot",
                "choice",
                "submit",
                "date",
                "time",
            ]:
                # Unknown free-text questions are handled below by the
                # profile-grounded reasoner when possible.
                if semantic != "unknown":
                    continue

            if semantic == "terms":
                continue

            if semantic in {"unknown", "message", "cover_letter", "bio"}:
                if await self._reason_and_fill(field):
                    filled += 1
                    continue
                if semantic == "unknown":
                    continue

            try:
                success = await self._fill_field(
                    field
                )

                if success:
                    filled += 1

                    self.ai_fields_filled += 1
                    self.total_fields_filled += 1

                    print(
                        "field_filled: "
                        f"semantic='{semantic}'"
                    )

            except Exception as exc:
                print(
                    "field_fill_error: "
                    f"semantic='{semantic}' "
                    f"error={exc}"
                )

        resume = False
        if self.enable_resume_upload:
            resume = await self.upload_resume()

        self.fields_filled = (
            self.total_fields_filled
        )

        print(
            "ai_form_engine_complete: "
            f"fields_filled={filled} "
            f"resume_uploaded={resume}"
        )

        return {
            "fields_filled": filled,
            "resume_uploaded": resume,
        }

    # ================================================================
    # FIELD VERIFICATION
    # ================================================================

    async def verify_field(
        self,
        field,
    ):
        semantic = field.get(
            "semantic"
        )

        locator = field.get(
            "locator"
        )

        if semantic in [
            "unknown",
            "submit",
            "terms",
            "full_name",
        ]:
            return None

        expected = self.get_profile_value(
            semantic
        )

        if expected is None:
            return None

        try:
            tag = field.get(
                "tag"
            )

            field_type = field.get(
                "type",
                "",
            )

            if field_type == "checkbox":
                actual = await locator.is_checked()

                if isinstance(
                    expected,
                    bool,
                ):
                    return (
                        actual
                        == expected
                    )

                return actual

            if field_type == "radio":
                return await locator.is_checked()

            if tag == "select":
                actual = await locator.input_value()

                expected_text = (
                    self._stringify(
                        expected
                    )
                    .lower()
                    .strip()
                )

                if (
                    actual.lower().strip()
                    == expected_text
                ):
                    return True

                options = locator.locator(
                    "option:checked"
                )

                if await options.count():
                    text = (
                        await options.first.inner_text()
                    ).lower().strip()

                    return (
                        text
                        == expected_text
                    )

                return False

            actual = await locator.input_value()

            expected_text = (
                self._stringify(
                    expected
                ).strip()
            )

            return (
                actual.strip()
                == expected_text
            )

        except Exception:
            return False

    async def verify_filled_fields(self):
        if not self.fields:
            await self.inspect_form()

        verified = []
        failed = []

        for field in self.fields:
            semantic = field.get(
                "semantic"
            )

            if semantic in [
                "unknown",
                "submit",
                "terms",
                "resume",
                "message",
                "cover_letter",
                "date",
                "time",
                "full_name",
            ]:
                continue

            expected = self.get_profile_value(
                semantic
            )

            if expected is None:
                continue

            result = await self.verify_field(
                field
            )

            if result is True:
                verified.append(
                    semantic
                )

            elif result is False:
                failed.append(
                    semantic
                )

        print(
            "field_verification: "
            f"verified={len(verified)} "
            f"failed={len(failed)}"
        )

        if failed:
            print(
                "field_verification_failed: "
                + ", ".join(failed)
            )

        return {
            "verified": verified,
            "failed": failed,
        }

    # ================================================================
    # REQUIRED FIELDS
    # ================================================================

    async def get_required_unfilled_fields(
        self,
    ):
        if not self.fields:
            await self.inspect_form()

        unresolved = []

        for field in self.fields:
            locator = field.get(
                "locator"
            )

            semantic = field.get(
                "semantic"
            )

            try:
                required = (
                    await locator.get_attribute(
                        "required"
                    )
                )
            except Exception:
                required = None

            if not required:
                continue

            if semantic in [
                "submit",
                "unknown",
            ]:
                unresolved.append(
                    semantic
                    or "unknown"
                )

                continue

            if semantic == "full_name":
                continue

            expected = self.get_profile_value(
                semantic
            )

            if expected is None:
                unresolved.append(
                    semantic
                )

                continue

            result = await self.verify_field(
                field
            )

            if result is not True:
                unresolved.append(
                    semantic
                )

        return list(
            dict.fromkeys(
                unresolved
            )
        )

    # ================================================================
    # COMPLETE SAFE FORM FLOW
    # ================================================================

    async def fill_form_safely(self):
        await self.inspect_form()

        result = await self.fill_safe_fields()

        await self.inspect_form()

        verification = (
            await self.verify_filled_fields()
        )

        terms_accepted = (
            await self._check_terms()
        )

        unresolved = (
            await self.get_required_unfilled_fields()
        )

        self.fields_filled = (
            self.total_fields_filled
        )

        return {
            "fields_filled": self.total_fields_filled,
            "ai_fields_filled": self.ai_fields_filled,
            "fallback_fields_filled": self.fallback_fields_filled,
            "resume_uploaded": self.resume_uploaded,
            "terms_accepted": terms_accepted,
            "verified": verification,
            "unresolved_required_fields": unresolved,
        }
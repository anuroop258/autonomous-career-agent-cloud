import json, os, re, time, urllib.request, urllib.error
from pathlib import Path
from custom_qa_store import find_custom_answer
from src.application.common.question_router import QuestionIntentRouter


def _diag_reason_result(result):
    if not isinstance(result, dict):
        return result
    return {
        "answer": result.get("answer"),
        "field": result.get("field"),
        "kind": result.get("kind"),
        "confidence": result.get("confidence"),
    }

class ProfileReasoner:
    """
    Profile-grounded question reasoner.

    Priority:
      1) Deterministic profile facts.
      2) Gemini reasoning when configured.
      3) Ollama local-model fallback when available.
      4) OpenAI reasoning when configured (compatibility).
      5) Conservative local semantic reasoning otherwise.

    The model is explicitly forbidden from inventing facts or professional
    experience. It receives the complete profile and the visible options.
    """

    def __init__(self, base_dir=None):
        # A single reasoner implementation is shared by all platform
        # adapters.  Callers may explicitly supply a profile directory, but
        # the project profile remains the safe default.
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent
        self._load_gemini_environment()
        self.profile = json.loads((self.base_dir / "profile.json").read_text(encoding="utf-8"))
        # Secrets are intentionally process configuration, never project files.
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if self._is_placeholder_key(self.gemini_key):
            # .env.example ships a placeholder; treat it as "not configured"
            # instead of burning a request (and a timeout) on every question.
            self.gemini_key = ""
        enable_setting = os.getenv("ENABLE_GEMINI")
        self.gemini_enabled = True if enable_setting is None else enable_setting.strip().lower() in {"1","true","yes","on"}
        # Match the known-working desktop Gemini chatbot default. Override via GEMINI_MODEL.
        self.gemini_model = os.getenv(
            "GEMINI_MODEL", "gemini-3.5-flash-lite"
        ).strip()
        self._gemini_client = None
        # Set when Gemini can never succeed this session (bad key, missing SDK,
        # unknown model) so later questions skip it instead of stalling.
        self._gemini_disabled_reason = None
        self._gemini_cache = {}
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
        self.ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat").strip()
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip()
        self.ollama_enabled = os.getenv("OLLAMA_ENABLED", "0").strip().lower() in {"1","true","yes","on"}
        self.timeout = int(os.getenv("GEMINI_TIMEOUT", os.getenv("OPENAI_TIMEOUT", os.getenv("OLLAMA_TIMEOUT", "20"))))
        self.model_retries = min(1, max(0, int(os.getenv("MODEL_RETRIES", "1"))))
        self.retry_backoff_seconds = max(0.1, float(os.getenv("MODEL_RETRY_BACKOFF", "1.0")))

    def _load_gemini_environment(self):
        """Load the same .env-style configuration used by the working Gemini chatbot.

        Priority is process environment first, then an explicitly supplied env file,
        then the project .env, then a sibling gemini_chatbot/.env. Existing process
        variables are never overwritten.
        """
        candidates = []
        explicit = os.getenv("GEMINI_ENV_FILE", "").strip()
        if explicit:
            candidates.append(Path(explicit).expanduser())
        candidates.extend([
            self.base_dir / ".env",
            self.base_dir.parent / "gemini_chatbot" / ".env",
            Path.cwd() / ".env",
            Path.cwd() / "gemini_chatbot" / ".env",
        ])
        try:
            from dotenv import load_dotenv
        except Exception:
            load_dotenv = None
        if load_dotenv is not None:
            seen = set()
            for path in candidates:
                try:
                    path = path.resolve()
                except Exception:
                    pass
                key = str(path)
                if key in seen or not path.is_file():
                    continue
                seen.add(key)
                load_dotenv(path, override=False)

    @staticmethod
    def _is_placeholder_key(key):
        k = str(key or "").strip().lower()
        return (not k) or k.startswith(("paste_", "your_", "changeme")) or "paste_your" in k or k in {"none", "null", "xxx"}

    def _gemini_available(self):
        return bool(self.gemini_key and self.gemini_enabled and not self._gemini_disabled_reason)

    def _generation_task(self, question, context=None):
        """Classify answer-as-writing tasks that should be generated from profile facts.

        These are not missing profile fields.  They are application-writing tasks
        such as a headline, summary, cover letter, motivation, or an open-ended
        recruiter prompt.  They deliberately route to Gemini after deterministic
        facts/custom Q&A have had their chance.
        """
        q = self._norm(question)
        ctx = context if isinstance(context, dict) else {}
        semantic = self._norm(ctx.get("field_semantic"))
        widget = self._norm(ctx.get("widget"))

        headline_markers = (
            "headline", "professional headline", "profile headline",
        )
        if semantic in {"headline", "professional_headline", "job_headline"} or any(m in q for m in headline_markers):
            return "professional_headline"

        summary_markers = (
            "summary", "professional summary", "profile summary",
            "career summary", "about yourself", "tell us about yourself",
            "about me", "introduction", "self introduction",
        )
        if semantic in {"summary", "professional_summary", "about", "bio", "introduction"} or any(m in q for m in summary_markers):
            return "professional_summary"

        cover_markers = (
            "cover letter", "coverletter", "cover note", "application letter",
        )
        if semantic in {"cover_letter", "coverletter"} or any(m in q for m in cover_markers):
            return "cover_letter"

        # Duration/years-of-experience questions are factual screening questions,
        # not generic open-ended writing prompts. Route them separately so a
        # question such as "How much experience do you have in Deep Learning?"
        # cannot receive a generic profile-summary answer.
        duration_patterns = (
            r"\bhow much experience do you have in\b",
            r"\bhow many years of experience do you have in\b",
            r"\bhow many years experience do you have in\b",
            r"\b(?:years|year) of experience in\b",
            r"\bexperience in [a-z0-9+#.\- ]+$",
        )
        if any(re.search(pattern, q) for pattern in duration_patterns):
            return "skill_experience_years"

        motivation_markers = (
            "why this role", "why do you want this role", "why do you want to join",
            "why are you interested", "what interests you", "motivation for",
            "why should we hire you", "what makes you a good fit",
            "what can you bring", "what value can you add",
            "career objective", "professional objective",
            "strengths", "key strengths", "tell us about your experience",
            "relevant experience", "relevant background",
        )
        if semantic in {"motivation", "strengths", "relevant_experience", "career_objective", "professional_objective", "message"} or any(m in q for m in motivation_markers):
            return "open_ended_application_response"

        # A free-text/textarea field with no selectable options is an application
        # writing surface.  Give Gemini permission to synthesize a truthful answer
        # from the profile instead of treating it like a missing fact.
        if not self._clean_options(ctx.get("visible_options", [])) and (
            widget in {"textarea", "textbox", "text", "input"}
            or semantic in {"unknown", "text", "textarea", "textbox"}
        ) and q:
            return "open_ended_application_response"

        return None

    def _gemini_cache_key(self, question, options, context):
        role = (context or {}).get("job_role") if isinstance(context, dict) else None
        task = self._generation_task(question, context=context)
        company = (context or {}).get("company") if isinstance(context, dict) else None
        return (self._norm(question), tuple(self._norm(o) for o in options), self._norm(role), task or "", self._norm(company))

    def reason(self, question, options, context=None):
        question = self._clean(question)
        options = self._clean_options(options)
        print(f"  DIAG ProfileReasoner.reason normalized_question={self._norm(question)!r}")

        if not question:
            print("  DIAG ProfileReasoner.reason returned=None empty_question")
            return None

        # Route the semantic question before fuzzy Custom Q&A.  The router is
        # authoritative for well-defined categories such as project-description,
        # experience-years, and yes/no experience questions.
        try:
            route = QuestionIntentRouter.route(label=question, options=options)
        except Exception:
            route = {"intent": "unknown", "confidence": 0.0}

        # Deterministic profile facts must win over any saved Q&A answer.
        # This prevents a transient model/JSON failure from dropping simple
        # fields such as graduation year, CTC, or experience years.
        local = self._local_reason(question, options)
        if local is not None and local.get("confidence", 0) >= 0.9:
            print(f"  DIAG ProfileReasoner.reason returned_local={_diag_reason_result(local)!r}")
            return local

        # Exact user-authored Q&A is the first fallback only after the
        # deterministic profile cannot answer confidently.
        try:
            exact_custom = find_custom_answer(question, options, exact_only=True)
            if exact_custom is not None:
                answer = exact_custom["answer"]
                kind = "yes_no" if str(answer).strip().lower() in {"yes", "no"} else "text"
                print(f"  CUSTOM Q&A EXACT FALLBACK: score={exact_custom['score']:.3f} source={exact_custom['question']!r} answer={answer!r}")
                return {"answer": answer, "field": "custom_qa", "kind": kind, "confidence": 1.0}
        except Exception as exc:
            print(f"  CUSTOM Q&A WARNING: {type(exc).__name__}: {exc}")

        # Fuzzy Custom Q&A is a fallback for questions without a stronger
        # semantic owner.  Never let it override project/experience routing.
        if route.get("intent") == "unknown":
            try:
                fuzzy_custom = find_custom_answer(question, options)
                if fuzzy_custom is not None:
                    answer = fuzzy_custom["answer"]
                    kind = "yes_no" if str(answer).strip().lower() in {"yes", "no"} else "text"
                    print(f"  CUSTOM Q&A FUZZY MATCH: score={fuzzy_custom['score']:.3f} source={fuzzy_custom['question']!r} answer={answer!r}")
                    return {"answer": answer, "field": "custom_qa", "kind": kind, "confidence": 0.98}
            except Exception as exc:
                print(f"  CUSTOM Q&A WARNING: {type(exc).__name__}: {exc}")

        if self._gemini_available():
            cache_key = self._gemini_cache_key(question, options, context)
            if cache_key in self._gemini_cache:
                cached = self._gemini_cache[cache_key]
                print("  Gemini QA: using cached answer for repeated question")
                return dict(cached)
            try:
                print(f"  Gemini QA: unresolved question, asking {self.gemini_model}")
                try:
                    result = self._gemini_reason(question, options, context=context)
                except TypeError as exc:
                    if "unexpected keyword argument 'context'" in str(exc):
                        result = self._gemini_reason(question, options)
                    else:
                        raise
                if result:
                    validated = self._validate(result, question, options)
                    if validated is not None:
                        print(f"  Gemini QA: answered {_diag_reason_result(validated)!r}")
                        self._gemini_cache[cache_key] = dict(validated)
                        return validated
                    print("  Gemini QA: response rejected by answer validation; trying Ollama/local fallback")
                else:
                    print("  Gemini QA: no usable answer returned (null/empty); trying fallbacks")
            except Exception as e:
                print(
                    "  DIAG ProfileReasoner.reason provider_exception "
                    f"provider=Gemini question={question!r} type={type(e).__name__} error={e}"
                )
                print(f"  Gemini QA fallback: {type(e).__name__}: {e}")
                self._maybe_disable_gemini(e)

        # Local Ollama fallback is deliberately after Gemini and before OpenAI.
        # It is useful when Gemini returns malformed JSON, times out, or is
        # temporarily unavailable. A failed Ollama request must never stop the
        # normal application flow.
        if self.ollama_enabled:
            try:
                try:
                    result = self._ollama_reason(question, options, context=context)
                except TypeError as exc:
                    if "unexpected keyword argument 'context'" in str(exc):
                        result = self._ollama_reason(question, options)
                    else:
                        raise
                if result:
                    validated = self._validate(result, question, options)
                    if validated is not None:
                        return validated
            except Exception as e:
                print(
                    "  DIAG ProfileReasoner.reason provider_exception "
                    f"provider=Ollama question={question!r} type={type(e).__name__} error={e}"
                )
                print(f"  Ollama QA fallback: {type(e).__name__}: {e}")

        if self.openai_key:
            try:
                try:
                    result = self._openai_reason(question, options, context=context)
                except TypeError as exc:
                    if "unexpected keyword argument 'context'" in str(exc):
                        result = self._openai_reason(question, options)
                    else:
                        raise
                if result:
                    validated = self._validate(result, question, options)
                    if validated is not None:
                        return validated
            except Exception as e:
                print(
                    "  DIAG ProfileReasoner.reason provider_exception "
                    f"provider=OpenAI question={question!r} type={type(e).__name__} error={e}"
                )
                print(f"  OpenAI QA fallback: {type(e).__name__}: {e}")

        result = self._local_reason(question, options)
        print(f"  DIAG ProfileReasoner.reason returned_final_local={_diag_reason_result(result)!r}")
        return result

    def _prompt(self, question, options, context=None):
        profile = self._public_profile()
        schema = {
            "answer": "string or number or null",
            "kind": "text|number|yes_no|single_select|multi_select|unknown",
            "selected_options": ["only exact visible option labels"],
            "field": "short semantic profile field or null",
            "confidence": 0.0
        }
        generation_task = self._generation_task(question, context=context)
        task_instruction = ""
        if generation_task == "professional_headline":
            task_instruction = (
                "TASK: Generate a professional application headline from the supplied profile facts. "
                "Return one concise headline only, maximum 127 characters, suitable for a job application. "
                "Do not use first-person pronouns and do not claim professional experience that is not in the profile."
            )
        elif generation_task == "professional_summary":
            task_instruction = (
                "TASK: Generate a concise professional summary from the supplied profile facts. "
                "Use 2-4 sentences, first person, emphasizing education, relevant skills and project/hands-on work. "
                "State fresher status accurately when relevant and never invent employment."
            )
        elif generation_task == "cover_letter":
            task_instruction = (
                "TASK: Generate a concise job-application cover letter from the supplied profile facts and application context. "
                "Use first person, keep it professional and specific to the role/context, and rely only on supported facts. "
                "Do not invent an employer, employment history, achievements, or experience years."
            )
        elif generation_task == "skill_experience_years":
            task_instruction = (
                "TASK: Answer an explicit skill-duration question. Return only the candidate's professional experience duration for the requested skill. "
                "Never turn a general skills/profile summary into an experience answer. If the profile has no explicit skill-specific professional duration, "
                "use the candidate's documented professional experience (0 years for this fresher) rather than inventing a number."
            )
        elif generation_task == "open_ended_application_response":
            task_instruction = (
                "TASK: Generate a concise first-person application response to this open-ended question. "
                "Use only supported profile facts and relevant project/hands-on experience. "
                "Do not invent professional employment, years, achievements, or contact details."
            )

        system = """You are a truthful job-application form answering engine.
Use ONLY the candidate profile supplied below. Reason about the meaning of a new question instead of requiring a pre-written question mapping.

Rules:
- Never invent experience, employers, achievements, certifications, dates, salary, skills, or personal facts.
- Professional/industry experience is distinct from project/academic/personal hands-on experience. This candidate is a fresher with 0 professional years.
- Treat skill-existence/hands-on yes/no questions differently from numeric years-of-experience questions.
- If a question asks about a skill and the skill exists in the profile, project or hands-on familiarity may support Yes, but never convert that into professional years.
- For years of professional or skill experience, use the profile's explicit years.
- For yes/no, return Yes or No only when the profile supports it. Otherwise null.
- For multiple choice, select only exact visible option labels supported by the profile. Never answer a multi-select question with generic Yes/No.
- For ordinary open-ended application questions, write concise first-person text built ONLY from facts in the profile and application_context.
- For known writing tasks such as headline, summary, cover letter, motivation, strengths, and open-ended application responses, synthesize wording from supported facts instead of returning null merely because there is no pre-written profile field.
- If no truthful answer can be established, return null.
- NEVER use the candidate's email address, phone number, or other contact details as an answer to an unrelated question. Return null instead. Only return contact details when the question explicitly asks for that contact field.
- If options are present, do not invent labels; selected_options must be copied exactly from the options.
- Output JSON only, matching this schema:
""" + json.dumps(schema, ensure_ascii=False)
        if task_instruction:
            system += "\n\n" + task_instruction
        user = {
            "candidate_profile": profile,
            "question": question,
            "visible_options": options,
            "application_context": context or {},
            "generation_task": generation_task,
        }
        return system, json.dumps(user, ensure_ascii=False)

    def _gemini_reason(self, question, options, context=None):
        """Use the same google-genai SDK pattern as the working desktop chatbot.

        A fresh chat is created for each form question so one employer question
        cannot contaminate the next one. The existing profile-grounded prompt
        and strict answer validation remain authoritative.
        """
        if not self.gemini_key:
            return None

        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise RuntimeError(
                "google-genai is required for Gemini reasoning. Install requirements.txt."
            ) from exc

        if self._gemini_client is None:
            client_kwargs = {"api_key": self.gemini_key}
            if hasattr(types, "HttpOptions"):
                # Bound every request; GEMINI_TIMEOUT was previously ignored,
                # so a stalled call could hang the whole application flow.
                client_kwargs["http_options"] = types.HttpOptions(
                    timeout=int(max(5, self.timeout) * 1000)
                )
            self._gemini_client = genai.Client(**client_kwargs)

        system, user = self._prompt(question, options, context=context)
        attempts = max(1, self.model_retries + 1)
        for attempt in range(attempts):
            try:
                chat = self._gemini_client.chats.create(
                    model=self.gemini_model,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )
                response = chat.send_message(message=user)
                text = (getattr(response, "text", None) or "").strip()
                if not text:
                    return None
                return self._parse_json_text(text)
            except Exception as exc:
                if not self._is_transient_gemini_error(exc) or attempt >= attempts - 1:
                    raise
                delay = self.retry_backoff_seconds * (2 ** attempt)
                print(
                    f"  Gemini: transient provider error; retrying in {delay:.1f}s "
                    f"({attempt + 1}/{attempts - 1})"
                )
                time.sleep(delay)
        return None

    def _maybe_disable_gemini(self, exc):
        """Stop calling Gemini for the session when the failure is permanent."""
        text = f"{type(exc).__name__} {exc}".lower()
        if isinstance(exc, RuntimeError) and "google-genai is required" in text:
            reason = "google-genai SDK not installed (pip install google-genai)"
        elif any(t in text for t in ("api key not valid", "api_key_invalid", "permission_denied", "401", "403", "unauthenticated")):
            reason = "API key rejected (check GEMINI_API_KEY)"
        elif any(t in text for t in ("404", "not_found", "is not found", "not supported for generatecontent")):
            reason = f"model {self.gemini_model!r} unavailable (check GEMINI_MODEL)"
        else:
            return
        self._gemini_disabled_reason = reason
        print(f"  Gemini QA DISABLED for this run: {reason}")

    @staticmethod
    def _is_transient_gemini_error(exc):
        text = str(exc).lower()
        return any(token in text for token in (
            "503", "unavailable", "high demand", "429", "resource_exhausted",
            "500", "502", "504", "deadline exceeded", "temporarily",
        ))

    def _ollama_reason(self, question, options, context=None):
        """
        Ask a locally running Ollama model using the same profile-grounded
        prompt as Gemini/OpenAI. Ollama is a fallback, not the primary reasoner.
        """
        system, user = self._prompt(question, options, context=context)
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        req = urllib.request.Request(
            self.ollama_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            raw = self._urlopen_json_with_retry(req, service="Ollama", retries=self.model_retries)
        except urllib.error.HTTPError as exc:
            # Some older/custom Ollama deployments expose /api/generate but
            # not /api/chat. A single bounded compatibility retry avoids a
            # needless hard 404 fallback failure without changing the default.
            if exc.code == 404 and self.ollama_url.rstrip("/").endswith("/api/chat"):
                alt_url = self.ollama_url.rsplit("/api/chat", 1)[0] + "/api/generate"
                alt_payload = {
                    "model": self.ollama_model,
                    "prompt": f"{system}\n\n{user}",
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                }
                alt_req = urllib.request.Request(
                    alt_url, data=json.dumps(alt_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST"
                )
                raw = self._urlopen_json_with_retry(alt_req, service="Ollama", retries=0)
            else:
                raise

        text = raw.get("message", {}).get("content", "")
        if not text:
            text = raw.get("response", "")
        return self._parse_json_text(text)

    def _urlopen_json_with_retry(self, req, service="model", retries=None):
        """Bounded retry for transient model-service failures."""
        if retries is None:
            retries = self.model_retries
        attempts = max(1, retries + 1)
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                transient = exc.code == 429 or 500 <= exc.code < 600
                if not transient or attempt >= attempts - 1:
                    raise
                delay = self.retry_backoff_seconds * (2 ** attempt)
                print(f"  {service}: transient HTTP {exc.code}; retrying in {delay:.1f}s ({attempt + 1}/{attempts - 1})")
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= attempts - 1:
                    raise
                delay = self.retry_backoff_seconds * (2 ** attempt)
                print(f"  {service}: transient transport error {type(exc).__name__}; retrying in {delay:.1f}s ({attempt + 1}/{attempts - 1})")
                time.sleep(delay)
        raise RuntimeError(f"{service} request failed after retries")

    def _openai_reason(self, question, options, context=None):
        system, user = self._prompt(question, options, context=context)
        payload = {
            "model": self.openai_model,
            "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "reasoning": {"effort": "low"}, "max_output_tokens": 500
        }
        req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        text = raw.get("output_text")
        if not text:
            chunks=[]
            for item in raw.get("output", []):
                for c in item.get("content", []):
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                        chunks.append(c.get("text", ""))
            text="".join(chunks)
        return self._parse_json_text(text)

    def _parse_json_text(self, text):
        """Parse model JSON defensively without changing the answer semantics.

        Models sometimes wrap valid JSON in markdown or add a short sentence
        around it. The old implementation passed the entire response directly
        to json.loads(), so one stray character caused JSONDecodeError and the
        question became UNKNOWN.
        """
        text = (text or "").strip()
        if not text:
            return None

        # Remove common markdown fences.
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text).strip()

        # First try the complete response.
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            pass

        # Recover the first balanced JSON object from surrounding prose.
        start = text.find("{")
        if start >= 0:
            depth = 0
            in_string = False
            escaped = False
            for i in range(start, len(text)):
                ch = text[i]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            parsed = json.loads(candidate)
                            return parsed if isinstance(parsed, dict) else None
                        except (json.JSONDecodeError, TypeError):
                            break

        # Recover common JSON-like model output with bare property names or
        # trailing commas. This specifically handles responses such as
        # {answer: "Advanced", kind: "single_select", ...} without loosening
        # the semantic validation performed afterwards.
        try:
            repaired = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)
            repaired = re.sub(r",\s*([}])", r"\1", repaired)
            parsed = json.loads(repaired)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            pass

        # Last conservative recovery for Python-dict-style model output.
        # literal_eval is intentionally restricted to the returned text and
        # does not execute arbitrary code.
        try:
            import ast
            parsed = ast.literal_eval(text)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, SyntaxError, TypeError):
            return None

    @staticmethod
    def _is_contact_question(question):
        """Return True only when the prompt explicitly requests contact data."""
        q = str(question or "").lower()
        return bool(
            re.search(r"\b(?:e[- ]?mail|email\s+id|email address)\b", q)
            or re.search(r"\b(?:phone|mobile(?:\s+(?:number|no))?|telephone|contact number|contact no)\b", q)
        )

    @staticmethod
    def _contains_contact_leak(answer):
        """Detect contact data appearing in an unrelated answer."""
        text = str(answer or "").strip()
        if not text:
            return False
        if re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, flags=re.I):
            return True
        if re.search(r"(?<!\d)(?:\+?91[-. ]?)?[6-9]\d{9}(?!\d)", text):
            return True
        return False

    def _validate(self, result, question, options):
        if not isinstance(result, dict):
            return None
        kind = str(result.get("kind") or "unknown").strip().lower()
        answer = result.get("answer")
        selected = result.get("selected_options") or []
        if isinstance(selected, str):
            selected = [selected]

        # Gemini frequently omits or mangles optional fields.  Normalise them
        # so a truthful answer is not thrown away for a formatting reason.
        try:
            conf = float(result.get("confidence"))
        except (TypeError, ValueError):
            conf = 0.8
        conf = max(0.0, min(1.0, conf))
        if conf < 0.5:
            print(f"  DIAG ProfileReasoner._validate rejected_low_confidence={conf}")
            return None
        result = dict(result, confidence=conf)
        if isinstance(answer, list) and kind != "multi_select":
            selected = selected or [str(x) for x in answer]
            answer = selected[0] if len(selected) == 1 else None
            if len(selected) > 1:
                kind = "multi_select"
        if isinstance(answer, str) and answer.strip().lower() in {"null", "none", "unknown", "n/a", "not applicable"}:
            return None
        if kind not in {"text", "number", "yes_no", "single_select", "multi_select"}:
            if selected and len(selected) > 1:
                kind = "multi_select"
            elif options:
                kind = "single_select"
                answer = answer if answer is not None else (selected[0] if selected else None)
            elif isinstance(answer, str) and answer.strip().lower() in {"yes", "no"}:
                kind = "yes_no"
            elif answer is not None:
                kind = "text"
        if kind == "single_select" and answer is None and selected:
            answer = selected[0]

        # Never allow a model/provider answer to leak profile contact data into
        # an unrelated question. Contact data is only permitted when the
        # question explicitly asks for it.
        if not self._is_contact_question(question):
            if kind == "multi_select":
                if any(self._contains_contact_leak(item) for item in selected):
                    print("  DIAG ProfileReasoner._validate rejected_contact_leak kind=multi_select")
                    return None
            elif self._contains_contact_leak(answer):
                print("  DIAG ProfileReasoner._validate rejected_contact_leak kind=%s" % kind)
                return None

        # UI action buttons are not answer choices.
        options = [
            x for x in options
            if self._norm(x) not in {
                "save", "continue", "next", "submit", "submit application",
                "apply", "apply now", "send", "send application",
                "finish", "done", "skip", "back", "cancel"
            }
        ]
        allowed = {self._norm(x): x for x in options}
        if kind == "multi_select":
            selected = [allowed[self._norm(x)] for x in selected if self._norm(x) in allowed]
            if not selected:
                return None
            return {
                "answer": selected,
                "kind": "multi_select",
                "field": result.get("field"),
                "confidence": result.get("confidence", 0)
            }

        if kind in ("single_select", "yes_no"):
            if answer is None:
                return None
            # Yes/No may be represented as exact visible options.
            if options:
                key=self._norm(answer)
                if key in allowed:
                    answer=allowed[key]
                else:
                    matched=self._match_option(answer, options, question)
                    if matched is None:
                        return None
                    answer=matched
            elif kind=="yes_no" and self._norm(answer) not in ("yes","no"):
                return None
            return {"answer": answer, "kind": kind, "field": result.get("field"),
                    "confidence": result.get("confidence", 0)}

        if kind == "number":
            if answer is None:
                return None
            try:
                n=float(str(answer).replace(",","").strip())
                normalized_number = str(int(n)) if n.is_integer() else str(n)
            except Exception:
                return None

            # A numeric-looking question may actually be rendered as a radio
            # scale (for example Python self-rating 1-10). In that case return
            # the exact visible option instead of treating it as a text input.
            if options:
                numeric_match = None
                for opt in options:
                    raw = str(opt).strip()
                    m = re.fullmatch(r"(?:rating\s*)?(\d+(?:\.\d+)?)", raw, flags=re.I)
                    if m:
                        try:
                            if float(m.group(1)) == n:
                                numeric_match = opt
                                break
                        except ValueError:
                            pass
                if numeric_match is not None:
                    return {
                        "answer": numeric_match,
                        "kind": "single_select",
                        "field": result.get("field"),
                        "confidence": result.get("confidence", 0),
                    }

            return {"answer": normalized_number, "kind": "number", "field": result.get("field"),
                    "confidence": result.get("confidence", 0)}

        if kind == "text":
            if answer is None or not str(answer).strip():
                return None
            return {"answer": str(answer).strip(), "kind": "text",
                    "field": result.get("field"), "confidence": result.get("confidence", 0)}

        return None

    def _certification_answer(self, q):
        """
        Answer certification questions only from the explicit certification
        list in profile.json. API experience is not treated as certification.
        """
        nq = self._norm(q)

        if "certif" not in nq and "certified" not in nq:
            return None

        certifications = [
            str(x).strip()
            for x in self.profile.get("certifications", [])
            if str(x).strip()
        ]

        normalized = [
            (self._norm(cert), cert)
            for cert in certifications
        ]

        # Open-ended certification requests.
        if any(
            phrase in nq
            for phrase in (
                "which certifications",
                "what certifications",
                "list your certifications",
                "name your certifications",
                "certifications do you have",
            )
        ):
            if certifications:
                return (
                    ", ".join(certifications),
                    "text",
                    "certifications",
                )
            return None

        # Specific certification/entity questions.
        entities = [
            "claude",
            "anthropic",
            "aws",
            "amazon web services",
            "azure",
            "google cloud",
            "gcp",
            "python",
            "tensorflow",
            "pytorch",
            "nptel",
            "cisco",
        ]

        requested = [
            self._norm(entity)
            for entity in entities
            if self._norm(entity) in nq
        ]

        # Match against the actual certification names, not API experience.
        if requested:
            for req in requested:
                if any(
                    req in cert_norm
                    or cert_norm in req
                    for cert_norm, _ in normalized
                ):
                    return "Yes", "yes_no", "certifications"

            return "No", "yes_no", "certifications"

        # Generic certification possession.
        if any(
            phrase in nq
            for phrase in (
                "do you have any certification",
                "do you have certifications",
                "are you certified",
                "do you hold any certification",
                "do you hold certifications",
            )
        ):
            return (
                "Yes" if certifications else "No",
                "yes_no",
                "certifications",
            )

        # Specific-looking possession question without a named entity:
        # answer only from the fact that the candidate has certifications.
        if any(
            phrase in nq
            for phrase in (
                "have you obtained any certification",
                "have you obtained certification",
                "have you completed any certification",
                "have you completed certification",
            )
        ):
            return (
                "Yes" if certifications else "No",
                "yes_no",
                "certifications",
            )

        return None

    def _employer_screening_answer(self, q, options):
        """
        Deterministic answers for common employer screening questions.

        These rules use only facts already present in profile.json. They run
        before Gemini so transient model/JSON failures cannot break simple,
        profile-grounded questions. Unknown preferences (for example,
        willingness to accept compensation-only contractor terms or a desired
        hourly USD rate) intentionally remain unresolved rather than being
        invented.
        """
        nq = self._norm(q)
        p = self.profile
        c = p.get("candidate", {}) or {}
        contact = p.get("contact", {}) or {}
        comp = p.get("compensation", {}) or {}
        employment = p.get("employment", {}) or {}

        def result(answer, kind, field, confidence=1.0):
            if options and kind in ("yes_no", "single_select"):
                answer_options = [
                    x for x in options
                    if self._norm(x) not in {
                        "save", "continue", "next", "submit",
                        "submit application", "apply", "apply now",
                        "send", "send application", "finish", "done",
                        "skip", "back", "cancel"
                    }
                ]
                if answer_options:
                    matched = self._match_option(answer, answer_options, nq)
                    if matched is None:
                        return None
                    answer = matched
            return {
                "answer": answer,
                "kind": kind,
                "field": field,
                "confidence": confidence,
            }

        # Plain "Experience (in years)" / "Total experience" style labels. These are
        # not phrased as "how many years...", so the generic duration rules below
        # never matched them and the whole Indeed form stopped on the first field.
        # The value comes only from the profile (never invented).
        if re.fullmatch(
            r"(?:total |overall |work |professional )*experience(?: in)?(?: years| yrs| year| yr)?(?: required)?",
            nq,
        ) and nq != "experience":
            years = c.get("total_experience_years")
            if years is not None:
                return result(str(years), "number", "candidate.total_experience_years", 1.0)

        # "Are you comfortable with our work timings / shift (12:30 PM-9:30 PM)?"
        # Answered only from the profile's explicit shift-flexibility flag.
        if (
            any(x in nq for x in ("comfortable", "okay with", "ok with", "fine with", "willing", "agree to", "can you work"))
            and any(x in nq for x in ("timing", "timings", "shift", "shifts", "working hours", "work hours", "night"))
        ):
            flex = (p.get("preferences", {}) or {}).get("night_shift")
            if flex is None:
                flex = c.get("night_shift")
            if flex is True:
                return result("Yes", "yes_no", "preferences.night_shift", 1.0)
            if flex is False:
                return result("No", "yes_no", "preferences.night_shift", 1.0)

        # Hyderabad residence. This is intentionally separate from generic
        # location because the question is a yes/no eligibility check.
        if (
            ("based in hyderabad" in nq)
            or ("live in hyderabad" in nq)
            or ("located in hyderabad" in nq)
            or ("reside in hyderabad" in nq)
            or ("living in hyderabad" in nq)
        ):
            city = self._norm(contact.get("city", "Hyderabad"))
            return result(
                "Yes" if "hyderabad" in city else "No",
                "yes_no",
                "contact.city",
            )

        # Explicit city/location questions.
        if (
            "which city in india" in nq
            or "what city in india" in nq
            or "city do you live" in nq
            or "city are you based" in nq
        ):
            city = contact.get("city") or "Hyderabad"
            return result(
                city,
                "single_select" if options else "text",
                "contact.city",
            )

        # State/country/location requests.
        if (
            "location (city state country)" in nq
            or "location city state country" in nq
            or "city state country" in nq
        ):
            city = contact.get("city") or "Hyderabad"
            state = contact.get("state") or "Telangana"
            country = contact.get("country") or "India"
            return result(
                f"{city}, {state}, {country}",
                "text",
                "contact.location",
            )

        if any(x in nq for x in (
            "level of proficiency in english", "english proficiency",
            "english level", "level of english", "proficiency level in english",
            "please select your english level",
        )):
            # No explicit English self-rating is stored in profile.json, so do
            # not invent one. Returning None intentionally lets Gemini, then
            # Ollama, reason from the visible choices instead of silently
            # forcing an unsupported level.
            return None
            if options:
                matched = self._match_option(preferred, options, nq)
                if matched is None:
                    return None
                preferred = matched
            return result(preferred, "single_select" if options else "text",
                          "skills.English", 1.0)

        # Expected compensation must take precedence when the question contains
        # both words such as "current salary expectations".
        if any(
            x in nq
            for x in (
                "expected ctc", "expected salary", "expected package",
                "desired ctc", "desired salary", "desired compensation",
                "salary expectation", "salary expectations",
                "expected compensation",
            )
        ):
            value = comp.get("expected_ctc")
            if value is None or str(value).strip() == "":
                return None
            try:
                numeric = float(str(value).replace(",", "").strip())
                # Job forms commonly express salary expectations in LPA. Keep
                # the established project convention: ₹400000 -> 4 for generic
                # expected-salary questions and also for explicit LPA questions.
                # "... in numbers" asks for the full amount (e.g. 400000), not LPA.
                if numeric >= 100000 and "in numbers" not in nq:
                    value = str(int(numeric / 100000)) if numeric.is_integer() else str(numeric / 100000)
            except (TypeError, ValueError):
                value = str(value).strip()
            return result(str(value), "number", "compensation.expected_ctc", 1.0)

        # Current salary / CTC must come from profile.json, not a hard-coded
        # value. Preserve the existing numeric convention used by Naukri.
        if any(
            x in nq
            for x in (
                "current ctc", "present ctc", "current salary",
                "present salary", "current package", "present package",
                "current compensation",
            )
        ):
            value = comp.get("current_ctc")
            if value is None or str(value).strip() == "":
                return None
            return result(str(value), "number", "compensation.current_ctc", 1.0)

        # Notice period.
        if "notice period" in nq or "notice duration" in nq:
            value = c.get("notice_period_days")
            if value is None:
                value = 0
            return result(str(value), "number", "candidate.notice_period_days", 1.0)

        if (
            "time to join" in nq
            or "when can you join" in nq
            or "when can you start" in nq
            or "earliest start" in nq
        ):
            immediate = c.get("available_to_join_immediately")
            if immediate is True:
                # If the form explicitly expects a number, use the profile's
                # notice period. Otherwise the textual answer is clearer.
                if "days" in nq or "day" in nq:
                    return result("0", "number",
                                  "candidate.notice_period_days", 1.0)
                return result("Immediately",
                              "single_select" if options else "text",
                              "candidate.available_to_join_immediately", 1.0)

        # Compound requirement: 5+ years of data-engineering experience AND
        # specific technologies/security. The profile is a fresher and does
        # not claim those professional requirements, so the conjunction is No.
        if (
            "5+ years" in nq
            and "data engineering" in nq
            and (
                "dbt" in nq
                or "pyspark" in nq
                or "snowpark" in nq
            )
            and (
                "rls" in nq
                or "row level security" in nq
                or "column level security" in nq
                or "rbac" in nq
            )
        ):
            return result("False", "yes_no", "experience.professional", 1.0)

        # Production/advanced-pilot Snowflake Cortex / Databricks Genie is
        # explicitly not claimed by the supplied profile.
        if (
            ("snowflake cortex" in nq or "databricks genie" in nq)
            and (
                "production" in nq
                or "advanced pilot" in nq
                or "deployed" in nq
                or "personally built" in nq
                or "configured" in nq
            )
        ):
            return result("False", "yes_no", "experience.snowflake_cortex_databricks_genie", 1.0)

        # A conditional description of the above unsupported experience should
        # never be fabricated. "N/A" is truthful when the preceding condition
        # is not met.
        if (
            ("snowflake cortex" in nq or "databricks genie" in nq)
            and (
                "briefly describe" in nq
                or "describe a project" in nq
                or "which specific features" in nq
                or "semantic layer" in nq
            )
        ):
            return result("N/A", "text",
                          "experience.snowflake_cortex_databricks_genie", 1.0)

        # Domain experience: no explicit Pharma/life-sciences/regulated
        # financial-services experience is present in the supplied profile.
        if (
            ("pharma" in nq or "life sciences" in nq or
             "regulated financial services" in nq)
            and (
                "domain experience" in nq
                or "do you have" in nq
                or "experience" in nq
            )
        ):
            if "if your answer is yes" in nq or "mention the domain" in nq:
                return result("No", "yes_no", "experience.domain", 1.0)
            return result("No", "yes_no", "experience.domain", 1.0)

        # Do not invent a personal preference for compensation-only contractor
        # terms. This must remain unknown unless the profile explicitly stores
        # the preference.
        if (
            "compensation-only" in nq
            or "compensation only" in nq
            or "independent contractor" in nq
        ) and (
            "comfortable" in nq
            or "proceeding" in nq
            or "agreement" in nq
        ):
            preference = p.get("preferences", {}) or {}
            for key in (
                "comfortable_with_independent_contract",
                "accepts_compensation_only",
                "willing_to_work_as_independent_contractor",
            ):
                if key in preference:
                    return result(
                        "Yes" if preference.get(key) else "No",
                        "yes_no",
                        f"preferences.{key}",
                        1.0,
                    )
            return None

        # Likewise, an hourly USD rate is not derivable truthfully from an
        # annual CTC without an explicit profile preference/conversion policy.
        if (
            "hourly rate" in nq
            and ("usd" in nq or "dollar" in nq)
        ):
            for key in ("expected_hourly_rate_usd", "hourly_rate_usd"):
                if key in comp and str(comp.get(key)).strip():
                    return result(
                        str(comp[key]).strip(),
                        "number",
                        f"compensation.{key}",
                        1.0,
                    )
            return None

        return None

    def _common_profile_fact(self, q, options):
        """
        Handle common screening/application questions using only explicit
        profile facts. This expands coverage without changing the question
        detection, answer verification, or application flow.
        """
        nq = self._norm(q)
        p = self.profile
        c = p.get("candidate", {}) or {}
        contact = p.get("contact", {}) or {}
        education = p.get("education", {}) or {}
        employment = p.get("employment", {}) or {}

        def result(answer, kind, field, confidence=1.0):
            if options and kind in ("yes_no", "single_select"):
                answer_options = [
                    x for x in options
                    if self._norm(x) not in {
                        "save", "continue", "next", "submit",
                        "submit application", "apply", "apply now",
                        "send", "send application", "finish", "done",
                        "skip", "back", "cancel",
                    }
                ]
                if answer_options:
                    matched = self._match_option(
                        answer,
                        answer_options,
                        nq,
                    )
                    if matched is None:
                        return None
                    answer = matched
            return {
                "answer": answer,
                "kind": kind,
                "field": field,
                "confidence": confidence,
            }

        # Postal-code labels vary substantially across ATS forms.  This is a
        # plain profile fact, so resolve it before any semantic fallback and
        # keep it as a text value: leading zeroes are significant in some
        # countries and must never be coerced away by a numeric control.
        if any(label in nq for label in (
            "postal code", "zip code", "pin code", "pincode", "post code",
        )):
            pin_code = contact.get("pin_code")
            if pin_code is not None and str(pin_code).strip():
                return result(str(pin_code).strip(), "text", "contact.pin_code")
            return None

        # Location and geography.
        if (
            "current location" in nq
            or "current city" in nq
            or "where are you currently located" in nq
            or "where are you based" in nq
            or "location do you currently" in nq
        ):
            return result(
                contact.get("city", "Hyderabad"),
                "single_select" if options else "text",
                "contact.city",
            )

        if (
            "preferred location" in nq
            or "preferred city" in nq
            or "location preference" in nq
            or "preferred work location" in nq
        ):
            return result(
                contact.get("city", "Hyderabad"),
                "single_select" if options else "text",
                "contact.city",
            )

        # Combined "Location (City, State, Country)" style fields ask for
        # all three in one string — the narrower "state" rule below would
        # otherwise match this too (it contains both "state" and
        # "location") and wrongly return just the state alone.
        if (
            ("city" in nq and "state" in nq and "country" in nq)
            or ("city" in nq and "state" in nq and "province" in nq)
        ):
            city = contact.get("city", "Hyderabad")
            state = contact.get("state", "Telangana")
            country = contact.get("country", "India")
            return result(f"{city}, {state}, {country}", "text", "contact.city_state_country")

        if (
            "current state" in nq
            or "which state" in nq
            or "state you live in" in nq
            or "state you reside" in nq
            or (re.search(r"\bstate\b", nq) and "location" in nq)
        ):
            return result(
                contact.get("state", "Telangana"),
                "single_select" if options else "text",
                "contact.state",
            )

        if "nationality" in nq or "citizenship" in nq:
            return result(
                contact.get("nationality", "Indian"),
                "single_select" if options else "text",
                "contact.nationality",
            )

        if "gender" in nq or "sex" in nq:
            return result(
                contact.get("gender", "Male"),
                "single_select" if options else "text",
                "contact.gender",
            )

        # Education.
        if (
            "highest qualification" in nq
            or "highest education" in nq
            or "educational qualification" in nq
        ):
            degree = education.get("degree") if education else None
            if not degree:
                combined = str(c.get("education", "B.E./B.Tech"))
                degree = combined.split(",", 1)[0].strip()

            return result(
                degree or "B.E./B.Tech",
                "single_select" if options else "text",
                "education.degree",
            )

        if any(
            phrase in nq
            for phrase in (
                "degree name",
                "what degree",
                "which degree",
                "qualification name",
            )
        ):
            degree = education.get("degree") if education else None
            if not degree:
                combined = str(c.get("education", "B.E./B.Tech"))
                degree = combined.split(",", 1)[0].strip()

            return result(
                degree or "B.E./B.Tech",
                "single_select" if options else "text",
                "education.degree",
            )

        if any(
            phrase in nq
            for phrase in (
                "branch",
                "major",
                "specialization",
                "area of study",
                "field of study",
            )
        ):
            # Do not trigger on broad "specialization" questions if they are
            # about a job rather than education.
            if any(
                word in nq
                for word in (
                    "degree",
                    "education",
                    "college",
                    "university",
                    "study",
                    "branch",
                    "major",
                )
            ):
                value = education.get("branch") if education else None
                if not value:
                    combined = str(
                        c.get(
                            "education",
                            "Electronics and Communication Engineering",
                        )
                    )
                    value = (
                        combined.split(",", 1)[1].strip()
                        if "," in combined
                        else combined
                    )
                return result(
                    value or "Electronics and Communication Engineering",
                    "single_select" if options else "text",
                    "education.branch",
                )

        if (
            "college" in nq
            or "university" in nq
            or "institution" in nq
            or "school" in nq
        ):
            value = (
                education.get("college")
                if education
                else "Vasavi College of Engineering"
            )
            return result(
                value or "Vasavi College of Engineering",
                "single_select" if options else "text",
                "education.college",
            )

        # Employment / fresher facts.
        if (
            "current employer" in nq
            or "current company" in nq
            or "present employer" in nq
            or "present company" in nq
            or "employer name" in nq
        ):
            value = (
                employment.get("current_company")
                or "Not Applicable"
            )
            return result(
                value,
                "single_select" if options else "text",
                "employment.current_company",
            )

        if (
            "current designation" in nq
            or "current job title" in nq
            or "present designation" in nq
            or "job title" == nq.strip()
        ):
            value = (
                c.get("current_designation")
                or "Fresher / Graduate"
            )
            return result(
                value,
                "single_select" if options else "text",
                "candidate.current_designation",
            )

        if (
            "employment status" in nq
            or "currently employed" in nq
            or "currently working" in nq
            or "currently employed?" in nq
        ):
            return result(
                "Yes" if c.get("currently_employed") else "No",
                "yes_no",
                "candidate.currently_employed",
            )

        if (
            "fresher" in nq
            and any(
                phrase in nq
                for phrase in (
                    "are you a",
                    "is this for",
                    "are you",
                )
            )
        ):
            return result(
                "Yes" if c.get("total_experience_years", 0) == 0 else "No",
                "yes_no",
                "candidate.total_experience_years",
            )

        if (
            "internship experience" in nq
            or "internship experience" in nq
            or "have you done an internship" in nq
            or "internship" == nq.strip()
        ):
            return result(
                "Yes" if c.get("internship_experience") else "No",
                "yes_no",
                "candidate.internship_experience",
            )

        # Availability / joining.
        if (
            "available start date" in nq
            or "earliest start date" in nq
            or "when can you start" in nq
            or "when can you join" in nq
            or "joining availability" in nq
        ):
            value = "Immediately"
            return result(
                value,
                "single_select" if options else "text",
                "candidate.available_to_join_immediately",
            )

        # Explicit work authorization / sponsorship variants.
        if (
            "authorized to work" in nq
            or "legally authorized" in nq
            or "work authorization" in nq
            or "right to work" in nq
        ) and "india" in nq:
            return result(
                "Yes" if c.get("authorized_to_work_in_india") else "No",
                "yes_no",
                "candidate.authorized_to_work_in_india",
            )

        if (
            "require sponsorship" in nq
            or "need sponsorship" in nq
            or "visa sponsorship" in nq
            or "sponsorship required" in nq
        ):
            return result(
                "Yes" if c.get("visa_sponsorship_required") else "No",
                "yes_no",
                "candidate.visa_sponsorship_required",
            )

        # Common logistics variants.
        if (
            "active offer" in nq
            or "offer in hand" in nq
            or "currently holding an offer" in nq
        ):
            return result(
                "Yes" if c.get("has_active_offer") else "No",
                "yes_no",
                "candidate.has_active_offer",
            )

        return None

    def _catalog_profile_fact(self, q, options):
        """Resolve explicitly configured profile facts before model fallback.

        The catalog is intentionally declarative: it can add employer-wording
        aliases without duplicating personal values in code.  Values still
        come only from profile.json and choice answers are mapped to options
        owned by the current field.
        """
        nq = self._norm(q)
        catalog = self.profile.get("deterministic_question_catalog", {}) or {}

        def read_path(path):
            value = self.profile
            for key in str(path or "").split("."):
                if not isinstance(value, dict):
                    return None
                value = value.get(key)
            return value

        for entry_name, entry in catalog.items():
            if not isinstance(entry, dict):
                continue
            patterns = [self._norm(x) for x in entry.get("patterns", [])]
            if not any(pattern and pattern in nq for pattern in patterns):
                continue
            value = read_path(entry.get("path"))
            if value is None or str(value).strip() == "":
                return None

            kind = str(entry.get("kind") or "text")
            answer = value
            if kind == "yes_no":
                answer = "Yes" if value is True else "No" if value is False else None
            elif kind == "number":
                answer = str(value)
            elif isinstance(value, (list, tuple)):
                answer = ", ".join(str(x).strip() for x in value if str(x).strip())
            else:
                answer = str(value).strip()
            if answer in (None, ""):
                return None

            if options and kind in ("yes_no", "single_select"):
                answer_options = [
                    x for x in options
                    if self._norm(x) not in {
                        "save", "continue", "next", "submit", "submit application",
                        "apply", "apply now", "send", "send application", "finish",
                        "done", "skip", "back", "cancel", "previous",
                    }
                ]
                if answer_options:
                    matched = self._match_option(answer, answer_options, nq)
                    if matched is None:
                        return None
                    answer = matched

            return {
                "answer": answer,
                "kind": kind,
                "field": entry.get("path") or entry_name,
                "confidence": 1.0,
            }
        return None

    def _learning_approach_answer(self, q, options):
        """
        Resolve common work-style screening questions when the options contain
        a clearly constructive learning/debugging approach.

        This is intentionally conservative: it matches only recognizable
        question families and only returns an existing visible option label.
        It never invents a preference for unrelated questions.
        """
        nq = self._norm(q)

        families = (
            "unfamiliar technology",
            "new technology",
            "new tool",
            "new framework",
            "new library",
            "new technology",
            "learn a new technology",
            "learn unfamiliar",
            "approach an unfamiliar",
        )

        if not any(family in nq for family in families):
            return None

        options = options or []

        preferred_patterns = (
            (
                "learn the fundamentals",
                "documentation",
                "prototype",
                "test",
                "debug",
            ),
            (
                "learn the fundamentals",
                "documentation",
                "small prototype",
            ),
            (
                "documentation",
                "small prototype",
                "test",
            ),
            (
                "research",
                "documentation",
                "prototype",
            ),
        )

        for raw in options:
            norm = self._norm(raw)
            for pattern in preferred_patterns:
                if all(part in norm for part in pattern):
                    return {
                        "answer": raw,
                        "kind": "single_select",
                        "field": "work_style.learning_approach",
                        "confidence": 0.95,
                    }

        return None

    def _education_and_skills_answer(self, q, options):
        """Deterministic answers for common education and skill screening fields."""
        nq = self._norm(q)
        raw_q = str(q or "")
        p = self.profile
        c = p.get("candidate", {}) or {}
        skills = p.get("skills", []) or []
        if isinstance(skills, dict):
            skills = list(skills.keys())

        def result(answer, kind, field, confidence=1.0):
            if options and kind in ("yes_no", "single_select"):
                answer_options = [
                    x for x in options
                    if self._norm(x) not in {
                        "save", "continue", "next", "submit", "submit application",
                        "apply", "apply now", "send", "send application",
                        "finish", "done", "skip", "back", "cancel"
                    }
                ]
                if answer_options:
                    matched = self._match_option(answer, answer_options, nq)
                    if matched is None:
                        return None
                    answer = matched
            return {"answer": answer, "kind": kind, "field": field, "confidence": confidence}

        def percentage(field, default):
            value = c.get(field, default)
            try:
                return float(str(value).replace("%", "").strip())
            except (TypeError, ValueError):
                return None

        def threshold_value(raw):
            patterns = (
                r"(?:more than|greater than|above|over)\s*(\d+(?:\.\d+)?)",
                r"(?:at least|greater than or equal to|more than or equal to)\s*(\d+(?:\.\d+)?)",
                r"(\d+(?:\.\d+)?)\s*(?:or more|or above|and above|\+)",
            )
            for pattern in patterns:
                m = re.search(pattern, raw.lower())
                if m:
                    return float(m.group(1)), ("more" if "more than" in m.group(0) or "greater than" in m.group(0) or "above" in m.group(0) or "over" in m.group(0) else "at_least")
            return None, None

        is_10th = any(x in nq for x in (
            "10th", "10 th", "tenth", "class x", "class 10", "ssc"
        )) and any(x in nq for x in ("percentage", "percent", "marks", "score"))
        is_12th = any(x in nq for x in (
            "12th", "12 th", "twelfth", "class xii", "class 12", "intermediate", "hsc"
        )) and any(x in nq for x in ("percentage", "percent", "marks", "score"))

        if is_10th or is_12th:
            field = "class_10_percentage" if is_10th else "class_12_percentage"
            default = 95 if is_10th else 94
            value = percentage(field, default)
            if value is None:
                return None

            threshold, relation = threshold_value(raw_q)
            if threshold is not None:
                answer_bool = value > threshold if relation == "more" else value >= threshold
                return result("Yes" if answer_bool else "No", "yes_no", f"candidate.{field}", 1.0)

            display = str(int(value)) if value.is_integer() else str(value)
            return result(display, "number", f"candidate.{field}", 1.0)

        # Open-ended skill inventory.
        if any(x in nq for x in (
            "which skills", "what skills", "list your skills", "skills do you have",
            "technical skills", "what are your skills"
        )) and not options:
            if skills:
                return result(", ".join(str(x).strip() for x in skills if str(x).strip()), "text", "skills", 1.0)

        # Multi-select skill checklist.
        if options and self._looks_multi(nq):
            matches = [opt for opt in options if self._option_matches_profile(opt)]
            if matches:
                return result(matches, "multi_select", "skills", 1.0)

        # Programming-language prompts are a factual subset of the skill
        # inventory, not a request to invent general technical skills.
        if any(phrase in nq for phrase in (
            "programming languages", "programming language", "coding languages",
        )):
            languages = [
                skill for skill in skills
                if self._norm(skill) in {"python", "c", "c++", "java", "javascript", "typescript"}
            ]
            if options:
                matches = [opt for opt in options if self._option_matches_profile(opt)]
                if matches:
                    return result(matches, "multi_select", "skills.programming_languages", 1.0)
            if languages:
                return result(
                    ", ".join(str(skill) for skill in languages),
                    "text", "skills.programming_languages", 1.0,
                )

        # Yes/no skill possession questions.
        if self._is_yes_no(nq):
            for skill in skills:
                ns = self._norm(skill)
                # A one-character normalized skill (C/C++) must not match
                # arbitrary words such as "CGPA" or "can".  Preserve a
                # literal C++ match while requiring multi-character skills
                # to occur as meaningful normalized terms.
                raw_skill = str(skill).strip().lower()
                raw_question = str(q or "").lower()
                skill_mentioned = (
                    (len(ns) >= 2 and ns in nq)
                    or (raw_skill == "c" and re.search(r"(?<![a-z0-9])c(?![a-z0-9+])", raw_question) is not None)
                    or (raw_skill == "c++" and "c++" in raw_question)
                )
                if skill_mentioned and any(x in nq for x in (
                    "do you have", "have you", "worked with", "used", "familiar",
                    "hands on", "hands-on", "experience", "know"
                )):
                    return result("Yes", "yes_no", f"skills.{skill}", 1.0)

        # Professional years for a named skill are zero for this fresher unless
        # the profile explicitly stores a different number. Never invent years.
        if any(x in nq for x in ("years of experience", "years experience", "how many years", "how much experience")):
            for skill in skills:
                ns = self._norm(skill)
                raw_skill = str(skill).strip().lower()
                raw_question = str(q or "").lower()
                skill_mentioned = (
                    (len(ns) >= 2 and ns in nq)
                    or (raw_skill == "c" and re.search(r"(?<![a-z0-9])c(?![a-z0-9+])", raw_question) is not None)
                    or (raw_skill == "c++" and "c++" in raw_question)
                )
                if skill_mentioned:
                    years = c.get("total_experience_years", 0)
                    return result(str(years), "number", f"skills.{skill}.experience_years", 1.0)

        return None

    def _open_text_profile_answer(self, q, options):
        """Handle common open-ended AI/GenAI questions from explicit profile facts.

        This is intentionally conservative. It does not invent a self-rating or
        a number of years when the profile does not contain one; those questions
        are left for Gemini/Ollama to reason about.
        """
        nq = self._norm(q)
        p = self.profile
        skills = p.get("skills", []) or []
        if isinstance(skills, dict):
            skills = list(skills.keys())
        skill_text = " ".join(self._norm(x) for x in skills)

        # Generic skill/proficiency self-rating questions are deterministic.
        # The requested default rating is 8. If the UI exposes a numeric option,
        # use the exact visible option so select/radio controls receive valid UI
        # values; otherwise return numeric 8 for a text/number field.
        rating_markers = (
            "rate yourself", "rate your", "self rating", "self-rate",
            "rating", "out of 10", "out of 5", "out of 100",
            "1 to 10", "1-10", "1 / 10", "1/10",
            "how good are you", "how good is your",
            "how proficient are you", "how proficient is your",
            "proficiency", "proficiency level", "skill level",
        )
        if any(marker in nq for marker in rating_markers):
            rating = 8
            if options:
                # Prefer an exact visible 8, including common labels such as
                # "8 - Very Good" or "8/10".
                for opt in options:
                    raw = str(opt).strip()
                    norm = self._norm(raw)
                    if norm == "8" or re.match(r"^8(?:\s+|/|[-:]|\().*$", raw.lower()):
                        return {
                            "answer": opt,
                            "kind": "single_select",
                            "field": "self_rating",
                            "confidence": 1.0,
                        }
                # If the visible scale genuinely does not contain 8, do not
                # force an invalid option; let the existing model/local fallback
                # decide based on the actual choices.
                return None
            return {
                "answer": str(rating),
                "kind": "number",
                "field": "self_rating",
                "confidence": 1.0,
            }

        # LinkedIn profile questions are direct profile facts and should never
        # depend on an LLM.
        linkedin = str((p.get("online_profiles", {}) or {}).get("linkedin") or "").strip()
        print(
            "  DIAG ProfileReasoner._local_reason linkedin_branch_check "
            f"entered={bool(linkedin and 'linkedin' in nq)} "
            "profile_key='online_profiles.linkedin' "
            f"linkedin_value_found={bool(linkedin)}"
        )
        if linkedin and "linkedin" in nq:
            username_request = any(x in nq for x in (
                "linkedin username", "linkedin handle", "linkedin user name",
            ))
            profile_request = any(x in nq for x in (
                "linkedin profile", "linkedin url", "linkedin link",
                "linkedin account", "linkedin page", "what is your linkedin",
                "what's your linkedin", "provide your linkedin",
                "enter your linkedin",
            ))
            if username_request and not profile_request:
                answer = linkedin.rstrip("/").rsplit("/", 1)[-1]
            else:
                answer = linkedin if linkedin.lower().startswith(("http://", "https://")) else f"https://{linkedin.lstrip('/')}"
            result_value = {
                "answer": answer,
                "kind": "text",
                "field": "online_profiles.linkedin",
                "confidence": 1.0,
            }
            print(f"  DIAG ProfileReasoner._local_reason linkedin_return={_diag_reason_result(result_value)!r}")
            return result_value

        # Any genuine GitHub-profile question is factual and should never depend
        # on Gemini. The supplied profile stores the GitHub handle under
        # online_profiles.github. Return a full URL for profile/link requests,
        # while username/handle requests keep the bare handle.
        if "github" in nq:
            github = str((p.get("online_profiles", {}) or {}).get("github") or "").strip()
            if github:
                username_request = any(x in nq for x in (
                    "github username", "github handle", "github user name",
                ))
                profile_request = any(x in nq for x in (
                    "github profile", "github url", "github link",
                    "github account", "github page", "github portfolio",
                    "what is your github", "what's your github",
                    "provide your github", "enter your github",
                ))
                if username_request and not profile_request:
                    answer = github.rsplit("/", 1)[-1]
                else:
                    answer = github if github.lower().startswith(("http://", "https://")) else f"https://github.com/{github.lstrip('@')}"
                return {
                    "answer": answer,
                    "kind": "text",
                    "field": "online_profiles.github",
                    "confidence": 1.0,
                }

        # Open-ended applications/solutions questions should use the actual
        # projects in profile.json. This covers recruiter wording such as
        # "What applications or solutions have you worked with?" which is
        # semantically a project-description request, not a professional-years
        # claim.
        if (
            not options
            and any(x in nq for x in (
                "what applications or solutions have you worked with",
                "applications or solutions have you worked with",
                "applications or solutions have you worked on",
                "what applications have you worked with",
                "what solutions have you worked with",
                "applications you have worked with",
                "solutions you have worked with",
            ))
        ):
            projects = p.get("projects", []) or []
            descriptions = []
            for project in projects:
                if not isinstance(project, dict):
                    continue
                title = str(project.get("title", "")).strip()
                details = str(project.get("details", "")).strip()
                if title and details:
                    descriptions.append(f"{title}: {details}")
            if descriptions:
                return {
                    "answer": " ".join(descriptions),
                    "kind": "text",
                    "field": "projects",
                    "confidence": 1.0,
                }

        # Hands-on GenAI/LLM/application experience is supported by the profile.
        ai_terms = ("chatbot", "gen ai", "generative ai", "llm", "gemini", "llama", "chatgpt", "claude", "ai tool")
        experience_words = ("experience", "used", "using", "worked with", "hands on", "built", "application", "app")
        if any(term in nq for term in ai_terms) and any(word in nq for word in experience_words):
            # If the question is explicitly yes/no, return the truthful boolean.
            if self._is_yes_no(nq) or "yes or no" in nq:
                return {
                    "answer": "Yes",
                    "kind": "yes_no",
                    "field": "projects.ai_genai_experience",
                    "confidence": 1.0,
                }
            # For an open text field, describe only what the profile supports.
            if not options:
                return {
                    "answer": (
                        "I have hands-on project experience building AI and GenAI applications, "
                        "including LLM-based applications, RAG, Gemini API, Ollama, LangChain, "
                        "and AI agents. I am a fresher, so this is project experience rather than "
                        "professional employment."
                    ),
                    "kind": "text",
                    "field": "projects.ai_genai_experience",
                    "confidence": 0.95,
                }

        # Open-ended skill inventory.
        if any(x in nq for x in ("which skills", "what skills", "list your skills", "skills do you have", "technical skills")) and not options:
            if skills:
                return {
                    "answer": ", ".join(str(x).strip() for x in skills if str(x).strip()),
                    "kind": "text",
                    "field": "skills",
                    "confidence": 1.0,
                }

        return None

    def _skill_experience_years_answer(self, q, options):
        """Resolve explicit skill-duration questions from question_mappings/profile data.

        This runs before generic open-text handling. A question that explicitly
        asks "how much/how many years of experience" for a skill is a duration
        fact, not a request for a general profile summary.
        """
        nq = self._norm(q)
        if not (
            "how much experience do you have in" in nq
            or "how many years of experience do you have in" in nq
            or "how many years experience do you have in" in nq
            or re.search(r"\b(?:years|year) of experience in\b", nq)
        ):
            return None

        mappings = self.profile.get("question_mappings", {}) or {}
        for entry_name, entry in mappings.items():
            if not isinstance(entry, dict):
                continue
            field = str(entry.get("field") or "")
            if not field.startswith("skill_experience_years."):
                continue
            patterns = [self._norm(x) for x in entry.get("patterns", [])]
            if not any(pattern and pattern in nq for pattern in patterns):
                continue
            skill = field.split(".", 1)[1]
            years = (self.profile.get("skill_experience_years", {}) or {}).get(skill)
            # A missing skill-specific professional-duration value is not
            # permission to invent experience. The candidate profile records
            # zero professional years overall, so the safe factual duration is 0.
            if years is None:
                years = self.profile.get("candidate", {}).get("professional_experience_years", 0)
            try:
                years_num = float(str(years).strip())
            except (TypeError, ValueError):
                return None
            answer = str(int(years_num)) if years_num.is_integer() else str(years_num)

            # When a visible numeric option exists, select the exact option.
            if options:
                option_norms = {self._norm(o): o for o in options}
                if self._norm(answer) in option_norms:
                    return {
                        "answer": option_norms[self._norm(answer)],
                        "kind": "single_select",
                        "field": field,
                        "confidence": 1.0,
                    }

            return {
                "answer": answer,
                "kind": "number",
                "field": field,
                "confidence": 1.0,
            }
        return None

    def _local_reason(self, q, options):
        # Conservative fallback. It is semantic, but intentionally refuses
        # unknown facts rather than pretending to be an LLM.
        nq=self._norm(q)
        print(f"  DIAG ProfileReasoner._local_reason normalized_question={nq!r}")

        # Explicit skill-duration questions must beat generic open-text
        # generation. This prevents "How much experience do you have in Deep
        # Learning?" from becoming a generic skills/profile paragraph.
        skill_duration = self._skill_experience_years_answer(q, options)
        if skill_duration is not None:
            return skill_duration

        education_skills = self._education_and_skills_answer(q, options)
        if education_skills is not None:
            return education_skills

        open_text = self._open_text_profile_answer(q, options)
        if open_text is not None:
            print(f"  DIAG ProfileReasoner._local_reason returned={_diag_reason_result(open_text)!r}")
            return open_text

        cert = self._certification_answer(q)
        if cert is not None:
            answer, kind, field = cert
            return {
                "answer": answer,
                "kind": kind,
                "field": field,
                "confidence": 1.0,
            }

        # CGPA bucket questions should resolve from the actual visible
        # options before generic numeric/Yes-No handling.
        if options and "cgpa" in nq:
            cgpa_option = self._match_cgpa_option(
                nq,
                options,
            )
            if cgpa_option is not None:
                return {
                    "answer": cgpa_option,
                    "kind": "single_select",
                    "field": "candidate.cgpa",
                    "confidence": 1.0,
                }

        employer = self._employer_screening_answer(
            q,
            options,
        )
        if employer is not None:
            return employer

        catalog_fact = self._catalog_profile_fact(q, options)
        if catalog_fact is not None:
            return catalog_fact

        project = self._project_experience_answer(
            q,
            options,
        )
        if project is not None:
            return project

        learning_approach = self._learning_approach_answer(
            q,
            options,
        )
        if learning_approach is not None:
            return learning_approach

        common_fact = self._common_profile_fact(
            q,
            options,
        )
        if common_fact is not None:
            return common_fact

        # Exact profile facts.
        # Current/expected CTC are handled by _employer_screening_answer
        # above using profile.json values. Do not hard-code salary values here.
        if (
            ("graduation" in nq and "year" in nq)
            or "year of graduation" in nq
            or "year did you graduate" in nq
            or "when did you graduate" in nq
            or "when did you pass out" in nq
            or "what year did you pass out" in nq
            or "which year did you pass out" in nq
            or "year of passing" in nq
            or "passing year" in nq
            or "passed out year" in nq
            or "year you completed" in nq
        ):
            return {"answer":str(self.profile["candidate"]["graduation_year"]),"kind":"number","field":"candidate.graduation_year","confidence":1}
        # Education/profile facts.
        if "cgpa" in nq:
            # When the UI supplies CGPA buckets, choose the actual bucket.
            # Only fall back to numeric 6.8 when no bucket matches.
            if options:
                cgpa_option = self._match_cgpa_option(
                    nq,
                    options,
                )
                if cgpa_option is not None:
                    return {
                        "answer": cgpa_option,
                        "kind": "single_select",
                        "field": "candidate.cgpa",
                        "confidence": 1.0,
                    }

            if not any(
                x in nq
                for x in (
                    "less than",
                    "below",
                    "under",
                    "at least",
                    "or more",
                    "above",
                )
            ):
                return {
                    "answer": "6.8",
                    "kind": "number",
                    "field": "candidate.cgpa",
                    "confidence": 1,
                }
        if any(x in nq for x in ("10th percentage","10th percent","tenth percentage","ssc percentage")):
            return {"answer":"95","kind":"number","field":"candidate.class_10_percentage","confidence":1}
        if any(x in nq for x in ("12th percentage","12th percent","intermediate percentage","inter percentage","hsc percentage")):
            return {"answer":"94","kind":"number","field":"candidate.class_12_percentage","confidence":1}
        if any(x in nq for x in (
            "b.e. percentage", "be percentage", "b e percentage",
            "btech percentage", "b tech percentage", "btech percent",
            "b tech percent", "bachelor percentage", "bachelor percent",
        )) or (("be" in nq or "b e" in nq) and "percentage" in nq):
            return {"answer":"68","kind":"number","field":"candidate.be_percentage","confidence":1}
        # Job-title/designation-flavored questions are answered directly and
        # take priority over the salutation check below, so "Current Job
        # Title" etc. never gets mistaken for a "Mr/Mrs/Ms" prefix field.
        job_title_markers = (
            "job title", "position title", "role title", "current title",
            "preferred title", "desired title", "job role", "designation",
            "current position", "current role", "current job",
        )
        if any(x in nq for x in job_title_markers) or "current designation" in nq:
            return {
                "answer": self.profile.get("candidate", {}).get("current_designation", "Fresher / Graduate"),
                "kind": "text",
                "field": "candidate.current_designation",
                "confidence": 1.0,
            }
        # Bare "title" is ambiguous beyond the job-title markers above (e.g.
        # "project title", "thesis title"). Only answer it as a salutation
        # when the question is unambiguous, or the visible options are
        # actually Mr/Mrs/Ms-style choices; otherwise fall through so
        # Gemini/Ollama can use the real visible options instead of guessing.
        if (
            "salutation" in nq
            or "prefix" in nq
            or "honorific" in nq
            or "courtesy title" in nq
            or nq.strip() == "title"
            or (
                "title" in nq
                and options
                and any(
                    str(o).strip().lower() in ("mr", "mrs", "ms", "dr", "mx", "miss")
                    for o in options
                )
            )
        ):
            return {"answer": "Mr", "kind": "single_select", "field": "candidate.salutation", "confidence": 1}

        if "notice period" in nq:
            return {"answer":str(self.profile["candidate"]["notice_period_days"]),"kind":"number","field":"candidate.notice_period_days","confidence":1}
        if any(x in nq for x in ("years of experience","years experience","how many years","how much experience")):
            # Skill/total experience is explicitly 0 in the supplied profile.
            return {"answer":"0","kind":"number","field":"experience","confidence":0.9}

        if self._is_yes_no(nq):
            project_yn = self._project_experience_yes_no(q)
            if project_yn is not None:
                answer_options = [
                    x for x in (options or [])
                    if self._norm(x) not in {
                        "save", "continue", "next", "submit",
                        "submit application", "apply", "apply now",
                        "send", "send application", "finish", "done",
                        "skip", "back", "cancel",
                    }
                ]
                if answer_options:
                    matched = self._match_option(
                        project_yn,
                        answer_options,
                        nq,
                    )
                    if matched is None:
                        return None
                    project_yn = matched

                return {
                    "answer": project_yn,
                    "kind": "yes_no",
                    "field": "projects",
                    "confidence": 1.0,
                }

            yn=self._local_yes_no(nq)
            if yn is not None:
                # "Save"/"Continue"/"Submit" are action controls, not answer
                # choices. Never let them turn a profile-grounded Yes/No into
                # UNKNOWN. Only map the semantic answer when a real answer
                # option is actually present.
                answer_options = [
                    x for x in (options or [])
                    if self._norm(x) not in {
                        "save", "continue", "next", "submit",
                        "submit application", "apply", "apply now",
                        "send", "send application", "finish", "done",
                        "skip", "back", "cancel"
                    }
                ]
                if answer_options:
                    matched = self._match_option(yn, answer_options, nq)
                    if matched is None:
                        return None
                    yn = matched
                return {"answer":yn,"kind":"yes_no","field":"profile","confidence":1.0}

        # Project-grounded descriptive answers for common open-text prompts.
        if any(x in nq for x in (
            "describe your experience",
            "describe your work",
            "tell us about your experience",
            "tell us about your relevant experience",
            "relevant experience",
            "describe your background",
            "what experience do you have",
        )):
            if "rag" in nq:
                return {
                    "answer": "I have hands-on project experience building a document-based RAG application using document processing, embeddings, FAISS vector similarity search, source citations, and Streamlit. I am a fresher, so this is project experience rather than professional employment.",
                    "kind": "text",
                    "field": "projects.Document-based RAG Application",
                    "confidence": 0.95
                }
            if "python" in nq:
                return {
                    "answer": "I have hands-on project experience using Python for AI/ML and GenAI development, including data processing, model-related work, APIs, and application development. I am a fresher, so this is project experience rather than professional employment.",
                    "kind": "text",
                    "field": "skills.Python",
                    "confidence": 0.9
                }

        # Common Naukri programming-ability question. The supplied profile
        # documents Python, C++, Java and C plus multiple hands-on projects,
        # so when the visible choices contain the strongest matching option,
        # select it rather than stopping as UNKNOWN.
        if "programming ability" in nq or "programming skills" in nq or "coding ability" in nq:
            if options:
                for opt in options:
                    no = self._norm(opt)
                    if (
                        "strong in at least one language" in no
                        and "independently solve coding problems" in no
                    ):
                        return {
                            "answer": opt,
                            "kind": "single_select",
                            "field": "skills.programming_ability",
                            "confidence": 0.95,
                        }
            return None

        # Generic multi-select: match option labels to actual profile skills.
        if options and self._looks_multi(nq):
            matches=[]
            for opt in options:
                if self._option_matches_profile(opt):
                    matches.append(opt)
            if matches:
                return {"answer":matches,"kind":"multi_select","field":"skills","confidence":0.8}

        return None

    def _project_experience_answer(self, q, options):
        """
        Resolve project-experience category questions from the projects that
        are actually present in profile.json.

        The current profile contains three substantive AI/ML projects. It
        does NOT state that they were academic/hackathon-only, so the truthful
        category is the 'built ... independently or as a major contributor'
        option when that option is offered.
        """
        nq = self._norm(q)

        if not any(
            phrase in nq
            for phrase in (
                "project experience",
                "project background",
                "software project",
                "projects experience",
                "experience with projects",
                "project work",
                "ai project",
                "ai projects",
                "ai application",
                "ai applications",
                "projects or applications",
                "applications you have built",
                "projects you have built",
                "applications you have developed",
                "projects you have developed",
                "your projects",
                "what are your projects",
                "what projects have you worked on",
                "what projects have you built",
                "what projects have you developed",
                "which projects have you worked on",
                "describe your projects",
                "tell us about your projects",
                "tell me about your projects",
                "talk about your projects",
                "project portfolio",
            )
        ):
            return None

        projects = self.profile.get("projects", []) or []
        has_projects = any(
            isinstance(project, dict)
            and (
                str(project.get("title", "")).strip()
                or str(project.get("details", "")).strip()
            )
            for project in projects
        )

        if not has_projects:
            return None

        # Open-ended AI-project/application questions are known
        # profile-grounded questions. Resolve them deterministically before
        # Gemini so malformed/truncated model JSON can never turn a truthful
        # profile question into UNKNOWN.
        #
        # Important Naukri edge case: the conversational panel can still expose
        # a previous answer bubble such as "Yes" as a visible button. That is
        # not an answer choice for the current open-ended question. Treat a
        # yes/no-only option set as UI transcript noise for an explicitly
        # open-ended project prompt.
        nq = self._norm(q)
        open_project_prompt = any(marker in nq for marker in (
            "explain", "describe", "tell us", "tell me", "briefly",
            "projects or applications", "applications you have built",
            "projects you have built", "your projects",
        )) and not any(nq.startswith(prefix) for prefix in (
            "do you ", "have you ", "are you ", "can you ", "did you ",
        ))

        meaningful_options = [
            str(opt).strip() for opt in (options or [])
            if str(opt).strip().lower() not in {"yes", "no"}
            and self._norm(opt) not in {
                "save", "continue", "next", "submit", "submit application",
                "apply", "apply now", "send", "finish", "done", "skip",
                "back", "cancel", "review",
            }
        ]
        raw_option_norms = {self._norm(opt) for opt in (options or [])}
        yes_no_prompt = any(
            nq.startswith(prefix) for prefix in (
                "do you ", "have you ", "are you ", "can you ", "did you ",
                "would you ", "could you ", "will you ",
            )
        ) or ({"yes", "no"} <= raw_option_norms)

        # Only treat an empty/non-choice option set as transcript noise for a
        # genuinely open-ended prompt. A real Yes/No project question must
        # remain owned by the project yes/no logic above.
        if open_project_prompt or (not meaningful_options and not yes_no_prompt):
            titles = []
            for project in projects:
                if not isinstance(project, dict):
                    continue
                title = str(project.get("title", "")).strip()
                details = str(project.get("details", "")).strip()
                if title:
                    titles.append(
                        f"{title} ({details})" if details else title
                    )

            if titles:
                # Recruiter prompts often explicitly ask for a brief explanation.
                # Keep the deterministic response concise while staying grounded
                # in the actual project titles stored in profile.json.
                short_titles = [str(project.get("title", "")).strip() for project in projects if isinstance(project, dict) and str(project.get("title", "")).strip()]
                answer = (
                    "I have built AI/GenAI projects including "
                    + ", ".join(short_titles)
                    + ". These projects involve Python, LLMs, RAG, automation, APIs and AI-driven application development."
                )
                return {
                    "answer": answer,
                    "kind": "text",
                    "field": "projects",
                    "confidence": 1.0,
                }

        options = options or []
        normalized_options = [
            (self._norm(opt), opt)
            for opt in options
        ]

        # Prefer the strongest truthful category present in the UI.
        for norm, raw in normalized_options:
            if (
                "built and completed" in norm
                and (
                    "independently" in norm
                    or "major contributor" in norm
                )
                and (
                    "full stack" in norm
                    or "backend" in norm
                    or "ai application" in norm
                )
            ):
                return {
                    "answer": raw,
                    "kind": "single_select",
                    "field": "projects",
                    "confidence": 0.95,
                }

        # A fallback for equivalent wording.
        for norm, raw in normalized_options:
            if (
                ("independently" in norm or "major contributor" in norm)
                and (
                    "built" in norm
                    or "developed" in norm
                    or "application" in norm
                )
                and (
                    "project" in norm
                    or "application" in norm
                    or "software" in norm
                    or "ai" in norm
                )
            ):
                return {
                    "answer": raw,
                    "kind": "single_select",
                    "field": "projects",
                    "confidence": 0.9,
                }

        # We intentionally do NOT select academic/hackathon-only because
        # profile.json does not make that claim.
        return None

    def _project_experience_yes_no(self, q):
        nq = self._norm(q)
        projects = self.profile.get("projects", []) or []
        has_projects = any(
            isinstance(project, dict)
            and (
                str(project.get("title", "")).strip()
                or str(project.get("details", "")).strip()
            )
            for project in projects
        )

        if not has_projects:
            return None

        if any(
            phrase in nq
            for phrase in (
                "do you have project experience",
                "do you have any project experience",
                "have you built any projects",
                "have you completed any projects",
                "have you built software projects",
            )
        ):
            return "Yes" if has_projects else "No"

        return None

    def _local_yes_no(self, q):
        p = self.profile
        # Explicit candidate preferences / status.
        if "relocat" in q:
            return "Yes" if p.get("preferences",{}).get("willing_to_relocate") else "No"
        if "visa sponsorship" in q or "sponsorship" in q:
            return "Yes" if p.get("candidate",{}).get("visa_sponsorship_required") else "No"
        if "currently employed" in q or "currently working" in q:
            return "Yes" if p.get("candidate",{}).get("currently_employed") else "No"
        if "active offer" in q or "have an offer" in q:
            return "Yes" if p.get("candidate",{}).get("has_active_offer") else "No"
        if "join immediately" in q or "available to join" in q:
            return "Yes" if p.get("candidate",{}).get("available_to_join_immediately") else "No"
        if "bond" in q:
            return "Yes" if p.get("candidate",{}).get("employment_bond_willing") else "No"
        if "night shift" in q or "night shifts" in q:
            return "Yes" if p.get("candidate",{}).get("night_shift") else "No"
        if "work from office" in q or "work in office" in q or "onsite" in q or "on-site" in q:
            return "Yes" if p.get("candidate",{}).get("onsite") else "No"
        if "remote" in q or "work from home" in q:
            return "Yes" if p.get("candidate",{}).get("remote") else "No"
        if "hybrid" in q:
            return "Yes" if p.get("candidate",{}).get("hybrid") else "No"
        if "authorized to work in india" in q or "legally authorized to work" in q:
            return "Yes" if p.get("candidate",{}).get("authorized_to_work_in_india") else "No"

        # CGPA threshold questions are derived deterministically from 6.8.
        m = re.search(r"(?:less than|below|under)\s*(\d+(?:\.\d+)?)\s*cgpa", q)
        if not m:
            m = re.search(r"cgpa\s*(?:less than|below|under)\s*(\d+(?:\.\d+)?)", q)
        if m:
            threshold=float(m.group(1))
            cgpa=float(p.get("candidate",{}).get("cgpa", 6.8))
            return "Yes" if cgpa < threshold else "No"
        m = re.search(r"(?:at least|greater than or equal to|more than or equal to|7\s*or\s*more)\s*(\d+(?:\.\d+)?)\s*cgpa", q)
        if m:
            threshold=float(m.group(1))
            cgpa=float(p.get("candidate",{}).get("cgpa", 6.8))
            return "Yes" if cgpa >= threshold else "No"
        if "cgpa" in q and any(x in q for x in ("do you have","have you","is your")):
            if "7 or more" in q or "at least 7" in q or "7 or above" in q:
                return "No" if float(p.get("candidate",{}).get("cgpa",6.8)) < 7 else "Yes"
            if "less than 7" in q or "below 7" in q or "under 7" in q:
                return "Yes" if float(p.get("candidate",{}).get("cgpa",6.8)) < 7 else "No"

        # Confirmed project/academic experience, but not professional internship.
        if (
            ("internship" in q and ("project" in q or "hackathon" in q or "academic" in q))
            or ("academic project" in q and "hackathon" in q)
        ) and any(x in q for x in ("completed","have you","did you","experience")):
            return "Yes"

        # Explicit internship-only question is No.
        if "internship" in q and not any(x in q for x in ("project","hackathon","academic")):
            return "No"

        # Skill existence questions: truthful project/hands-on familiarity.
        skills = p.get("skills", [])
        if isinstance(skills, dict):
            skills = list(skills.keys())
        for skill in skills:
            ns=self._norm(skill)
            if ns and ns in q and any(x in q for x in ("do you have","have you","worked with","used","familiar","hands on","hands-on","experience")):
                return "Yes"
        # Explicit API experience confirmed by user.
        for api, enabled in p.get("api_experience",{}).items():
            if enabled and self._norm(api) in q and any(x in q for x in ("experience","worked","used","have you","do you have")):
                return "Yes"
        return None

    def _match_cgpa_option(self, question, options):
        """
        Map the candidate's numeric CGPA to a visible CGPA bucket.
        This is deliberately restricted to CGPA questions.
        """
        q = self._norm(question)
        if "cgpa" not in q or not options:
            return None

        try:
            candidate_cgpa = float(
                self.profile.get("candidate", {}).get("cgpa")
            )
        except (TypeError, ValueError):
            return None

        def contains_cgpa(option):
            # Keep the raw option because _norm() intentionally removes
            # punctuation such as the hyphen in "6-7" and the plus in "7+".
            raw = str(option or "").strip()
            o = self._norm(raw)
            raw_low = raw.lower()

            # Less than / below / under / <
            m = re.search(
                r"(?:less than|below|under|<)\s*(\d+(?:\.\d+)?)",
                raw_low,
            )
            if m:
                return candidate_cgpa < float(m.group(1))

            # <= / at most
            m = re.search(
                r"(?:less than or equal to|at most|<=)\s*(\d+(?:\.\d+)?)",
                raw_low,
            )
            if m:
                return candidate_cgpa <= float(m.group(1))

            m = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:or below|and below)",
                raw_low,
            )
            if m:
                return candidate_cgpa <= float(m.group(1))

            # Greater than / above / more than / >
            m = re.search(
                r"(?:greater than|more than|above|over|>)\s*(\d+(?:\.\d+)?)",
                raw_low,
            )
            if m:
                return candidate_cgpa > float(m.group(1))

            # >= / at least / or above / +
            m = re.search(
                r"(?:greater than or equal to|at least|>=)\s*(\d+(?:\.\d+)?)",
                raw_low,
            )
            if m:
                return candidate_cgpa >= float(m.group(1))

            m = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:or above|and above|\+)",
                raw_low,
            )
            if m:
                return candidate_cgpa >= float(m.group(1))

            # Ranges such as 6-7, 7 to 8, 7–8.
            m = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(\d+(?:\.\d+)?)",
                raw_low,
            )
            if m:
                lo = float(m.group(1))
                hi = float(m.group(2))
                return lo <= candidate_cgpa <= hi

            m = re.search(
                r"between\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)",
                raw_low,
            )
            if m:
                lo = float(m.group(1))
                hi = float(m.group(2))
                return lo <= candidate_cgpa <= hi

            return False


        matches = [
            option
            for option in options
            if contains_cgpa(option)
        ]

        # Never guess if the visible buckets overlap or are ambiguous.
        return matches[0] if len(matches) == 1 else None

    def _match_option(self, answer, options, question=None):
        """
        Map a semantic Yes/No answer onto the actual on-screen option text.
        Real controls are rarely a bare "Yes"/"No" (e.g. "Yes, I have hands-on
        experience", a checkbox label, trailing punctuation). This first tries
        an exact normalized match, then falls back to a substring match in
        either direction, then to a leading-word match ("Yes" vs "Yes, I..."),
        so a correct semantic answer isn't discarded just because the button
        text isn't a literal "Yes"/"No". Returns None only if nothing on
        screen plausibly corresponds to the answer.
        """
        if question:
            cgpa_match = self._match_cgpa_option(
                question,
                options,
            )
            if cgpa_match is not None:
                return cgpa_match

        na = self._norm(answer)
        norm_options = [(self._norm(x), x) for x in options]

        # 1) Exact normalized match.
        for no, original in norm_options:
            if no == na:
                return original

        # 2) Substring match either direction (handles "Yes, I have ..." etc).
        for no, original in norm_options:
            if na and (na in no or no in na):
                return original

        # 3) Leading-word match: option starts with the same word ("yes"/"no").
        for no, original in norm_options:
            if no.split(" ")[:1] == na.split(" ")[:1] and na.split(" ")[:1] != ['']:
                return original

        return None

    def _option_matches_profile(self, option):
        o=self._norm(option)

        # Only aliases backed by an explicit profile skill/project are allowed.
        aliases={
            "python": ["python"],
            "llm apis openai gemini anthropic": ["google gemini api", "llms"],
            "rag vector databases": ["rag", "faiss", "chromadb"],
            "tool function calling": [],  # not claimed by the supplied profile
            "langchain langgraph": ["langchain"],
            "prompt engineering": ["prompt engineering"],
            "machine learning": ["machine learning", "pytorch", "tensorflow", "scikit-learn"],
            "deep learning": ["deep learning", "pytorch", "tensorflow"],
            "generative ai": ["generative ai", "llms", "google gemini api"],
        }
        if o in aliases:
            if not aliases[o]:
                return False
            return any(
                self._norm(alias) in self._norm(skill)
                or self._norm(skill) in self._norm(alias)
                for alias in aliases[o]
                for skill in self.profile.get("skills", [])
            )

        # Exact/near-exact skill match only. Do not infer arbitrary technologies
        # from generic words in a question or option.
        for skill in self.profile.get("skills", []):
            ns=self._norm(skill)
            if len(ns) >= 3 and len(o) >= 3 and (o == ns or o in ns or ns in o):
                return True
        return False

    def _looks_multi(self,q):
        return any(x in q for x in (
            "which of the following", "select all", "select the",
            "which technologies", "what technologies", "which skills",
            "what skills", "choose all"
        ))

    def _is_yes_no(self,q):
        return q.startswith(("do you ","did you ","have you ","are you ","can you ","would you ","will you ","is your ","require ")) or "yes or no" in q

    def _public_profile(self):
        # Contact facts are legitimate application answers (for example,
        # city, nationality, email, phone, and postal code).  The semantic
        # fallback must see them, while deterministic rules remain first.
        p=json.loads(json.dumps(self.profile))
        return p

    def _clean_options(self, options):
        """Normalize real answer choices while dropping page-level action controls.

        Browser adapters sometimes see Save/Next/Apply buttons while they are
        collecting visible controls. Those are not answer choices and must never
        change the semantic meaning of an open-ended question.
        """
        action_tokens = {
            "save", "continue", "next", "submit", "submit application",
            "apply", "apply now", "send", "send application", "finish",
            "done", "skip", "back", "cancel", "previous", "review",
        }
        out=[]
        for x in options or []:
            x=self._clean(x)
            if not x or len(x)>180:
                continue
            nx=self._norm(x)
            if nx in action_tokens or nx.startswith(("save ", "continue ", "submit ")):
                continue
            if x not in out:
                out.append(x)
        return out[:50]

    def _clean(self,x):
        return re.sub(r"\s+"," ",str(x or "")).strip()

    def _norm(self,x):
        return re.sub(r"[^a-z0-9]+"," ",str(x or "").lower()).strip()

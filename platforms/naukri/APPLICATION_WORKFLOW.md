# Naukri application workflow

Authoritative implementation: `../../naukri_agent.py`.

`application_engine.py` is the platform boundary and delegates to that proven
agent; it does not import Indeed or LinkedIn application logic.

Search -> Applied pre-filter -> fresh job tab -> JD/experience/AI checks ->
Naukri native Apply or external company-site route -> Naukri/external form
handling -> answer verification -> Continue/Next -> final submission gate.

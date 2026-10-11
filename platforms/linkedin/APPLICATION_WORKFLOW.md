# LinkedIn application workflow

Authoritative implementation: `src/application/linkedin/linkedin_agent.py`.

Search controller -> collect job URLs -> **if zero URLs, stop the role search**
-> fresh job tab -> JD/experience checks -> route detection -> LinkedIn Easy
Apply OR external Apply/interstitial -> corresponding form engine -> verify ->
next job.

The zero-result stop is a regression-protected LinkedIn-specific behavior.

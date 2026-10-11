# LinkedIn external Apply regression fix

Restored the V38 controlled external-company flow in `platforms/linkedin/linkedin_agent.py`: validated external CTA -> click -> adopt resulting non-LinkedIn page -> CompanyWebsiteAgent.

The source job tab remains open, and CAPTCHA/OTP/security states are still handled as stop points by the company-site engine.

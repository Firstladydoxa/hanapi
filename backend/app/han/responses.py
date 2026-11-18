"""Translator-facing response patterns (spec §3.2). Wording is fixed so the experience stays consistent."""

SUCCESS = "Here is my suggested translation:\n\n{translation}\n\nPlease review it and make any corrections before approving it."
MISSING_CONTEXT = "Is this intended for a formal or informal audience? A little context will help me prepare a more suitable translation."
UNCERTAIN_TERM = "I'm not fully confident about this term in the given context. I've highlighted it for your review."
UNAVAILABLE = "I'm sorry, I couldn't complete the translation at the moment. Please try again shortly."
DRAFT_SAVED = "Your translation draft is ready and has been saved to the project for review."
APPROVAL_RECORDED = "Your approved translation has been saved to the project's Translation Memory."

ASK_TEXT = "What text would you like me to translate?"
ASK_TARGET = "Which language would you like me to translate this into?"
ASK_SOURCE = "Which language is the original text written in?"
UNSUPPORTED = (
    "I can't offer an automated draft for that language pair yet. "
    "Please contact TNI to arrange translation by a qualified human translator."
)
ENGINE_DEFLECTION = (
    "HAN manages the translation process for you, so I can't share details about how a draft was produced. "
    "What matters is the result: please review the suggestion carefully and edit it as needed."
)
APPROVAL_EXPLANATION = (
    "Approval is always your decision. I can't approve a translation on your behalf. "
    "When you're happy with a version, use the Approve button in the review panel and it will be recorded under your name."
)
INTRO = (
    "Hello, I'm HAN. I can prepare translation drafts for your review, check them against approved terminology and "
    "your project's Translation Memory, and help you revise them. Try: \"Translate this text from English to German: ...\""
)
QUOTA = "This project has reached its translation allowance. Please contact your project manager."
UNKNOWN_LANGUAGE = "I don't recognise that language yet. Could you tell me its name or code (for example, \"German\" or \"de\")?"
HELP_FALLBACK = (
    "I can help with translation requests. For example: \"Translate this text from English to German: ...\". "
    "Tell me the languages and paste the text, and I'll prepare a draft for your review."
)

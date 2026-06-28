"""
Golden eval dataset — matched to our use case: an AI tutor for career switchers / upskillers.

Single-turn cases are grounded in `retrieval_context` (for faithfulness) and use realistic tutoring
Q&A; the multi-turn case is a Python-learning dialogue for a career switcher (consistency / knowledge
retention / role adherence). Deliberately NOT generic trivia — the content mirrors what the agents
actually do (explain concepts, build plans, analyze jobs).
"""

from deepeval.test_case import ConversationalTestCase, LLMTestCase, Turn

# ── Grounding (what a faithful answer must not contradict) ────────────────────
_OVERFITTING_CTX = [
    "Overfitting is when a model learns the training data too well — including its noise — so it "
    "performs well on training data but poorly on unseen data. It is mitigated with regularization, "
    "more data, dropout, and cross-validation.",
]

# ── Single-turn: a tutor answering a learner's doubt ──────────────────────────
FAITHFUL_DOUBT = LLMTestCase(
    input="What is overfitting in machine learning, and how do I avoid it?",
    actual_output=(
        "Overfitting is when your model memorizes the training data — including its noise — so it "
        "scores well on training data but generalizes poorly to new data. You can reduce it with "
        "regularization, more training data, dropout, and cross-validation."
    ),
    retrieval_context=_OVERFITTING_CTX,
)

# Negative control: contradicts the grounding (should score LOW on faithfulness/accuracy).
UNFAITHFUL_DOUBT = LLMTestCase(
    input="What is overfitting in machine learning, and how do I avoid it?",
    actual_output=(
        "Overfitting means your model is too simple and underperforms even on the training data. "
        "You fix it by removing all regularization and training for far fewer epochs."
    ),
    retrieval_context=_OVERFITTING_CTX,
)

# ── Multi-turn: tutor guiding a career switcher learning Python ───────────────
TUTOR_CONVERSATION = ConversationalTestCase(
    chatbot_role="a warm, accurate programming tutor helping a career switcher learn Python",
    scenario="A learner moving into a data role is learning Python fundamentals.",
    expected_outcome="The tutor explains clearly, stays consistent, remembers earlier turns, and stays in the tutor role.",
    turns=[
        Turn(role="user", content="I'm switching careers into data. Can you teach me about Python lists?"),
        Turn(
            role="assistant",
            content=(
                "Of course! A Python list is an **ordered, mutable** collection, e.g. `nums = [1, 2, 3]`. "
                "You can index it (`nums[0]` → 1) and add to it with `nums.append(4)`."
            ),
        ),
        Turn(role="user", content="How do I add an item to it again?"),
        Turn(
            role="assistant",
            content=(
                "Use `.append()`, like I showed: `nums.append(4)` adds 4 to the end. To insert at a "
                "specific position, use `nums.insert(0, 99)`."
            ),
        ),
        Turn(role="user", content="Remind me — what data type did we say a list is?"),
        Turn(
            role="assistant",
            content=(
                "A list is an **ordered, mutable** collection — exactly what we covered. 'Mutable' means "
                "you can change it in place after you create it."
            ),
        ),
    ],
)

# (agent_name, test_case) pairs the suite iterates over.
SINGLE_TURN_GOLDEN = [("doubt_solver", FAITHFUL_DOUBT)]
CONVERSATIONS_GOLDEN = [("assistant", TUTOR_CONVERSATION)]

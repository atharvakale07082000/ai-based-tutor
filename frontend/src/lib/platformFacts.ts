/**
 * Numbers the marketing surface states as fact.
 *
 * These are claims about the product, so they must match the product. They live in one
 * file — rather than inline in the page — because they are pinned from the backend by
 * `backend/tests/test_platform_facts.py`, which reads the real source and fails if it
 * drifts:
 *
 *   SUB_SKILLS_RATED / CURRICULUM_DOMAINS  ←  the topic graph in
 *                                             `backend/app/prompts/curriculum.yaml`
 *
 * The previous inline value ("32 sub-skills", stated in two places) was wrong, and
 * nothing connected it to the code, so nothing caught it. If a claim can't be pinned to
 * a source this way, don't put a number on it.
 *
 * The hero's agent count is deliberately NOT here: it is rendered as `AGENTS.length`
 * from the very list the page shows beneath it, so the number and the roster cannot
 * disagree.
 */

/** Sub-skills in the curriculum topic graph, across every domain. */
export const SUB_SKILLS_RATED = 108

/** Domains those sub-skills are grouped under. */
export const CURRICULUM_DOMAINS = 14

---
name: curriculum-design
description: Sequence a personalized learning path from the learner's goals and proficiency gaps using the topic graph.
allowed-tools: classify_topic get_topic_graph get_proficiency web_search
---

# Curriculum design

Build an ordered path from what the learner knows toward what they want to reach.

1. Call `classify_topic` on the learner's stated goal to map free text to a domain.
2. Call `get_topic_graph` to pull the domain's subtopics and their dependencies.
3. Call `get_proficiency` to read the learner's Elo per topic. Order subtopics by
   proficiency gap — lowest Elo (biggest gap) first — while respecting prerequisite
   order from the graph. Skip topics already mastered (Elo ≥ 700).
4. For a fast-moving field, optionally call `web_search` to surface currently
   in-demand subtopics worth adding.
5. Present the path as an ordered list: each step = subtopic + one line on why it
   comes here. Keep it to a sensible length (cap ~8-10 steps); don't dump the graph.

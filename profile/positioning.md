# Positioning angles — which parts of the profile to lead with

This file has two jobs: (1) tell the CV tailoring step which "story" to tell for a
given role, and (2) help you **filter jobs at search time** — if a posting doesn't
map to one of these angles with real proof, it's probably not worth applying to.

Each angle lists the `headline_variants` key to use, the tags to pull bullets by
(see `tags` in master-profile.yaml), and the strongest proof points.

## 1. Full-Stack Tech Lead  (default / strongest)
- Headline: `full_stack_lead`
- Lead tags: full-stack, leadership, architecture, ci-cd, quality
- Proof: Mindler end-to-end ownership + release velocity; NN architect; Finner CTO.
- Best-fit postings: "lead", "architecture", "full-stack", "mentor", "CI/CD", "own features end-to-end".

## 2. Product / Conversion Engineer
- Headline: `product_engineer`
- Lead tags: conversion, product, metric, performance, payments
- Proof: 5%→21% booking conversion, CSAT 3→4.8, Stripe/in-app billing, A/B + feature flags.
- Best-fit postings: growth/acquisition squads, experimentation, funnels, subscriptions, SEO.

## 3. Backend / Principal (distributed, regulated)
- Headline: `backend_principal`
- Lead tags: backend, distributed, architecture, reliability, regulated, security
- Proof: ~20 services + actor model, DLQ incident response, open-banking MVP, CQRS-ES.
- Best-fit postings: "principal/staff", event-driven, high-availability, fintech/health/insurance.

## 4. Mobile Product (React Native)
- Headline: `mobile_product`
- Lead tags: mobile, full-stack, product, ci-cd
- Proof: Mindler RN + Expo CNG / EAS and App Store + Play Store release; ParkNow; The Future Group RN products.
- Best-fit postings: React Native / Expo apps, consumer mobile, small teams.

## 5. AI-Native Engineer
- Headline: `ai_native`
- Lead tags: ai-native, architecture, tooling, leadership
- Proof: vivief/devAC MCP server, Mindler Answers, daily Claude Code / Cursor spec-driven work.
- Best-fit postings: AI-forward teams, agentic workflows, dev-tooling, "AI-native".

## Scheduling / Operations (cross-cutting differentiator)
Not a standalone angle, but a strong wedge when the domain is scheduling, planning,
logistics or operational efficiency (e.g. Zymego). Add tags: scheduling, operations,
erp, systems-thinking — pull Mivon, DiMS!, TechBuddy.

---

### Job-fit quick test (use before writing a CV)
1. Which angle above does the posting map to? (If none → skip or downgrade priority.)
2. Do I have ≥3 tagged proof points for that angle? (If not → weaker application.)
3. Does the domain hit a wedge (scheduling/ops, regulated, AI-native)? (Bonus.)
Record the answer in the application's `meta.yaml` (`angle`, `fit_score`).
